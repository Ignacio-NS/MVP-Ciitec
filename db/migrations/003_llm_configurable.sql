-- Migración idempotente: motor de IA intercambiable (cualquier modelo).
--   1) acción de auditoría CONFIG_IA (cambios de proveedor/modelo desde la interfaz),
--   2) columna modelo_llm en briefing_versiones (qué modelo redactó cada versión),
--   3) tabla llm_config (configuración elegida por el Administrador del Sistema).
--
-- `db/schema.sql` solo corre al crear el volumen; para bases ya existentes:
--   docker compose exec -T db psql -U $DB_USER -d $DB_NAME < db/migrations/003_llm_configurable.sql
--
-- Sin esta migración el sistema sigue funcionando con el .env (la interfaz de
-- "Motor de IA" mostrará un aviso y no permitirá guardar).

ALTER TYPE accion_audit ADD VALUE IF NOT EXISTS 'CONFIG_IA';

ALTER TABLE briefing_versiones ADD COLUMN IF NOT EXISTS modelo_llm TEXT;

CREATE TABLE IF NOT EXISTS llm_config (
    id               BIGSERIAL PRIMARY KEY,
    proveedor        TEXT NOT NULL,
    modelo           TEXT,
    base_url         TEXT,
    api_key_cifrada  TEXT,
    json_mode        BOOLEAN,
    temperature      TEXT,
    token_param      TEXT,
    extra_params     JSONB,
    context_tokens   INT,
    timeout_s        REAL,
    sintesis_modo    TEXT,
    vigente          BOOLEAN NOT NULL DEFAULT false,
    creado_por       UUID REFERENCES usuarios(id),
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    desactivado_en   TIMESTAMPTZ
);
-- (para quien aplicó una versión anterior de esta migración)
ALTER TABLE llm_config ADD COLUMN IF NOT EXISTS sintesis_modo TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_config_vigente ON llm_config (vigente) WHERE vigente;
