"""
Abstracción del proveedor de LLM.

Toda la lógica del sistema habla con esta interfaz, NUNCA con DeepSeek/Gemini/Groq/OpenAI
directamente. En el MVP se usa DeepSeek (endpoint OpenAI-compatible, pagado); en producción
se reemplaza por un modelo local (clasificación de datos) implementando LocalLLMProvider
y seteando LLM_PROVIDER=local, sin tocar el resto del código.

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
    """Contrato que cumple cualquier proveedor (Groq hoy, modelo local mañana)."""

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


class _OpenAICompatProvider(LLMProvider):
    """Base para back-ends con API estilo OpenAI (Groq, GitHub Models).

    Las subclases solo configuran `client`, `model` y `max_retries`; toda la
    lógica de prompts/JSON/reintentos vive aquí.
    """

    client: Any
    model: str
    max_retries: int
    max_output_tokens: int = settings.llm_max_output_tokens
    # Techo al que se puede escalar max_tokens si la salida se trunca (depende del modelo).
    max_output_techo: int = settings.llm_max_output_tokens
    # Parámetros extra por proveedor (p.ej. Gemini necesita reasoning_effort="none"
    # para no gastar tiempo/tokens en "thinking" interno antes del JSON final).
    extra_create_kwargs: dict[str, Any] = {}

    def _chat_json(self, system: str, user: str) -> dict[str, Any]:
        """Pide JSON al modelo y reintenta con backoff.

        Una respuesta cortada por el tope de tokens (finish_reason="length") NUNCA se acepta
        "reparada": json_repair cierra las llaves y Pydantic rellena con vacíos todo lo que
        faltaba (secciones enteras sin datos, guardadas como un briefing válido). En ese caso
        se reintenta con más tokens de salida y, si ya no se puede, se falla con LLMError.
        json_repair solo se usa para JSON mal formado que NO se truncó.
        """
        last_err: Exception | None = None
        max_tokens = self.max_output_tokens
        for intento in range(self.max_retries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=max_tokens,
                    **self.extra_create_kwargs,
                )
                choice = resp.choices[0]
                truncado = choice.finish_reason == "length"
                raw = _strip_fences(choice.message.content or "")
                try:
                    return json.loads(raw)  # JSON completo y válido (aunque roce el tope)
                except json.JSONDecodeError as e:
                    if truncado:
                        logger.warning(
                            "Salida LLM truncada (finish_reason=length, max_tokens=%s, usage=%s)",
                            max_tokens, getattr(resp, "usage", None),
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
                    if reparado is not None:
                        return reparado
                    raise
            except LLMError:
                raise  # error definitivo (truncación irreparable): no reintentar
            except Exception as e:  # red, JSON inválido transitorio, etc.
                last_err = e
                if intento < self.max_retries - 1:
                    time.sleep(2 ** intento)  # 1s, 2s, 4s...
        raise LLMError(f"LLM falló tras {self.max_retries} intentos: {last_err}")

    def extraer_hechos(self, texto: str) -> list[dict[str, Any]]:
        data = self._chat_json(_EXTRACT_SYS, texto)
        try:
            parsed = HechosResponse.model_validate(data)
        except ValidationError as e:
            raise LLMError(f"Extracción con formato inválido: {e}")
        return [h.model_dump() for h in parsed.hechos]

    def sintetizar_briefing(self, hechos: list[dict[str, Any]], parametros: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps({"hechos": hechos, "parametros": parametros}, ensure_ascii=False)
        data = self._chat_json(_SYNTH_SYS, payload)
        try:
            return BriefingOut.model_validate(data).model_dump()
        except ValidationError as e:
            raise LLMError(f"Síntesis con formato inválido: {e}")

    def detectar_contradicciones(self, hechos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(hechos) < 2:
            return []
        payload = json.dumps({"hechos": hechos}, ensure_ascii=False)
        data = self._chat_json(_CONTRA_SYS, payload)
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
        data = self._chat_json(_HOJA_SYS, payload)
        try:
            return HojaCompletada.model_validate(data).model_dump()
        except ValidationError as e:
            raise LLMError(f"Hoja con formato inválido: {e}")


class DeepSeekProvider(_OpenAICompatProvider):
    """DeepSeek (endpoint OpenAI-compatible) — proveedor activo (pagado)."""

    def __init__(self) -> None:
        from openai import OpenAI  # import perezoso

        if not settings.deepseek_api_key:
            raise LLMError("DEEPSEEK_API_KEY no configurada")
        self.client = OpenAI(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
        )
        self.model = settings.deepseek_model
        self.max_retries = settings.llm_max_retries


class GroqProvider(_OpenAICompatProvider):
    def __init__(self) -> None:
        from groq import Groq  # import perezoso

        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY no configurada")
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.groq_model
        self.max_retries = settings.groq_max_retries
        self.max_output_techo = max(self.max_output_tokens, 32768)  # tope de Llama 3.3 70B en Groq


class GeminiProvider(_OpenAICompatProvider):
    """Gemini (Google) vía su endpoint OpenAI-compatible."""

    # gemini-2.5-flash/flash-lite "piensan" por defecto (tokens de razonamiento
    # internos antes del JSON final), lo que suma latencia real al presupuesto
    # de generación sin aportar al resultado (no citamos el thinking). "none"
    # lo desactiva para estos modelos (no aplica a 2.5 Pro / 3, que no permiten
    # apagarlo). Ver: https://ai.google.dev/gemini-api/docs/openai
    extra_create_kwargs: dict[str, Any] = {"reasoning_effort": "none"}

    def __init__(self) -> None:
        from openai import OpenAI  # import perezoso

        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY no configurada")
        self.client = OpenAI(
            base_url=settings.gemini_base_url,
            api_key=settings.gemini_api_key,
        )
        self.model = settings.gemini_model
        self.max_retries = settings.llm_max_retries
        # Si aun sin "thinking" la salida se trunca, se puede escalar hasta el techo del modelo.
        self.max_output_techo = max(self.max_output_tokens, 65536)


class GitHubProvider(_OpenAICompatProvider):
    """GitHub Models (endpoint OpenAI-compatible) — gpt-4o (legado)."""

    def __init__(self) -> None:
        from openai import OpenAI  # import perezoso

        if not settings.github_token:
            raise LLMError("GITHUB_TOKEN no configurada")
        self.client = OpenAI(
            base_url=settings.github_base_url,
            api_key=settings.github_token,
        )
        self.model = settings.github_model
        self.max_retries = settings.llm_max_retries


class LocalLLMProvider(LLMProvider):
    """Stub para producción: aquí entra el modelo local (clasificación de datos)."""

    def extraer_hechos(self, texto: str) -> list[dict[str, Any]]:
        raise NotImplementedError("Implementar con el modelo local on-premise.")

    def sintetizar_briefing(self, hechos: list[dict[str, Any]], parametros: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Implementar con el modelo local on-premise.")

    def detectar_contradicciones(self, hechos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise NotImplementedError("Implementar con el modelo local on-premise.")

    def completar_hoja(self, hechos: list[dict[str, Any]], contexto: str, hoja: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Implementar con el modelo local on-premise.")


def get_llm_provider() -> LLMProvider:
    proveedor = settings.llm_provider.lower()
    if proveedor == "local":
        return LocalLLMProvider()
    if proveedor == "groq":
        return GroqProvider()
    if proveedor == "github":
        return GitHubProvider()
    if proveedor == "gemini":
        return GeminiProvider()
    return DeepSeekProvider()  # "deepseek" (por defecto)
