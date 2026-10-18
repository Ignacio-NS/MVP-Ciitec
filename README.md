# Síntesis Automática de Reportes y Briefings Operacionales — CIITEC / Ejército de Chile

Aplicación web interna on-premise que **lee** documentos heterogéneos (PDF, Word,
Excel, correos, bitácoras), extrae hechos con LLM, genera un **briefing
institucional** versionado y trazable, detecta inconsistencias y lo exporta a
PDF/Word/texto/PPTX. Monorepo, arquitectura en capas, **motor de IA intercambiable**:
funciona con cualquier modelo (Gemini por defecto; también OpenAI, Claude, DeepSeek,
Mistral, Groq, cualquier endpoint compatible con OpenAI y modelos locales con Ollama o vLLM).
Se cambia en el `.env` o desde la interfaz (Administrador del Sistema → *Motor de IA*).

## Levantar en local

Requisitos: Docker Desktop instalado y corriendo.

```bash
cp .env.example .env          # copiar plantilla de variables
```

Editar `.env` y completar como mínimo:

- La clave del proveedor de IA elegido en `LLM_PROVIDER` (por defecto `GEMINI_API_KEY`,
  de https://aistudio.google.com/apikey). Sin clave la generación con IA falla con un
  error claro; el resto de la app funciona igual. Con `LLM_PROVIDER=local` no se necesita.
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
| RF-003 extracción | `pipeline/extraccion.py` + `llm/provider.py` (Groq, JSON + Pydantic) |
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

- **Motor de IA (cualquier modelo):** ver la sección siguiente.
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

## Motor de IA

El pipeline habla con la IA solo a través de `LLMProvider` (`backend/app/llm/provider.py`).
Dos adaptadores cubren cualquier modelo: uno para APIs compatibles con OpenAI y uno
nativo para Claude. Qué modelo responde lo decide la **configuración efectiva**:

1. **Interfaz** (Administrador del Sistema → *Motor de IA*): elegir proveedor y modelo,
   probar la conexión y activar. Se aplica a la próxima generación sin reiniciar; la
   clave se guarda cifrada y cada cambio queda en la auditoría (`CONFIG_IA`).
   Auditor y Oficial de Seguridad pueden verla, no cambiarla.
2. **`.env` del servidor** (`LLM_PROVIDER` + variables `LLM_*`): respaldo cuando la
   interfaz no tiene nada activo. `LLM_CONFIG_UI=false` bloquea la interfaz y
   `LLM_PROVEEDORES_PERMITIDOS` limita qué proveedores se pueden elegir.

| `LLM_PROVIDER` | Dónde corren los documentos | Qué configurar |
|---|---|---|
| `local` | Red institucional (Ollama / vLLM) | `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`, `LLM_CONTEXT_TOKENS` |
| `openai_compat` | Nube privada (Azure, Bedrock, Vertex) o gateway | `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` |
| `litellm` | Gateway incluido → más de 100 servicios (Bedrock nativo, Vertex, Cohere…) | `LITELLM_MASTER_KEY`, `LITELLM_MODEL`, `infra/litellm/config.yaml` |
| `gemini` (por defecto) | API pública de Google | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| `openai` | API pública de OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| `anthropic` | API pública de Anthropic | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |
| `deepseek`, `mistral`, `groq`, `github` | API pública | `<PROVEEDOR>_API_KEY`, `<PROVEEDOR>_MODEL` |

**Para que sirva cualquier modelo** (también los chicos o locales):

- *Lista de modelos*: la interfaz consulta al servicio qué modelos tiene (`GET /models`) y
  los ofrece en una lista. En Ollama son los ya descargados; uno nuevo se descarga desde
  la misma pantalla (botón *Descargar en el servidor*, usa `/api/pull` de Ollama).
- *Redacción por secciones* (`LLM_SINTESIS_MODO`): `auto` (por defecto) redacta el SITREP
  de una vez y, si el modelo no alcanza o su ventana es < 32k, lo rehace en 6 llamadas
  chicas; `secciones` lo hace siempre por partes; `completa`, siempre de una vez. Si una
  sección secundaria falla queda vacía y la versión muestra un aviso para revisarla.
- *Verificar modelo*: prueba el modelo con un parte ficticio (conexión, extracción,
  resumen ejecutivo y respeto de cifras) y entrega un veredicto. No reemplaza al Robot QA.
- *Gateway LiteLLM*: `docker compose --profile gateway up -d litellm` y declarar los
  modelos en `infra/litellm/config.yaml`; en el sistema, proveedor *Gateway LiteLLM*.

Bases ya creadas deben aplicar la migración:
`docker compose exec -T db psql -U $DB_USER -d $DB_NAME < db/migrations/003_llm_configurable.sql`.
Si se cambia a `anthropic` hay que reconstruir las imágenes (`docker compose build api worker`).

Cada llamada deja una línea `llm_call` en `docker compose logs worker` con proveedor,
modelo, operación, latencia y tokens (nunca el contenido). Cada versión del SITREP
guarda qué modelo la redactó (`briefing_versiones.modelo_llm`) y el Robot QA lo lee
de `GET /api/info` para su manifiesto.
