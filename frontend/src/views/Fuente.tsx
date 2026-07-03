import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { Icon } from "../components/icons";
import { Badge } from "../components/ui";

// Vista de fuente (RF-006): muestra el texto extraído del documento origen y resalta
// la cita textual (texto_origen) del hecho desde el que se llegó (trazabilidad).
export default function Fuente() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { state } = useLocation();
  const cita: string = ((state as any)?.cita || "").trim();
  const [f, setF] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const markRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    api
      .getFuenteTexto(id)
      .then(setF)
      .catch((e) => setErr(e.message || "No se pudo cargar la fuente"));
  }, [id]);

  // Llevar el scroll a la primera coincidencia de la cita una vez renderizada.
  useEffect(() => {
    if (f && cita && markRef.current) {
      markRef.current.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [f, cita]);

  // Parte el texto en nodos, envolviendo en <mark> cada aparición de la cita.
  function render(texto: string) {
    if (!cita) return texto;
    const partes = texto.split(cita);
    if (partes.length === 1) return texto; // no encontrada: se muestra arriba en su recuadro
    const out: any[] = [];
    partes.forEach((p, i) => {
      out.push(<span key={`p${i}`}>{p}</span>);
      if (i < partes.length - 1) {
        out.push(
          <mark
            key={`m${i}`}
            ref={i === 0 ? (markRef as any) : undefined}
            className="src-cita"
          >
            {cita}
          </mark>
        );
      }
    });
    return out;
  }

  return (
    <div className="page">
      <div className="row gap2" style={{ marginBottom: "var(--sp-4)" }}>
        <button className="btn btn--ghost btn--sm" onClick={() => navigate(-1)}>
          <Icon name="arrow-left" />
          Volver
        </button>
        <span className="muted">/</span>
        <span className="muted">Fuente</span>
      </div>

      {err ? (
        <div className="card">
          <div className="card__body muted">{err}</div>
        </div>
      ) : !f ? (
        <div className="card">
          <div className="card__body muted">Cargando…</div>
        </div>
      ) : (
        <>
          <div className="page-head">
            <div>
              <div className="row gap2 row--wrap" style={{ marginBottom: 8 }}>
                <Badge nivel={f.nivel_clasificacion} lg />
                <span className="badge badge--res" style={{ height: 18 }}>
                  {f.tipo}
                </span>
              </div>
              <h1 className="page-title">{f.nombre_archivo}</h1>
              {f.unidad && <p className="page-sub">Unidad: {f.unidad}</p>}
            </div>
          </div>

          {cita && (
            <div className="card" style={{ marginBottom: "var(--sp-4)" }}>
              <div className="card__head">
                <div className="card__title">
                  <Icon name="link" className="card__icon" />
                  Cita del hecho
                </div>
              </div>
              <div className="card__body">
                <blockquote className="src-cita-box">{cita}</blockquote>
              </div>
            </div>
          )}

          <div className="card">
            <div className="card__head">
              <div className="card__title">
                <Icon name="text-lines" className="card__icon" />
                Texto extraído
              </div>
            </div>
            <div className="card__body">
              {f.texto_extraido ? (
                <pre className="src-text">{render(f.texto_extraido)}</pre>
              ) : (
                <p className="muted">Sin texto extraído.</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
