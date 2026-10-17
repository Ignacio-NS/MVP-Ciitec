# CONTEXT — Sistema de Síntesis Automática de Briefings (CIITEC / Ejército de Chile)

> Documento maestro para Claude Code. Léelo junto con el documento de
> requerimientos (RF-001..RF-010, RNF-001..RNF-006), que es la fuente de verdad
> de QUÉ debe hacer el sistema. La arquitectura y el stack ya están decididos y
> NO se re-discuten; tu trabajo es planificar e implementar CÓMO, con calidad de
> producción. Ya hay artefactos base preparados (ver "Lo que ya está hecho").

## Modo de trabajo
Estás en modo PLAN. Primero lee el documento de requerimientos y revisa el repo.
NO escribas código todavía: entrega un plan de implementación detallado y deja
las preguntas abiertas para que las confirme antes de codear.

## Objetivo de calidad
NO es un prototipo descartable. Apuntamos a una implementación completa y pulida:
TODOS los requerimientos funcionales (RF-001..RF-010) funcionando, y TODOS los no
funcionales (RNF-001..RNF-006) con mecanismos reales (no simulados). Debe poder
demostrarse end-to-end y resistir una revisión técnica exigente.

## Arquitectura definida (no re-discutir)
Aplicación web interna, despliegue on-premise, monorepo, arquitectura en capas:

- **Capa 1 — Presentación:** React + TypeScript (Vite), intranet por HTTPS. PWA
  con caché local para conectividad degradada (RF-010).
- **Capa 2 — Aplicación/API:** Nginx (reverse proxy + TLS 1.3), FastAPI (async),
  auth contra LDAP/AD, Celery + Redis (tareas asíncronas), WebSocket (progreso).
- **Capa 3 — Procesamiento/IA (worker):** parser de documentos, extracción
  NLP/LLM, detector de inconsistencias, generador de briefing, motor de versiones,
  exportador. Estilo **pipes & filters**: Ingestar → Normalizar → Extraer →
  Detectar → Sintetizar.
- **Capa 4 — Datos:** PostgreSQL + pgvector (relacional + vectorial en una sola
  BD), MinIO (documentos originales), audit log inmutable.

**Stack:** React+TS · FastAPI · Celery+Redis · Nginx · LLM detrás de la
interfaz pluggable `LLMProvider` (por defecto Gemini 2.5 Flash; también Claude,
modelo local con Ollama/vLLM, nube privada por endpoint OpenAI-compatible y más de 100
servicios vía el gateway LiteLLM; se elige con `LLM_PROVIDER` o desde la pantalla
*Motor de IA*, ver README) · `sentence-transformers` para embeddings (local) · PostgreSQL +
pgvector · MinIO.

**Flujo:** Carga → Encola → Procesa → Valida → Entrega.
**Restricciones:** info clasificada en 3 niveles (Público/Reservado/Secreto);
50 documentos en < 3 min; el sistema solo LEE los documentos existentes (PDF,
Word, Excel, correos), no modifica procesos ni formatos.

## Lo que ya está hecho (úsalo, no lo reinventes)
- `db/schema.sql` — modelo de datos completo: fuentes, hechos (con trazabilidad y
  embedding), briefings, versiones append-only, trazabilidad bullet→hecho,
  inconsistencias, exportaciones, audit log con hash chain. Cada tabla mapeada a
  su RF/RNF.
- `db/seed.sql` — roles + usuarios demo.
- `docker-compose.yml` — stack completo (db, redis, minio, openldap, api, worker,
  frontend, nginx) con healthchecks.
- `.env.example` — todas las variables de entorno.
- `backend/app/llm/provider.py` — abstracción del LLM + `OpenAIProvider` con
  salida estructurada (JSON schema) y prompts de extracción y síntesis.
- `backend/requirements.txt` — dependencias.

## Estructura objetivo del monorepo
```
mvp-briefings/
├── docker-compose.yml
├── .env.example
├── db/                  schema.sql · seed.sql · migraciones (alembic)
├── infra/nginx/         nginx.conf · certs/ (TLS)
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py          FastAPI (rutas, middleware sesión 15 min)
│       ├── config.py        pydantic-settings
│       ├── db.py            engine / sesión SQLAlchemy
│       ├── models/          ORM
│       ├── auth/            LDAP + JWT + RBAC por nivel de clasificación
│       ├── api/             routers: fuentes, briefings, versiones, export, audit
│       ├── llm/provider.py  (ya creado)
│       ├── embeddings.py    sentence-transformers
│       ├── worker.py        Celery app
│       └── pipeline/        ingesta · normalizacion · extraccion · deteccion · sintesis · exportacion
└── frontend/
    └── src/   (React + TS, PWA, vistas de carga/revisión/versiones/export)
```

## Mapeo requerimiento → componente (para defender / IEEE 830)
- RF-001 ingesta → `pipeline/ingesta` (parsers PDF/Word/Excel/correo) + MinIO + `fuentes`
- RF-002 normalización → `pipeline/normalizacion` → `hechos.normalizado`
- RF-003 extracción → `llm/provider.extraer_hechos` (JSON schema) → `hechos`
- RF-004 generación → `llm/provider.sintetizar_briefing` → `briefing_versiones.contenido`
- RF-005 inconsistencias → `pipeline/deteccion` (pgvector + reglas + LLM) → `inconsistencias`
- RF-006 trazabilidad → `hechos.fuente_id` + `version_bullet_hechos`
- RF-007 versionado → `briefing_versiones` (append-only, diffs, aprobación)
- RF-008 exportación → `pipeline/exportacion` (weasyprint/docxtpl) → `exportaciones`
- RF-009 point-in-time → consulta de versión activa a la hora T
- RF-010 offline → PWA + IndexedDB + cola de sync
- RNF-001 auth → `auth/` (LDAP + RBAC + sesión 15 min)
- RNF-002 cifrado/clasificación → Nginx TLS 1.3 + cifrado en reposo + `nivel_clasificacion`
- RNF-003 auditoría → `audit_log` (inmutable, hash chain, retención 5 años)
- RNF-004 rendimiento → worker paralelo (concurrency) + índices
- RNF-005 disponibilidad → healthchecks + restart policies (SLA es de infra prod)
- RNF-006 usabilidad → UI en español, flujo cargar→generar→exportar

## Qué quiero en el plan
1. Confirmar/ajustar la estructura del monorepo.
2. Modelo de objetos (ORM) sobre el schema ya definido.
3. Diseño del pipeline (5 filtros desacoplados) y cómo cumple < 3 min / 50 docs.
4. Contrato de la API + canal WebSocket de progreso.
5. Estrategia de auth (LDAP→JWT→RBAC por nivel) y de cifrado.
6. Estrategia offline (qué se cachea, sync, conflictos).
7. Fases priorizadas: primero un end-to-end mínimo (un doc entra → sale briefing),
   luego completar cada RF/RNF.
8. Supuestos y preguntas abiertas para que yo decida.

## Levantar en local
```
cp .env.example .env   # y completar OPENAI_API_KEY y secretos
docker compose up --build
# api: https://localhost/api   · frontend: https://localhost   · MinIO: http://localhost:9001
```
> Nota: GitHub Copilot solo asiste al escribir código; la app necesita una
> OPENAI_API_KEY propia para las llamadas en runtime.
