-- Migración idempotente: elegir qué páginas de la plantilla entran en el SITREP
-- (botón "Contenido del SITREP" en Motor de IA). Append-only; solo una fila vigente.
--
-- `db/schema.sql` solo corre al crear el volumen; para bases ya existentes:
--   docker compose exec -T db psql -U $DB_USER -d $DB_NAME < db/migrations/004_sitrep_paginas.sql
--
-- Sin esta migración el sistema funciona igual (entran todas las páginas) y la
-- interfaz avisa que no se puede guardar la selección.

CREATE TABLE IF NOT EXISTS sitrep_paginas (
    id               BIGSERIAL PRIMARY KEY,
    excluidas        JSONB NOT NULL DEFAULT '[]'::jsonb,
    vigente          BOOLEAN NOT NULL DEFAULT false,
    creado_por       UUID REFERENCES usuarios(id),
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    desactivado_en   TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sitrep_paginas_vigente ON sitrep_paginas (vigente) WHERE vigente;
