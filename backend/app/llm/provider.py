"""
Abstracción del proveedor de LLM.

Toda la lógica del sistema habla con esta interfaz (`LLMProvider`), NUNCA con Gemini/Claude/DeepSeek/
OpenAI directamente. El proveedor se elige solo con `LLM_PROVIDER` (registro `_PROVIDERS`), sin tocar el
pipeline. Proveedor activo por defecto: Gemini 2.5 Flash. Modalidades de resguardo de la información:
  - API pública del proveedor:  gemini · anthropic · deepseek · groq · github
  - Nube privada o dedicada:    openai_compat (Azure OpenAI, Vertex AI, Bedrock, gateway institucional)
  - Modelo local en la red:     local (Ollama / vLLM, modelos de pesos abiertos)

El LLM no garantiza JSON-schema estricto, así que cada método:
  1) pide JSON con prompts MUY explícitos en español,
  2) parsea + valida con Pydantic (schemas/llm.py),
  3) reintenta con backoff exponencial; si agota, propaga LLMError.
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..config import settings
from ..schemas.llm import (
    BriefingOut,
    ContradiccionesResponse,
    HechosResponse,
    HojaCompletada,
)

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Falla irrecuperable del LLM tras agotar reintentos."""


# ---------------------------------------------------------------------------
#  Prompts (español, explícitos, sin preámbulo) — adaptados a Groq
# ---------------------------------------------------------------------------
_EXTRACT_SYS = """Eres un analista de operaciones del Ejército de Chile. Extrae los hechos
operacionales del documento entregado. Responde SOLO con un JSON válido (sin preámbulo,
sin texto adicional, sin markdown) con esta estructura exacta:
{
  "hechos": [
    {
      "evento": "qué ocurrió",
      "ocurrido_en": "cuándo (ISO 8601 si es posible, si no, vacío)",
      "ubicacion": "dónde (área/lugar)",
      "responsable": "quién (unidad/responsable)",
      "impacto": "impacto en personas/medios/servicio",
      "estado": "ABIERTO|EN_CURSO|CERRADO",
      "texto_origen": "cita textual exacta del documento que respalda el hecho"
    }
  ]
}
Reglas: no inventes datos; si un campo no aparece, déjalo como cadena vacía "".
Incluye SIEMPRE "texto_origen" con la cita textual exacta. Usa terminología institucional.
Si no hay hechos claros, devuelve {"hechos": []}."""

_SYNTH_SYS = """Eres un asesor de operaciones del Ejército de Chile. A partir de los HECHOS ya
extraídos (no de los documentos crudos), redacta un briefing operacional institucional.
Responde SOLO con un JSON válido (sin preámbulo, sin markdown) con esta estructura:
{
  "resumen_ejecutivo": ["5 a 10 bullets ejecutivos"],
  "asuntos_criticos": [{"asunto":"...","impacto":"...","responsable":"..."}],
  "proyeccion_24_72h": "proyección de las próximas 24 a 72 horas",
  "situacion": {"resumen":"panorama operacional general (situación) en 2-4 frases","aspectos":["aspecto relevante de la situación","..."]},
  "personal": {
    "parte_fuerza_institucional": {"OF":"-.-","SOF":"-.-","ECP":"-.-","SLTP":"-.-","ESCMIL":"-.-","ESCSOF":"-.-","ESCSERV":"-.-","personal_civil":"-.-","SLC":"-.-","total":"-.-"},
    "slc": {"clase_2006":"-.-","clase_2007":"-.-","total":"-.-"},
    "macrozonas": [{"zona":"...","fuerza":"-.-","forman":"-.-","faltan":"-.-"}],
    "catastrofe": {"fuerza":"-.-","forman":"-.-","faltan":"-.-"},
    "unidades_emergencia": {"ufec":"-.-","brife":"-.-","parme":"-.-"}
  },
  "inteligencia": {
    "incidentes_institucionales": [{"tipo":"...","descripcion":"..."}],
    "incidentes_mootw": [{"tipo":"...","unidad":"...","descripcion":"..."}],
    "sistema_alerta": [{"alerta":"...","area":"...","unidad_asociada":"...","apreciacion":"..."}],
    "analisis_meteo": "...",
    "proyeccion_meteo_48h": "..."
  },
  "operaciones": {
    "ops_catastrofe": [{"cantidad":"-.-","tipo":"...","unidad_origen":"...","zona_empleo":"...","inicio_empleo":"..."}],
    "relevos_norte": [{"n":"...","fecha":"...","jaf":"...","unidades":"...","periodo":"..."}],
    "relevos_sur": [{"n":"...","fecha":"...","ft":"...","unidades":"...","periodo":"..."}],
    "ops_antartica": [{"bae":"...","dotacion_estival":"-.-","cpccgu":"..."}],
    "ops_extranjero": [{"operacion":"...","efectivos":"-.-","ubicacion":"...","repliegue":"..."}],
    "guardian_soberano": [{"jaf":"...","fuerza":"-.-","planif":"-.-","ejecut":"-.-"}],
    "unidades_terreno_kpi": {"unidades_en_terreno":"-.-","fuerza_en_terreno":"-.-","lugares_activos":"-.-","actividad_principal":"..."},
    "traslados_uac": [{"uac":"...","unidades":"-.-"}],
    "unidades_terreno": [{"actividad":"...","comando_matriz":"...","ur":"...","fechas":"...","ubicacion":"...","fuerza":"-.-"}],
    "despliegue_mapa": {"mzn":"-.-","mzs":"-.-","antartica":"-.-"}
  },
  "logistica": {
    "resumen": {"total":"-.-","nop":"-.-"},
    "operacionalidad": [{"unidad":"...","total":"-.-","nop":"-.-","campana":"-.-","combate":"-.-","administrativos":"-.-","eq_ingenieros":"-.-"}]
  },
  "trazabilidad": {"resumen_ejecutivo[0]": ["id-de-hecho", "..."]}
}
Reglas: el briefing DEBE incluir un resumen por sección (RF-004): "situacion" (panorama
general), "personal", "logistica", incidentes (en "inteligencia") y meteorología (en
"inteligencia.analisis_meteo"); completa "situacion" con lo que aporten los hechos/contexto.
Cada bullet/casilla con dato debe poder rastrearse a los hechos que lo originan;
incluye sus ids en "trazabilidad" usando como clave la ruta del bullet (p.ej. "resumen_ejecutivo[0]").
Donde no haya dato, usa "-.-". No inventes cifras. Mantén entre 5 y 10 bullets en resumen_ejecutivo.
Si en "parametros.contexto_fuentes" aparecen cifras o datos (personal OF/SOF/ECP/total, fuerzas por
macrozona, operacionalidad/NOP con sus categorías campaña/combate/administrativos/eq_ingenieros,
unidades de emergencia UFEC/BRIFE/PARME, guardián soberano con trabajos de tierra planificados/
ejecutados, traslados por UAC, despliegue por macrozona MZN/MZS/Antártica, relevos con su periodo,
meteorología, incidentes), ÚSALOS para completar las casillas institucionales correspondientes;
si no aparecen en el contexto ni en los hechos, deja "-.-". En "traslados_uac" usa el nombre corto
de la UAC tal como aparezca en la fuente (p.ej. "I DE", "COPE", "CAF")."""

_CONTRA_SYS = """Eres un analista de operaciones del Ejército de Chile. Te entrego una lista de
HECHOS (cada uno con su id). Identifica solo CONTRADICCIONES REALES: dos o más hechos que
describen el MISMO evento/situación pero con datos INCOMPATIBLES entre sí (cifras distintas,
estados opuestos como ABIERTO vs CERRADO, fechas o ubicaciones que no calzan, afirmaciones
que se excluyen).
REGLAS IMPORTANTES:
- NO marques como contradicción los hechos meramente repetidos o idénticos (eso es duplicado,
  no contradicción). Si el contenido coincide, NO es contradicción.
- En "descripcion" explica el conflicto en lenguaje natural claro (qué dato choca con qué),
  SIN escribir ids ni UUIDs en el texto. Los ids van solo en "hechos_involucrados".
Responde SOLO con JSON válido:
{"contradicciones":[{"descripcion":"...","hechos_involucrados":["id1","id2"],"severidad":1}]}
severidad: 1 baja, 2 media, 3 alta. Si no hay contradicciones reales, devuelve {"contradicciones": []}."""

_HOJA_SYS = """Eres un asesor de operaciones del Ejército de Chile. El mando pidió una HOJA ADICIONAL
para el reporte institucional. Recibes: la hoja ("titulo", "seccion", "instrucciones" del mando y
"bloques" con el formato que eligió el usuario), los HECHOS extraídos (cada uno con su id) y el
"contexto_fuentes" (texto de los documentos). Completa la hoja SOLO con datos presentes en los
hechos/contexto. Si "documentos_adjuntos" no está vacío, el "contexto_fuentes" contiene el texto de esos
documentos (cada uno encabezado por [nombre]) y son la fuente PRINCIPAL: extrae de ellos toda la
información relevante (cifras, tablas, listados, fechas, unidades) y vuélcala en los bloques; una tabla
del documento debe quedar como bloque "tabla" con sus mismas columnas y filas. Responde SOLO con JSON válido (sin preámbulo ni markdown):
{"titulo": "...", "bloques": [ ... ], "trazabilidad": {"b0": ["id-de-hecho"]}}
"titulo": solo si la hoja NO traía título (propón uno breve, en mayúsculas); si ya traía, devuélvelo vacío.
Cada bloque tiene "tipo" y sus campos:
- texto:   {"tipo":"texto","titulo":"...","texto":"..."}
- vinetas: {"tipo":"vinetas","titulo":"...","items":["..."]}
- tabla:   {"tipo":"tabla","titulo":"...","columnas":["..."],"filas":[["...","..."]]}
- kpis:    {"tipo":"kpis","titulo":"...","items":[{"etiqueta":"...","valor":"..."}]}
- grafico: {"tipo":"grafico","titulo":"...","estilo":"barras|barras_h|dona","categorias":["..."],"valores":[1,2]}
- imagen:  NO la completes; devuélvela tal cual venía.
Reglas: si "bloques" trae estructura, RESPÉTALA (mismos tipos, mismo orden, mismas columnas y títulos) y
solo rellena el contenido; si viene vacío, propón el formato más adecuado a las instrucciones (máx. 4 bloques).
NO inventes cifras ni datos: si no hay información, deja el campo vacío ("" o lista vacía). En "valores"
usa números. En "trazabilidad" la clave es "b<índice del bloque>" y el valor los ids de los hechos que lo
respaldan (solo ids que existan en los hechos entregados)."""


class LLMProvider(ABC):
    """Contrato que cumple cualquier proveedor (nube pública, nube privada o modelo local)."""

    @abstractmethod
    def extraer_hechos(self, texto: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def sintetizar_briefing(self, hechos: list[dict[str, Any]], parametros: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def detectar_contradicciones(self, hechos: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def completar_hoja(self, hechos: list[dict[str, Any]], contexto: str, hoja: dict[str, Any]) -> dict[str, Any]: ...


def _strip_fences(s: str) -> str:
    """Quita ```json ... ``` si el modelo lo agrega pese a las instrucciones."""
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s[: s.rfind("```")]
    return s.strip()


def _try_repair_json(raw: str) -> dict[str, Any] | None:
    """Intenta reparar JSON truncado/mal formado (cierra strings y llaves abiertas).

    El briefing institucional es JSON grande y a veces el modelo lo corta al
    llegar al tope de tokens de salida ("Unterminated string ..."). Como
    BriefingOut tiene todos los campos con default, un JSON parcial reparado
    valida igual: se pierde la cola (p.ej. trazabilidad) pero el briefing se
    genera en vez de fallar por completo.
    """
    try:
        from json_repair import repair_json  # import perezoso

        fixed = repair_json(raw)
        if not fixed:
            return None
        data = json.loads(fixed)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _exigir(valor: str, variable: str) -> str:
    """Falla con un mensaje claro si falta una variable de configuración del proveedor."""
    if not valor:
        raise LLMError(f"{variable} no configurada")
    return valor


@dataclass
class _Respuesta:
    """Resultado normalizado de UNA llamada al modelo, sea cual sea el protocolo del proveedor."""

    texto: str
    truncado: bool = False          # el modelo se cortó por el tope de tokens de salida
    tokens_in: int | None = None
    tokens_out: int | None = None


class _ChatJSONProvider(LLMProvider):
    """Lógica común a todo proveedor: prompts, JSON, reintentos, truncado y registro de uso.

    Las subclases solo implementan `_llamar` (una llamada al modelo) y configuran `model`,
    `max_retries` y, si hace falta, los techos de tokens.
    """

    nombre: str = "?"
    model: str
    max_retries: int
    max_output_tokens: int = settings.llm_max_output_tokens
    # Techo al que se puede escalar max_tokens si la salida se trunca (depende del modelo).
    max_output_techo: int = settings.llm_max_output_tokens

    def _llamar(self, system: str, user: str, max_tokens: int) -> _Respuesta:
        raise NotImplementedError

    def _error_definitivo(self, e: Exception) -> bool:
        """True si reintentar no sirve (p.ej. clave inválida): se falla de inmediato."""
        return False

    def _log_uso(self, operacion: str, intento: int, latencia: float, resultado: str,
                 resp: _Respuesta | None, falla: Exception | None) -> None:
        """Una línea por llamada, SOLO metadatos: nunca el contenido de prompts ni respuestas
        (los documentos pueden ser clasificados). De una excepción se registra solo su tipo."""
        logger.info(
            "llm_call provider=%s model=%s op=%s intento=%d/%d latencia_s=%.2f "
            "tokens_in=%s tokens_out=%s resultado=%s%s",
            self.nombre, self.model, operacion, intento, self.max_retries, latencia,
            resp.tokens_in if resp else None, resp.tokens_out if resp else None, resultado,
            f" error={type(falla).__name__}" if falla else "",
        )

    def _chat_json(self, system: str, user: str, operacion: str = "-") -> dict[str, Any]:
        """Pide JSON al modelo y reintenta con backoff.

        Una respuesta cortada por el tope de tokens NUNCA se acepta "reparada": json_repair
        cierra las llaves y Pydantic rellena con vacíos todo lo que faltaba (secciones enteras
        sin datos, guardadas como un briefing válido). En ese caso se reintenta con más tokens
        de salida y, si ya no se puede, se falla con LLMError. json_repair solo se usa para JSON
        mal formado que NO se truncó.
        """
        last_err: Exception | None = None
        max_tokens = self.max_output_tokens
        for intento in range(1, self.max_retries + 1):
            t0 = time.perf_counter()
            resp: _Respuesta | None = None
            resultado, falla, latencia = "error", None, None
            try:
                resp = self._llamar(system, user, max_tokens)
                latencia = time.perf_counter() - t0
                raw = _strip_fences(resp.texto)
                try:
                    data = json.loads(raw)  # JSON completo y válido (aunque roce el tope)
                except json.JSONDecodeError as e:
                    if resp.truncado:
                        resultado = "truncado"
                        logger.warning(
                            "Salida LLM truncada (provider=%s, max_tokens=%s, tokens_out=%s)",
                            self.nombre, max_tokens, resp.tokens_out,
                        )
                        if max_tokens < self.max_output_techo:
                            max_tokens = min(max_tokens * 2, self.max_output_techo)
                            last_err = LLMError("salida truncada por el tope de tokens")
                            continue  # reintenta de inmediato con más tokens de salida
                        raise LLMError(
                            "La respuesta del LLM superó el tope de tokens de salida "
                            f"({max_tokens}) y quedó incompleta; no se acepta un resultado a medias. "
                            "Sube LLM_MAX_OUTPUT_TOKENS o reduce el alcance (menos fuentes)."
                        ) from e
                    # JSON mal formado pero completo: intentar reparar (comas, comillas).
                    reparado = _try_repair_json(raw)
                    if reparado is None:
                        resultado = "json_invalido"
                        raise
                    resultado = "ok_reparado"
                    return reparado
                resultado = "ok"
                return data
            except LLMError as e:
                falla = e
                raise  # error definitivo (truncación irreparable, rechazo): no reintentar
            except Exception as e:  # red, JSON inválido transitorio, etc.
                falla = last_err = e
                latencia = time.perf_counter() - t0 if latencia is None else latencia
                if self._error_definitivo(e):
                    raise LLMError(f"Error no recuperable de {self.nombre}: {e}") from e
                if intento < self.max_retries:
                    time.sleep(2 ** (intento - 1))  # 1s, 2s, 4s...
            finally:
                self._log_uso(operacion, intento,
                              time.perf_counter() - t0 if latencia is None else latencia,
                              resultado, resp, falla)
        raise LLMError(f"LLM falló tras {self.max_retries} intentos: {last_err}")

    def extraer_hechos(self, texto: str) -> list[dict[str, Any]]:
        data = self._chat_json(_EXTRACT_SYS, texto, "extraer_hechos")
        try:
            parsed = HechosResponse.model_validate(data)
        except ValidationError as e:
            raise LLMError(f"Extracción con formato inválido: {e}")
        return [h.model_dump() for h in parsed.hechos]

    def sintetizar_briefing(self, hechos: list[dict[str, Any]], parametros: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps({"hechos": hechos, "parametros": parametros}, ensure_ascii=False)
        data = self._chat_json(_SYNTH_SYS, payload, "sintetizar_briefing")
        try:
            return BriefingOut.model_validate(data).model_dump()
        except ValidationError as e:
            raise LLMError(f"Síntesis con formato inválido: {e}")

    def detectar_contradicciones(self, hechos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(hechos) < 2:
            return []
        payload = json.dumps({"hechos": hechos}, ensure_ascii=False)
        data = self._chat_json(_CONTRA_SYS, payload, "detectar_contradicciones")
        try:
            return [c.model_dump() for c in ContradiccionesResponse.model_validate(data).contradicciones]
        except ValidationError:
            return []  # la detección de contradicciones es best-effort

    def completar_hoja(self, hechos: list[dict[str, Any]], contexto: str, hoja: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(
            {
                "hoja": {
                    "id": hoja.get("id", ""),
                    "titulo": hoja.get("titulo", ""),
                    "seccion": hoja.get("seccion", ""),
                    "instrucciones": hoja.get("instrucciones_ia", ""),
                    "documentos_adjuntos": [d.get("nombre", "") for d in hoja.get("documentos", [])],
                    "bloques": hoja.get("bloques", []),
                },
                "hechos": hechos,
                "contexto_fuentes": contexto,
            },
            ensure_ascii=False,
        )
        data = self._chat_json(_HOJA_SYS, payload, "completar_hoja")
        try:
            return HojaCompletada.model_validate(data).model_dump()
        except ValidationError as e:
            raise LLMError(f"Hoja con formato inválido: {e}")


class _OpenAICompatProvider(_ChatJSONProvider):
    """Base para back-ends con API estilo OpenAI (chat.completions): Gemini, DeepSeek, Groq,
    GitHub Models, un gateway/nube privada (`openai_compat`) o un servidor local (Ollama, vLLM).

    Las subclases solo configuran `client`, `model` y `max_retries`.
    """

    client: Any
    # Parámetros extra por proveedor (p.ej. Gemini necesita reasoning_effort="none"
    # para no gastar tiempo/tokens en "thinking" interno antes del JSON final).
    extra_create_kwargs: dict[str, Any] = {}
    # False -> no se envía response_format={"type": "json_object"} (algunos endpoints lo rechazan):
    # el JSON lo garantiza el prompt y la reparación de JSON.
    json_mode: bool = True

    def _llamar(self, system: str, user: str, max_tokens: int) -> _Respuesta:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
            **self.extra_create_kwargs,
        )
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        usage = getattr(resp, "usage", None)
        return _Respuesta(
            texto=choice.message.content or "",
            truncado=choice.finish_reason == "length",
            tokens_in=getattr(usage, "prompt_tokens", None),
            tokens_out=getattr(usage, "completion_tokens", None),
        )


class GeminiProvider(_OpenAICompatProvider):
    """Gemini (Google) vía su endpoint OpenAI-compatible — proveedor activo por defecto."""

    nombre = "gemini"
    # gemini-2.5-flash/flash-lite "piensan" por defecto (tokens de razonamiento
    # internos antes del JSON final), lo que suma latencia real al presupuesto
    # de generación sin aportar al resultado (no citamos el thinking). "none"
    # lo desactiva para estos modelos (no aplica a 2.5 Pro / 3, que no permiten
    # apagarlo). Ver: https://ai.google.dev/gemini-api/docs/openai
    extra_create_kwargs: dict[str, Any] = {"reasoning_effort": "none"}

    def __init__(self) -> None:
        _exigir(settings.gemini_api_key, "GEMINI_API_KEY")
        from openai import OpenAI  # import perezoso

        self.client = OpenAI(
            base_url=settings.gemini_base_url,
            api_key=settings.gemini_api_key,
        )
        self.model = settings.gemini_model
        self.max_retries = settings.llm_max_retries
        # Si aun sin "thinking" la salida se trunca, se puede escalar hasta el techo del modelo.
        self.max_output_techo = max(self.max_output_tokens, 65536)


class DeepSeekProvider(_OpenAICompatProvider):
    """DeepSeek (endpoint OpenAI-compatible)."""

    nombre = "deepseek"

    def __init__(self) -> None:
        _exigir(settings.deepseek_api_key, "DEEPSEEK_API_KEY")
        from openai import OpenAI  # import perezoso

        self.client = OpenAI(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
        )
        self.model = settings.deepseek_model
        self.max_retries = settings.llm_max_retries


class GroqProvider(_OpenAICompatProvider):
    """Groq (Llama 3.3 70B)."""

    nombre = "groq"

    def __init__(self) -> None:
        _exigir(settings.groq_api_key, "GROQ_API_KEY")
        from groq import Groq  # import perezoso

        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.groq_model
        self.max_retries = settings.groq_max_retries
        self.max_output_techo = max(self.max_output_tokens, 32768)  # tope de Llama 3.3 70B en Groq


class GitHubProvider(_OpenAICompatProvider):
    """GitHub Models (endpoint OpenAI-compatible) — gpt-4o."""

    nombre = "github"

    def __init__(self) -> None:
        _exigir(settings.github_token, "GITHUB_TOKEN")
        from openai import OpenAI  # import perezoso

        self.client = OpenAI(
            base_url=settings.github_base_url,
            api_key=settings.github_token,
        )
        self.model = settings.github_model
        self.max_retries = settings.llm_max_retries


class OpenAICompatProvider(_OpenAICompatProvider):
    """Cualquier endpoint con API estilo OpenAI, configurado solo por entorno (LLM_BASE_URL,
    LLM_API_KEY, LLM_MODEL): OpenAI directo, Azure OpenAI, Vertex AI, Bedrock por su endpoint
    compatible o un gateway institucional. Pensado para la modalidad de nube privada/dedicada."""

    nombre = "openai_compat"

    def __init__(self) -> None:
        _exigir(settings.llm_base_url, "LLM_BASE_URL")
        _exigir(settings.llm_api_key, "LLM_API_KEY")
        _exigir(settings.llm_model, "LLM_MODEL")
        from openai import OpenAI  # import perezoso

        self.client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
        self.model = settings.llm_model
        self.max_retries = settings.llm_max_retries
        self.json_mode = settings.llm_json_mode


class LocalLLMProvider(_OpenAICompatProvider):
    """Modelo de pesos abiertos servido dentro de la red del Ejército con un servidor de API
    estilo OpenAI (Ollama o vLLM). No requiere salida a internet ni clave."""

    nombre = "local"

    def __init__(self) -> None:
        _exigir(settings.local_llm_base_url, "LOCAL_LLM_BASE_URL")
        _exigir(settings.local_llm_model, "LOCAL_LLM_MODEL")
        from openai import OpenAI  # import perezoso

        # El SDK exige una clave no vacía aunque el servidor local no la use.
        self.client = OpenAI(base_url=settings.local_llm_base_url,
                             api_key=settings.local_llm_api_key or "local")
        self.model = settings.local_llm_model
        self.max_retries = settings.llm_max_retries
        self.json_mode = settings.llm_json_mode


class AnthropicProvider(_ChatJSONProvider):
    """Claude (Anthropic) con el SDK oficial. No se usa el endpoint compatible con OpenAI: no
    ofrece modo JSON ni es la vía soportada. El JSON lo garantiza el prompt + la reparación."""

    nombre = "anthropic"
    # Errores HTTP donde reintentar no sirve (clave inválida, modelo inexistente, petición mala).
    _ERRORES_DEFINITIVOS = ("AuthenticationError", "PermissionDeniedError", "NotFoundError", "BadRequestError")

    def __init__(self) -> None:
        _exigir(settings.anthropic_api_key, "ANTHROPIC_API_KEY")
        import anthropic  # import perezoso

        self._sdk = anthropic
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model
        self.max_retries = settings.llm_max_retries
        self.max_output_techo = max(self.max_output_tokens, 64000)

    def _llamar(self, system: str, user: str, max_tokens: int) -> _Respuesta:
        # Streaming: con max_tokens alto el SDK lo exige para evitar timeouts HTTP. No se envía
        # `temperature` (los modelos Claude recientes lo rechazan) ni `thinking`.
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise LLMError("Claude rechazó la solicitud (stop_reason=refusal); no se reintenta.")
        texto = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        usage = getattr(msg, "usage", None)
        return _Respuesta(
            texto=texto,
            truncado=msg.stop_reason == "max_tokens",
            tokens_in=getattr(usage, "input_tokens", None),
            tokens_out=getattr(usage, "output_tokens", None),
        )

    def _error_definitivo(self, e: Exception) -> bool:
        clases = tuple(getattr(self._sdk, n) for n in self._ERRORES_DEFINITIVOS if hasattr(self._sdk, n))
        return isinstance(e, clases)


# Registro nombre -> clase. Agregar un proveedor es una línea aquí; el pipeline no cambia.
_PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "deepseek": DeepSeekProvider,
    "groq": GroqProvider,
    "github": GitHubProvider,
    "openai_compat": OpenAICompatProvider,
    "local": LocalLLMProvider,
}


def get_llm_provider() -> LLMProvider:
    nombre = (settings.llm_provider or "").strip().lower()
    clase = _PROVIDERS.get(nombre)
    if clase is None:
        raise LLMError(
            f"LLM_PROVIDER='{settings.llm_provider}' no es válido. "
            f"Valores válidos: {', '.join(_PROVIDERS)}."
        )
    return clase()
