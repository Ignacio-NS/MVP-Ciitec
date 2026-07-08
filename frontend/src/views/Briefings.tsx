import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Icon } from "../components/icons";
import { Badge, Pill, fmtFecha } from "../components/ui";

type Item = {
  id: string;
  titulo: string;
  version_activa: number | null;
  estado: string;
  nivel_clasificacion: string;
  creado_en: string | null;
};

export default function Briefings() {
  const nav = useNavigate();
  const [items, setItems] = useState<Item[]>([]);
  const [cargando, setCargando] = useState(true);
  const [q, setQ] = useState("");
  const [fEstado, setFEstado] = useState("");
  const [fNivel, setFNivel] = useState("");

  useEffect(() => {
    api
      .listBriefings()
      .then((r) => setItems(r.briefings))
      .finally(() => setCargando(false));
  }, []);

  const filtrados = useMemo(
    () =>
      items.filter(
        (b) =>
          (!q || b.titulo.toLowerCase().includes(q.toLowerCase())) &&
          (!fEstado || b.estado === fEstado) &&
          (!fNivel || b.nivel_clasificacion === fNivel)
      ),
    [items, q, fEstado, fNivel]
  );

  const vacio = !cargando && filtrados.length === 0;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Repositorio</div>
          <h1 className="page-title">Historial de SITREPS</h1>
          <p className="page-sub">
            {cargando ? "Cargando…" : `${filtrados.length} documentos`} · ordenados por fecha de
            creación
          </p>
        </div>
        <Link className="btn btn--primary" to="/cargar">
          <Icon name="plus" />
          Nuevo SITREP
        </Link>
      </div>

      <div className="toolbar">
        <div className="search" style={{ flex: 1, minWidth: 240, maxWidth: 380 }}>
          <Icon name="search" />
          <input
            className="input"
            placeholder="Buscar por título…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <select
          className="select"
          style={{ width: "auto" }}
          value={fEstado}
          onChange={(e) => setFEstado(e.target.value)}
        >
          <option value="">Todos los estados</option>
          <option>BORRADOR</option>
          <option>GENERANDO</option>
          <option>LISTO</option>
          <option>APROBADO</option>
        </select>
        <select
          className="select"
          style={{ width: "auto" }}
          value={fNivel}
          onChange={(e) => setFNivel(e.target.value)}
        >
          <option value="">Toda clasificación</option>
          <option>PUBLICO</option>
          <option>RESERVADO</option>
          <option>SECRETO</option>
        </select>
      </div>

      {vacio ? (
        <div className="card">
          <div className="empty">
            <div className="empty__ico">
              <Icon name="list-empty" strokeWidth={1.6} />
            </div>
            <div className="empty__title">
              {items.length === 0 ? "Aún no hay SITREP." : "Sin resultados para el filtro."}
            </div>
            <p style={{ maxWidth: "40ch", margin: "0 auto var(--sp-5)" }}>
              Cargue documentos fuente y genere el primer SITREP institucional del sector.
            </p>
            <Link className="btn btn--primary" to="/cargar">
              <Icon name="upload" />
              Cargar documentos
            </Link>
          </div>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table table--clickable">
            <thead>
              <tr>
                <th style={{ width: "34%" }}>Título</th>
                <th>Versión activa</th>
                <th>Estado</th>
                <th>Clasificación</th>
                <th className="num">Creado</th>
              </tr>
            </thead>
            <tbody>
              {cargando && (
                <tr>
                  <td colSpan={5}>
                    <div className="skel" style={{ height: 14, width: "60%" }} />
                  </td>
                </tr>
              )}
              {filtrados.map((b) => (
                <tr key={b.id} onClick={() => nav(`/briefings/${b.id}`)}>
                  <td>
                    <div className="cell-strong">
                      <Link to={`/briefings/${b.id}`} onClick={(e) => e.stopPropagation()}>
                        {b.titulo}
                      </Link>
                    </div>
                    <div className="cell-sub mono">{b.id.slice(0, 8)}</div>
                  </td>
                  <td className="cell-mono">{b.version_activa != null ? `v${b.version_activa}` : "—"}</td>
                  <td>
                    <Pill estado={b.estado} />
                  </td>
                  <td>
                    <Badge nivel={b.nivel_clasificacion} />
                  </td>
                  <td className="num cell-sub">{fmtFecha(b.creado_en)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
