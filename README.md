# Síntesis Automática de Reportes y Briefings Operacionales — CIITEC / Ejército de Chile

Aplicación web interna on-premise que **lee** documentos heterogéneos (PDF, Word,
Excel, correos, bitácoras), extrae hechos con LLM, genera un **briefing
institucional** versionado y trazable, detecta inconsistencias y lo exporta a
PDF/Word/texto/PPTX. Monorepo, arquitectura en capas, LLM tras una interfaz pluggable
(por defecto DeepSeek `deepseek-chat`; intercambiable por Gemini, GitHub Models, Groq o modelo local).

## Levantar en local

Requisitos: Docker Desktop instalado y corriendo.

```bash
cp .env.example .env          # copiar plantilla de variables
```

Editar `.env` y completar como mínimo:

- `GEMINI_API_KEY`: clave de https://aistudio.google.com/apikey (proveedor por defecto; sin
  esto la generación de briefings con IA falla; el resto de la app funciona igual). Para usar
  otro modelo (Claude, uno local, una nube privada) ver «Proveedor LLM» más abajo.
- `JWT_SECRET`: string largo y aleatorio.
- `ENCRYPTION_KEY`: 32 bytes en base64, p.ej. `openssl rand -base64 32`.
- Opcional pero recomendado: cambiar los `..._PASSWORD=cambiar_en_local`.

Luego:

```bash
make certs                    # certificados TLS self-signed
#   Windows sin make: powershell -ExecutionPolicy Bypass -File scripts/gen_certs.ps1
docker compose up --build     # levanta db, redis, minio, openldap, api, worker, beat, frontend, nginx
```

- Frontend: `https://localhost`  · API: `https://localhost/api`  · MinIO: `http://localhost:9001`
- Generar corpus de prueba y medir RNF-004:
  ```bash
  python scripts/gen_corpus.py      # 50 docs + 5 curados en ./corpus  (pip install fpdf2 python-docx openpyxl)
  python scripts/loadtest.py        # sube 50 docs y cronometra (< 3 min)
  ```

## Usuarios demo (LDAP)

Contraseña por defecto: `demo1234` (variable `LDAP_DEMO_PASSWORD`).

| Usuario | Rol | Habilitación |
|---|---|---|
| operaciones | Oficial de Operaciones | RESERVADO |
| analista | Analista de Operaciones | RESERVADO |
| comandante | Comandante | SECRETO |
| auditor | Auditor | SECRETO |
| admin | Administrador del Sistema | SECRETO |

Flujo: **Cargar → Generar → Exportar**. La vista de Auditoría es solo para roles
auditor/seguridad/admin.

## Mapeo requerimiento → componente

| Req | Dónde |
|---|---|
| RF-001 ingesta | `backend/app/pipeline/ingesta.py` + `storage.py` (MinIO) |
| RF-002 normalización | `pipeline/normalizacion.py` → `hechos.normalizado` |
| RF-003 extracción | `pipeline/extraccion.py` + `llm/provider.py` (`LLMProvider`, JSON + Pydantic) |
| RF-004 generación | `pipeline/sintesis.py` (esquema institucional 6 págs) |
| RF-005 inconsistencias | `pipeline/deteccion.py` (pgvector + reglas + LLM) |
| RF-006 trazabilidad | `version_bullet_hechos` + `/briefings/{id}/trazabilidad` |
| RF-007 versionado | `briefing_versiones` (append-only) + aprobación + diffs |
| RF-008 exportación | `pipeline/exportacion.py` + `templates/briefing.html.j2` (WeasyPrint/docx/txt) |
| RF-009 point-in-time | `GET /briefings/{id}/versiones?at=<ISO>` |
| RF-010 offline | `frontend/src/offline.ts` (IndexedDB) + `vite.config.ts` (PWA) |
| RNF-001 auth | `auth/` (LDAP→JWT→RBAC por rol+nivel+unidad, sesión sliding 15 min; WS autenticado por token) |
| RNF-002 cifrado/clasif. | Nginx TLS1.3 + `crypto.py` (AES-256-GCM) + MinIO cifrado + gate por nivel |
| RNF-003 auditoría | `audit_log` (hash chain inmutable) + `/audit/verificar` + `retention.py` (beat) |
| RNF-004 rendimiento | Celery group/chord (`worker.py`) + índices + `loadtest.py` |
| RNF-005 disponibilidad | healthchecks + `restart: unless-stopped` |
| RNF-006 usabilidad | UI en español, flujo simple |

## Robot QA (Taller en Empresa 2)

Plataforma de pruebas automatizadas del sistema, en [`robot-qa/`](robot-qa/)
(52 casos en 6 familias: funcional, RAG, robustez, seguridad, rendimiento,
confiabilidad). Uso rápido:

```bash
pip install -e ./robot-qa
python -m robot_qa run --campaign smoke
```

Ver [`robot-qa/README.md`](robot-qa/README.md) para el detalle completo.

## Notas

- **Proveedor LLM (intercambiable):** el sistema no está atado a una lista cerrada de
  modelos. `LLM_PROVIDER` (en `.env`) elige el back-end sin tocar el pipeline; cualquier
  modelo se integra implementando la interfaz `LLMProvider` (`backend/app/llm/provider.py`) y
  registrándolo en `_PROVIDERS`. Por defecto: **Gemini 2.5 Flash**. Un valor desconocido
  falla con la lista de valores válidos (no cae en otro proveedor). Cada llamada deja una
  línea `llm_call ...` en el log (proveedor, modelo, operación, latencia, tokens, intento);
  nunca se registra el contenido de prompts ni de respuestas.

  | `LLM_PROVIDER` | Variables |
  |---|---|
  | `gemini` (por defecto) | `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-2.5-flash`, `GEMINI_BASE_URL` |
  | `anthropic` (Claude) | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL=claude-opus-5-5` (SDK oficial) |
  | `deepseek` | `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL=deepseek-chat`, `DEEPSEEK_BASE_URL` |
  | `groq` | `GROQ_API_KEY`, `GROQ_MODEL=llama-3.3-70b-versatile` |
  | `github` | `GITHUB_TOKEN` (PAT con permiso Models), `GITHUB_MODEL=openai/gpt-4o` |
  | `openai_compat` | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_JSON_MODE=true\|false` |
  | `local` | `LOCAL_LLM_BASE_URL` (por defecto `http://localhost:11434/v1`), `LOCAL_LLM_MODEL`, `LOCAL_LLM_API_KEY` (opcional), `LLM_JSON_MODE` |

  Comunes a todos: `LLM_MAX_RETRIES`, `LLM_MAX_OUTPUT_TOKENS`.

  **Modalidades de resguardo de la información** (el Ejército elige según la clasificación):

  | Modalidad | Modelos / servicios | `LLM_PROVIDER` | ¿La información sale de la red del Ejército? |
  |---|---|---|---|
  | Modelo local en la red | Pesos abiertos (Llama, Mistral, Qwen, Gemma, gpt-oss) servidos con Ollama o vLLM | `local` | No |
  | Nube privada o dedicada | Azure OpenAI, Amazon Bedrock, Google Vertex AI (por su endpoint compatible con OpenAI) o un gateway institucional | `openai_compat` | Solo hacia la nube dedicada |
  | API pública del proveedor | GPT (`openai_compat` con `https://api.openai.com/v1`), Claude (`anthropic`), Gemini (`gemini`) | `gemini`, `anthropic`, `openai_compat` | Sí |

  **Apuntar a un servidor local existente** (Ollama o vLLM; `docker-compose.yml` no lo levanta):

  ```
  LLM_PROVIDER=local
  LOCAL_LLM_MODEL=<nombre del modelo, p.ej. el que muestra `ollama list`>
  LOCAL_LLM_BASE_URL=http://host.docker.internal:11434/v1   # Ollama en la máquina anfitriona (Docker Desktop)
  #   vLLM: http://<host>:8000/v1  ·  Linux: usar la IP del host en lugar de host.docker.internal
  ```

  Si el endpoint rechaza `response_format` (modo JSON), poner `LLM_JSON_MODE=false`: el JSON lo
  garantizan el prompt y la reparación de JSON. Ajustar `LLM_MAX_OUTPUT_TOKENS` a la salida
  máxima del modelo (con endpoints propios es también el techo; no se escala).
- **Plantilla pixel-perfect (RF-008):** dos modos (`EXPORT_STYLE`):
  - `overlay` (por defecto): usa las **6 PNG** de `backend/app/templates/` como
    fondo exacto de cada página A4 y **sobrepone los datos** de la IA en las
    celdas vacías, según el mapa `backend/app/templates/overlay.json`.
  - `flow`: reconstrucción HTML/CSS data-driven (sin PNG).
  Calibrar las coordenadas del overlay: `EXPORT_DEBUG_GRID=true` dibuja una
  rejilla del 10% y se ajustan los `top/left` (%) en `overlay.json`.
  Las páginas 1 y 6 traían **cifras de ejemplo "quemadas"**; se generan **en blanco**
  con `python scripts/blank_template.py` (rellena cada celda con su color de fondo;
  originales respaldados en `templates/_originales/`). Tras blanquear, esas casillas
  se rellenan por overlay desde el briefing (`personal.slc`, `operaciones.guardian_soberano`,
  `logistica.resumen`, etc.). Si retocas la plantilla, vuelve a correr el script.
- **SQLAlchemy síncrono** a propósito (worker Celery prefork comparte el ORM).
