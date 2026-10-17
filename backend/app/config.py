"""
Configuración central (pydantic-settings). Lee variables de entorno / .env.
Toda la app importa `settings` desde aquí; no se leen variables sueltas.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Base de datos
    database_url: str = "postgresql+psycopg://briefings:cambiar_en_local@db:5432/briefings"

    # Cola asíncrona
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # Object storage (MinIO)
    minio_endpoint: str = "minio:9000"
    minio_user: str = "minioadmin"
    minio_password: str = "cambiar_en_local"
    minio_bucket: str = "fuentes"
    minio_secure: bool = False
    minio_encrypt: bool = True

    # LDAP / AD
    ldap_host: str = "openldap"
    ldap_port: int = 1389
    ldap_base_dn: str = "dc=ejercito,dc=cl"
    ldap_user_dn_template: str = "cn={username},ou=users,dc=ejercito,dc=cl"

    # Seguridad
    jwt_secret: str = "cambiar_en_local"
    jwt_algorithm: str = "HS256"
    session_timeout_min: int = 15
    encryption_key: str = "clave_aes_256_base64"
    audit_log_reads: bool = True
    audit_retention_years: int = 5

    # ------------------------------------------------------------------
    # LLM — motor de IA intercambiable (ver llm/catalogo.py y README).
    # Valores de LLM_PROVIDER: gemini | openai | anthropic | deepseek | mistral |
    # groq | github | openai_compat | local. Un valor desconocido DETIENE la
    # generación (no se cae en silencio a otro proveedor).
    # Se puede sobreescribir en caliente desde la interfaz (Administrador del
    # Sistema → "Motor de IA"); este .env queda como respaldo.
    # ------------------------------------------------------------------
    llm_provider: str = "gemini"
    # Variables GENÉRICAS: si se definen, mandan sobre las del preset del proveedor.
    llm_model: str = ""                 # p.ej. gpt-6-luna, claude-sonnet-5-5, qwen3.8:27b
    llm_base_url: str = ""              # endpoint OpenAI-compatible (obligatorio en openai_compat)
    llm_api_key: str = ""
    llm_json_mode: bool = True          # response_format=json_object (false si el servicio no lo acepta)
    llm_temperature: str = ""           # vacío = default del preset; "none" = no enviar el parámetro
    llm_token_param: str = ""           # max_tokens | max_completion_tokens (vacío = preset)
    llm_extra_params: str = ""          # JSON que se agrega al body (p.ej. {"reasoning_effort":"none"})
    llm_timeout_s: float = 300.0        # timeout por llamada (los modelos locales en CPU son lentos)
    llm_context_tokens: int = 0         # ventana de contexto del modelo; 0 = usar topes SYNTH_* fijos
    llm_max_output_techo: int = 0       # techo al que se escala la salida si se trunca; 0 = preset
    # Cómo se redacta el SITREP:
    #   auto      = de una vez; si el modelo no puede (o su ventana es < 32k), por secciones
    #   completa  = siempre de una vez (un JSON grande; modelos grandes)
    #   secciones = siempre por partes (cualquier modelo, incluidos los chicos/locales)
    llm_sintesis_modo: str = "auto"
    # Configuración desde la interfaz
    llm_config_ui: bool = True          # false = la interfaz solo muestra, no permite cambiar
    llm_proveedores_permitidos: str = ""  # lista separada por comas; vacío = todos
    llm_config_cache_s: float = 15.0    # cada cuánto el worker relee la configuración de la BD
    # Modelo local (Ollama / vLLM) — LLM_PROVIDER=local
    local_llm_base_url: str = "http://host.docker.internal:11434/v1"
    local_llm_model: str = "gpt-oss:20b"
    local_llm_api_key: str = ""
    # Anthropic (Claude) — adaptador nativo, LLM_PROVIDER=anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    # OpenAI — LLM_PROVIDER=openai
    openai_api_key: str = ""
    openai_model: str = ""
    # Mistral — LLM_PROVIDER=mistral
    mistral_api_key: str = ""
    mistral_model: str = ""
    # Gateway LiteLLM incluido (docker compose --profile gateway) — LLM_PROVIDER=litellm.
    # Traduce a más de 100 servicios (Bedrock nativo, Vertex, Cohere, watsonx, etc.).
    litellm_base_url: str = "http://litellm:4000/v1"
    litellm_api_key: str = ""           # vacío = se usa LITELLM_MASTER_KEY
    litellm_master_key: str = ""        # clave maestra del gateway (también la lee el contenedor)
    litellm_model: str = ""
    llm_max_retries: int = 4
    # Tope de tokens de SALIDA por request. deepseek-chat (= deepseek-v4-flash,
    # no-thinking) admite hasta ~64K+ de salida; el briefing institucional es JSON
    # grande y con 8000 se truncaba ("Unterminated string"). 16384 da holgura;
    # solo se factura lo realmente generado. Si aun así se corta, json_repair
    # NO acepta JSON truncado (ver provider.py: reintenta con más tokens o falla).
    llm_max_output_tokens: int = 32768
    # Topes de ENTRADA para la síntesis (evitan exceder el contexto del proveedor).
    synth_max_hechos: int = 150              # nº máx. de hechos enviados a síntesis
    synth_max_contexto_chars: int = 40000    # tope total del texto crudo (contexto_fuentes); DeepSeek 64k lo permite
    synth_max_chars_por_fuente: int = 4000   # tope por archivo, para que TODAS las fuentes aporten cifras
    # DeepSeek — endpoint OpenAI-compatible (proveedor activo, pagado)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # Gemini (Google) — endpoint OpenAI-compatible (legado)
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-2.5-flash"
    # Groq (legado)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_max_retries: int = 3
    # GitHub Models (OpenAI-compatible) — gpt-4o (legado)
    github_token: str = ""
    github_base_url: str = "https://models.github.ai/inference"
    github_model: str = "openai/gpt-4o"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # Reglas de detección (RF-005)
    dedup_threshold: float = 0.85
    desactualizado_dias: int = 7

    # Exportación (RF-008): "flow" = reconstrucción HTML fiel (tablas y gráficos
    # generados desde los datos; sin coordenadas fijas); "overlay" = legado
    # pixel-perfect (PNG de fondo + datos sobrepuestos), propenso a desalineación
    # y a chocar con el contenido de muestra horneado en el PNG.
    export_style: str = "flow"
    export_debug_grid: bool = False
    # PDF institucional (RF-008): se rellena la plantilla .pptx de 6 páginas y se
    # convierte a PDF con LibreOffice headless. `soffice_bin` permite apuntar al
    # binario en dev (Windows: "C:/Program Files/LibreOffice/program/soffice.exe").
    soffice_bin: str = "soffice"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
