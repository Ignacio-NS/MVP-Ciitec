"""
Catálogo de proveedores de IA: un "preset" por valor de LLM_PROVIDER.

Un preset solo entrega VALORES POR DEFECTO (URL, modelo, parámetros que ese
servicio exige o rechaza). Cualquier valor se puede sobreescribir con las
variables genéricas LLM_* del .env o desde la interfaz de administración.

`adaptador` indica qué clase habla con el servicio:
  - "openai": cualquier API compatible con OpenAI (la gran mayoría, incluidos
    Ollama y vLLM on-premise).
  - "anthropic": API nativa de Claude (su capa compatible con OpenAI ignora el
    modo JSON y rechaza temperature < 1 en los modelos recientes).

`resguardo` ordena las opciones según dónde viajan los documentos, que es el
criterio que más pesa con información clasificada:
  - MAXIMO: el modelo corre en servidores del Ejército, sin salida a internet.
  - ALTO:   nube privada/dedicada con contrato institucional.
  - BASICO: API pública del proveedor (solo datos sintéticos o no clasificados).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import settings


@dataclass(frozen=True)
class Preset:
    nombre: str
    etiqueta: str
    adaptador: str                      # "openai" | "anthropic"
    resguardo: str                      # MAXIMO | ALTO | BASICO
    base_url: str = ""
    modelo: str = ""
    api_key: str = ""
    requiere_api_key: bool = True
    json_mode: bool = True
    temperature: float | None = 0.1     # None = no enviar el parámetro
    token_param: str = "max_tokens"
    extra_params: dict[str, Any] = field(default_factory=dict)
    max_output_techo: int = 0           # 0 = igual a LLM_MAX_OUTPUT_TOKENS
    descripcion: str = ""


def _gemini_extra(modelo: str) -> dict[str, Any]:
    # Gemini 2.5 Flash "piensa" por defecto y eso sumaba latencia al presupuesto
    # (BUG-001 del Robot QA). "none" solo es válido en la familia 2.5; en 3.x no
    # se puede apagar del todo, así que no se envía y se deja al usuario elegir
    # (p.ej. LLM_EXTRA_PARAMS={"reasoning_effort":"low"}).
    return {"reasoning_effort": "none"} if modelo.startswith("gemini-2.5") else {}


def presets() -> dict[str, Preset]:
    """Construye los presets leyendo las variables por proveedor del .env (compatibilidad)."""
    s = settings
    return {
        "gemini": Preset(
            nombre="gemini", etiqueta="Google Gemini", adaptador="openai", resguardo="BASICO",
            base_url=s.gemini_base_url, modelo=s.gemini_model, api_key=s.gemini_api_key,
            max_output_techo=65536,
            descripcion="API pública de Google. Proveedor validado de punta a punta con el Robot QA.",
        ),
        "openai": Preset(
            nombre="openai", etiqueta="OpenAI (GPT)", adaptador="openai", resguardo="BASICO",
            base_url="https://api.openai.com/v1", modelo=s.openai_model or "gpt-6-luna",
            api_key=s.openai_api_key,
            # Los modelos de razonamiento de OpenAI exigen max_completion_tokens y
            # rechazan temperature cuando razonan: no se envía.
            temperature=None, token_param="max_completion_tokens",
            descripcion="API pública de OpenAI.",
        ),
        "anthropic": Preset(
            nombre="anthropic", etiqueta="Anthropic (Claude)", adaptador="anthropic", resguardo="BASICO",
            base_url="https://api.anthropic.com", modelo=s.anthropic_model or "claude-sonnet-5-5",
            api_key=s.anthropic_api_key,
            # Claude 4.7+ responde 400 a temperature < 1: no se envía.
            temperature=None, json_mode=False,
            descripcion="API nativa de Claude (no usa la capa OpenAI-compatible).",
        ),
        "deepseek": Preset(
            nombre="deepseek", etiqueta="DeepSeek", adaptador="openai", resguardo="BASICO",
            base_url=s.deepseek_base_url, modelo=s.deepseek_model, api_key=s.deepseek_api_key,
            descripcion="API pública de DeepSeek.",
        ),
        "mistral": Preset(
            nombre="mistral", etiqueta="Mistral AI", adaptador="openai", resguardo="BASICO",
            base_url="https://api.mistral.ai/v1", modelo=s.mistral_model or "mistral-medium-latest",
            api_key=s.mistral_api_key,
            descripcion="API pública de Mistral (Europa).",
        ),
        "groq": Preset(
            nombre="groq", etiqueta="Groq", adaptador="openai", resguardo="BASICO",
            base_url="https://api.groq.com/openai/v1", modelo=s.groq_model, api_key=s.groq_api_key,
            max_output_techo=32768,
            descripcion="Inferencia rápida de modelos abiertos (Llama, gpt-oss, Qwen).",
        ),
        "github": Preset(
            nombre="github", etiqueta="GitHub Models", adaptador="openai", resguardo="BASICO",
            base_url=s.github_base_url, modelo=s.github_model, api_key=s.github_token,
            descripcion="Catálogo de GitHub Models (desarrollo).",
        ),
        "openai_compat": Preset(
            nombre="openai_compat", etiqueta="Endpoint OpenAI-compatible (genérico)",
            adaptador="openai", resguardo="ALTO",
            base_url=s.llm_base_url, modelo=s.llm_model, api_key=s.llm_api_key,
            requiere_api_key=False,  # un gateway institucional puede no exigir clave
            descripcion=(
                "Cualquier servicio con API compatible con OpenAI: Azure OpenAI/Foundry, "
                "Amazon Bedrock, Google Vertex AI, OpenRouter o un gateway institucional "
                "(LiteLLM). Requiere LLM_BASE_URL y LLM_MODEL."
            ),
        ),
        "litellm": Preset(
            nombre="litellm", etiqueta="Gateway LiteLLM (más de 100 servicios)",
            adaptador="openai", resguardo="ALTO",
            base_url=s.litellm_base_url, modelo=s.litellm_model,
            api_key=s.litellm_api_key or s.litellm_master_key,
            requiere_api_key=False,
            descripcion=(
                "Gateway incluido en el docker-compose (perfil 'gateway'). Conecta servicios sin API "
                "compatible con OpenAI: Amazon Bedrock nativo (incluido Claude), Vertex AI con "
                "credenciales de servicio, Cohere, IBM watsonx, Hugging Face, etc. Los modelos se "
                "declaran en infra/litellm/config.yaml. El resguardo depende del servicio de destino."
            ),
        ),
        "local": Preset(
            nombre="local", etiqueta="Modelo local (Ollama / vLLM)", adaptador="openai", resguardo="MAXIMO",
            base_url=s.local_llm_base_url, modelo=s.local_llm_model, api_key=s.local_llm_api_key,
            requiere_api_key=False,
            descripcion=(
                "Modelo de pesos abiertos servido dentro de la red institucional. "
                "Única opción apta para información Reservada o Secreta."
            ),
        ),
    }


def extra_por_defecto(preset: Preset, modelo: str) -> dict[str, Any]:
    """Parámetros extra del preset, calculados con el modelo FINAL (puede venir de LLM_MODEL)."""
    if preset.nombre == "gemini":
        return _gemini_extra(modelo)
    return dict(preset.extra_params)


def nombres() -> list[str]:
    return list(presets().keys())
