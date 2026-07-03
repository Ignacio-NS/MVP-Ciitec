# Síntesis Automática de Reportes y Briefings Operacionales — CIITEC / Ejército de Chile

Aplicación web interna on-premise que **lee** documentos heterogéneos (PDF, Word,
Excel, correos, bitácoras), extrae hechos con LLM, genera un **briefing
institucional** versionado y trazable, detecta inconsistencias y lo exporta a
PDF/Word/texto. Monorepo, arquitectura en capas, LLM tras una interfaz pluggable
(por defecto GitHub Models `gpt-4o`; intercambiable por Groq o modelo local).

## Levantar en local

```bash
cp .env.example .env          # completar GEMINI_API_KEY, JWT_SECRET, ENCRYPTION_KEY
#   ENCRYPTION_KEY: 32 bytes base64, p.ej.  openssl rand -base64 32
make certs                    # certificados TLS self-signed (Windows: scripts/gen_certs.ps1)
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

## Notas

- **Proveedor LLM (intercambiable):** `LLM_PROVIDER` selecciona el back-end sin
  tocar el resto del código:
  - `gemini` (por defecto): Gemini vía endpoint OpenAI-compatible (`GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.1-pro`). Key en https://aistudio.google.com/apikey.
  - `github`: GitHub Models, `openai/gpt-4o` (`GITHUB_TOKEN` = PAT con permiso Models).
  - `groq`: Groq Llama 3.3 70B (`GROQ_API_KEY`, `GROQ_MODEL=llama-3.3-70b-versatile`).
  - `local`: modelo on-premise (clasificación de datos); implementar `LocalLLMProvider`.
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
