# Robot QA — MVP-Ciitec

Plataforma de pruebas automatizadas para el sistema de Síntesis Automática de
Reportes (`../backend`), construida para el ramo Taller en Empresa 2 siguiendo
los tres documentos de [`../ROBOT_QA/`](../ROBOT_QA/):

- `TE2 -C5 - PLANIFICACION PRUEBAS QA.pdf` — formato documental (plan de
  pruebas, caso de prueba, registro de incidencias).
- `Resumen_ISO_IEC_IEEE_29119-1_2022.pdf` — marco conceptual (riesgo, oráculo,
  niveles, estrategia).
- `Guia_Proyecto_Robot_QA_para_Sistemas_IA_y_LLM.pdf` — el enunciado del
  proyecto: arquitectura, taxonomía de pruebas, evaluación en 6 niveles, gate
  de liberación, criterios de aceptación.

## Arquitectura

```
Test Registry (testcases/*.yaml) ──▶ Runner ──▶ SUT Adapter ──▶ Observation
                                                                    │
                                                                    ▼
                                                              Evaluadores
                                                                    │
                                                                    ▼
                                            Agregador (gate) ──▶ Reportero
                                            (PASS/HUMAN_REVIEW/REJECT)  (HTML/JSON/JUnit)
```

- **`src/robot_qa/adapters/`** — `ApiAdapter` (invoke real contra
  `https://localhost/api`) y `ReplayAdapter` (reconstruye una corrida anterior
  desde `evidence/` sin llamar al SUT ni al LLM).
- **`src/robot_qa/evaluators/`** — 9 evaluadores (6 deterministas, 1 híbrido
  metamórfico, 1 semántico con juez LLM, 1 de revisión humana). Ver
  `evaluators/__init__.py` para el registro completo.
- **`src/robot_qa/runner/orchestrator.py`** — ejecuta una campaña completa:
  repeticiones, evaluadores, evidencia, manifiesto de reproducibilidad.
- **`src/robot_qa/reporting/`** — métricas, gate de liberación, comparación
  con línea base, reportes HTML/JUnit.

## Uso

```bash
# 0. Requisitos: docker compose up --build (desde la raíz del repo) y
#    GEMINI_API_KEY configurada en el .env de la raíz (la misma que usa el SUT).
pip install -e ./robot-qa
python scripts/gen_corpus.py --ground-truth   # corpus real + ground truth (RAG/rendimiento)

# 1. Campaña rápida (10 casos funcionales)
python -m robot_qa run --campaign smoke

# 2. Campaña completa (52 casos, 3 repeticiones) y guardarla como línea base
python -m robot_qa run --campaign full --save-baseline

# 3. Solo seguridad
python -m robot_qa run --campaign security

# 4. Reejecutar los evaluadores sobre evidencia ya capturada (sin red ni LLM)
python -m robot_qa run --campaign full --replay <run_id>

# 5. Listar el catálogo
python -m robot_qa list-cases --campaign full

# 6. Calibración humana (acuerdo juez LLM vs revisor humano)
python -m robot_qa calibrate <run_id>
```

Salida: `reports/<run_id>.html` (reporte legible), `reports/<run_id>.json`
(resultado completo), `reports/<run_id>.junit.xml` (CI), `reports/baseline.json`
(línea base versionada), `evidence/<run_id>/` (toda la evidencia, no se
versiona — ver `.gitignore`). Código de salida: `0` PASS, `1` HUMAN_REVIEW,
`2` REJECT.

## Catálogo de casos

52 casos en 6 familias (`testcases/`), generados por
`scripts/generate_testcases.py` (correrlo de nuevo tras editar el generador
para regenerar el YAML; el YAML resultante SÍ se versiona y es el catálogo
real que carga el runner):

| Suite | Casos | Qué prueba |
|---|---|---|
| `smoke` (funcional) | 10 | login, ingesta multi-formato, generación, versionado (RF-007), point-in-time (RF-009), exportación (RF-008), aprobación |
| `rag` | 12 | groundedness/citas (`GET .../trazabilidad`), recall de hechos requeridos, síntesis multi-documento |
| `robustez` | 10 | 6 relaciones metamórficas (parafraseo, reorden, quitar documento, documento irrelevante, duplicado, formato de fecha) |
| `security` | 10 | prompt injection, fuga por nivel de clasificación, RAG contaminado, consumo excesivo, integridad de auditoría, sobreconfianza |
| `rendimiento` | 5 | latencia end-to-end, incluye el RNF-004 literal (50 documentos < 3 min) |
| `confiabilidad` | 5 | consistencia entre repeticiones (`pass@k`) |

## Limitaciones conocidas (documentadas, no escondidas)

- **Costo/tokens**: la API de MVP-Ciitec no expone tokens ni costo del LLM en
  sus respuestas, así que `cost_per_successful_task` (Guía §7) no se puede
  medir sin instrumentar el backend. El evaluador `budget` solo mide latencia.
- **Segmentación por unidad**: los 5 usuarios demo del `db/seed.sql` tienen
  solo dos unidades reales (`I Brigada` para operaciones/analista; el resto
  son roles transversales que ven todo). El robot prueba fuga **por nivel de
  clasificación** (RESERVADO/SECRETO), que sí es reproducible con estos
  usuarios; probar fuga **entre unidades no transversales** requeriría sumar
  un sexto usuario demo de otra unidad a `db/seed.sql` y a `LDAP_USERS` en
  `docker-compose.yml` (no se hizo: es un cambio a la infraestructura
  compartida, fuera del alcance de este robot).
- **`rubric_llm` y `metamorphic`** dependen de que Gemini esté disponible; con
  `--no-judge` o sin `GEMINI_API_KEY`, esos casos se reportan explícitamente
  como no evaluados (nunca se inventa un puntaje).
