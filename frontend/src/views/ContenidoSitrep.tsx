import { useEffect, useState } from "react";
import { api, mensajeError } from "../api";
import { Icon, IconName } from "../components/icons";

type Pagina = {
  clave: string;
  numero: number;
  titulo: string;
  descripcion: string;
  obligatoria: boolean;
  incluida: boolean;
};

type Estado = {
  paginas: Pagina[];
  excluidas: string[];
  migracion_aplicada: boolean;
  puede_editar: boolean;
  actualizado_en: string | null;
};

const ICONO: Record<string, IconName> = {
  ejecutivo: "file-text",
  personal: "personal",
  inteligencia: "inteligencia",
  operaciones_despliegue: "operaciones",
  operaciones_terreno: "operaciones",
  logistica: "logistica",
};

/** Panel "Contenido del SITREP": qué páginas de la plantilla entran en los SITREP que se generen. */
export function ContenidoSitrep({ onCerrar }: { onCerrar: () => void }) {
  const [estado, setEstado] = useState<Estado | null>(null);
  const [fuera, setFuera] = useState<Set<string>>(new Set());
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  useEffect(() => {
    api
      .sitrepPaginas()
      .then((e: Estado) => {
        setEstado(e);
        setFuera(new Set(e.excluidas));
      })
      .catch((e) => setError(mensajeError(e)));
  }, []);

  const editable = !!estado?.puede_editar;
  const cambiado =
    !!estado && (fuera.size !== estado.excluidas.length || estado.excluidas.some((c) => !fuera.has(c)));
  const total = estado?.paginas.length || 0;
  const entran = total - fuera.size;

  function alternar(p: Pagina) {
    if (!editable || p.obligatoria) return;
    setOk("");
    setFuera((s) => {
      const n = new Set(s);
      if (n.has(p.clave)) n.delete(p.clave);
      else n.add(p.clave);
      return n;
    });
  }

  async function guardar() {
    setGuardando(true);
    setError("");
    setOk("");
    try {
      const e: Estado = await api.sitrepPaginasGuardar([...fuera]);
      setEstado(e);
      setFuera(new Set(e.excluidas));
      setOk("Guardado. Se aplica a los SITREP que se generen desde ahora.");
    } catch (e) {
      setError(mensajeError(e));
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div className="card">
      <div className="card__head">
        <div className="card__title">
          <Icon name="list" /> Contenido del SITREP
        </div>
        <div className="btn-group">
          {estado && (
            <span className="hint">
              Entran {entran} de {total} páginas
            </span>
          )}
          <button className="btn btn--ghost btn--sm" onClick={onCerrar} aria-label="Cerrar">
            <Icon name="x" />
          </button>
        </div>
      </div>
      <div className="card__body stack" style={{ gap: "var(--sp-3)" }}>
        <p className="hint" style={{ margin: 0 }}>
          Elija qué páginas de la plantilla institucional entran en el SITREP. Lo que se quita no lo redacta la IA (ahorra
          tiempo y tokens) y no aparece en el PDF ni en la vista del briefing. En la portada, los datos de las páginas
          quitadas se muestran como “-.-”. Las hojas adicionales no se ven afectadas.
        </p>
        {error && (
          <div className="alert alert--err" style={{ marginBottom: 0 }}>
            <Icon name="alert-circle" />
            <span>{error}</span>
          </div>
        )}
        {ok && (
          <div className="alert alert--ok" style={{ marginBottom: 0 }}>
            <Icon name="check-circle" />
            <span>{ok}</span>
          </div>
        )}
        {estado && !estado.migracion_aplicada && (
          <div className="alert alert--err" style={{ marginBottom: 0 }}>
            <Icon name="alert-triangle" />
            <span>
              Falta aplicar <span className="mono">db/migrations/004_sitrep_paginas.sql</span>. Mientras tanto entran
              todas las páginas.
            </span>
          </div>
        )}
        {!estado && !error && <span className="muted">Cargando…</span>}
        {estado && (
          <div className="sitrep-pags">
            {estado.paginas.map((p) => {
              const dentro = !fuera.has(p.clave);
              return (
                <div key={p.clave} className={`sitrep-pag${dentro ? "" : " is-off"}`}>
                  <div className="sitrep-pag__num">{p.numero}</div>
                  <Icon name={ICONO[p.clave] || "file"} />
                  <div className="sitrep-pag__txt">
                    <div className="sitrep-pag__tit">
                      {p.titulo}
                      {p.obligatoria && <span className="hint"> · obligatoria</span>}
                    </div>
                    <div className="hint">{p.descripcion}</div>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={dentro}
                    aria-label={`${dentro ? "Quitar" : "Incluir"} ${p.titulo}`}
                    className={`toggle${dentro ? " is-on" : ""}`}
                    onClick={() => alternar(p)}
                    disabled={!editable || p.obligatoria}
                    title={p.obligatoria ? "Siempre entra" : dentro ? "Entra en el SITREP" : "No entra en el SITREP"}
                  />
                </div>
              );
            })}
          </div>
        )}
        {estado && (
          <div className="btn-group" style={{ justifyContent: "flex-end" }}>
            {!editable && <span className="hint">Solo el Administrador del Sistema puede cambiarlo.</span>}
            {editable && (
              <>
                <button
                  className="btn btn--ghost btn--sm"
                  onClick={() => setFuera(new Set())}
                  disabled={guardando || fuera.size === 0}
                >
                  Incluir todas
                </button>
                <button className="btn btn--primary btn--sm" onClick={guardar} disabled={guardando || !cambiado}>
                  {guardando ? <span className="spin" /> : <Icon name="check-circle" />}
                  Guardar
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
