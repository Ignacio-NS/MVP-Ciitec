// Pruebas QA de motores de IA (solo lectura): resultados de benchmark_llm para
// analizarlos en equipo — resumen por motor, cada corrida y el SITREP generado.
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, mensajeError } from "../api";
import { Icon } from "../components/icons";
import { fmtFecha } from "../components/ui";
import { SeccionInstitucional } from "./Briefing";

type Resumen = {
  lote: string;
  motor: string;
  proveedor: string;
  modelo: string;
  corridas: number;
  exitosas: number;
  tiempo_s: number | null;
  tiempo_min_s: number | null;
  tiempo_max_s: number | null;
  calidad_pct: number | null;
  exactitud_pct: number | null;
  cifras: number | null;
  costo_clp: number | null;
  contradicciones: number | null;
  hechos: number | null;
};
type Corrida = {
  id: string;
  lote: string;
  motor: string;
  proveedor: string;
  modelo: string;
  corrida: number;
  inicio: string | null;
  estado: string;
  tiempo_s: number | null;
  calidad_pct: number | null;
  calidad: string | null;
  exactitud_pct: number | null;
  cifras: number | null;
  costo_clp: number | null;
  contradicciones: number;
  hechos: number;
  modo_sintesis: string | null;
  error: string | null;
};

const n1 = (v: number | null | undefined, suf = "") =>
  v == null ? "—" : `${v.toLocaleString("es-CL", { maximumFractionDigits: 1 })}${suf}`;

const SECCIONES = [
  { key: "personal", titulo: "Personal", icon: "personal" },
  { key: "inteligencia", titulo: "Inteligencia", icon: "inteligencia" },
  { key: "operaciones", titulo: "Operaciones", icon: "operaciones" },
  { key: "logistica", titulo: "Logística", icon: "logistica" },
];

function Barra({ valor, max, tono }: { valor: number | null; max: number; tono?: string }) {
  const pct = valor == null || max <= 0 ? 0 : Math.max(2, (100 * valor) / max);
  return (
    <div className="qa-bar" aria-hidden="true">
      <div className="qa-bar__fill" style={{ width: `${pct}%`, background: tono || "var(--accent)" }} />
    </div>
  );
}

// ============================ LISTADO ============================
export default function PruebasQA() {
  const nav = useNavigate();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [lote, setLote] = useState("");

  useEffect(() => {
    api
      .qaCorridas()
      .then((r) => {
        setData(r);
        setLote((l) => l || r.lotes?.[0] || "");
      })
      .catch((e) => setError(mensajeError(e)));
  }, []);

  const resumen: Resumen[] = useMemo(
    () =>
      (data?.resumen || [])
        .filter((r: Resumen) => r.lote === lote)
        .sort((a: Resumen, b: Resumen) => (a.tiempo_s ?? 1e9) - (b.tiempo_s ?? 1e9)),
    [data, lote]
  );
  const corridas: Corrida[] = useMemo(
    () =>
      (data?.corridas || [])
        .filter((c: Corrida) => c.lote === lote)
        .sort((a: Corrida, b: Corrida) => a.motor.localeCompare(b.motor) || a.corrida - b.corrida),
    [data, lote]
  );
  const noDisp = (data?.no_disponibles || []).filter((n: any) => n.lote === lote);
  const maxT = Math.max(1, ...resumen.map((r) => r.tiempo_s || 0));
  const maxC = Math.max(1, ...resumen.map((r) => r.costo_clp || 0));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Aseguramiento de calidad</div>
          <h1 className="page-title">Pruebas QA de motores de IA</h1>
          <p className="page-sub">
            El mismo SITREP generado con cada motor sobre los documentos de ejemplo (ficticios): tiempo,
            calidad, exactitud de cifras y costo.
          </p>
        </div>
        {data?.lotes?.length > 0 && (
          <select className="select" style={{ width: "auto" }} value={lote} onChange={(e) => setLote(e.target.value)}>
            {data.lotes.map((l: string) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <div className="alert alert--err">{error}</div>}
      {data && !data.disponible && (
        <div className="alert alert--warn">
          No hay resultados montados en el servidor ({data.carpeta}). Corra la prueba con
          benchmark_llm\correr_qa_motores.bat y reinicie la API.
        </div>
      )}
      {!data && !error && <p className="muted">Cargando…</p>}

      {data?.disponible && (
        <div className="stack">
          <div className="card">
            <div className="card__head">
              <div className="card__title">
                <Icon name="trending" className="card__icon" />
                Resumen por motor
              </div>
              <span className="hint">promedio de las corridas exitosas · ordenado por tiempo</span>
            </div>
            <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Motor</th>
                    <th>Corridas</th>
                    <th style={{ width: "22%" }}>Tiempo por SITREP</th>
                    <th className="num">Calidad (datos clave)</th>
                    <th className="num">Cifras correctas</th>
                    <th style={{ width: "16%" }}>Costo por SITREP</th>
                    <th className="num">Contradicciones</th>
                  </tr>
                </thead>
                <tbody>
                  {resumen.length === 0 && noDisp.length === 0 && (
                    <tr>
                      <td colSpan={7} className="muted">
                        Sin corridas en este lote.
                      </td>
                    </tr>
                  )}
                  {resumen.map((r) => (
                    <tr key={r.motor}>
                      <td>
                        <div className="cell-strong">{r.motor}</div>
                        <div className="hint mono">{r.modelo}</div>
                      </td>
                      <td>
                        {r.exitosas}/{r.corridas} OK
                      </td>
                      <td>
                        <div className="row row--between">
                          <strong>{n1(r.tiempo_s, " s")}</strong>
                          <span className="hint">
                            {n1(r.tiempo_min_s)}–{n1(r.tiempo_max_s)} s
                          </span>
                        </div>
                        <Barra valor={r.tiempo_s} max={maxT} />
                      </td>
                      <td className="num">{n1(r.calidad_pct, " %")}</td>
                      <td className="num">
                        {n1(r.exactitud_pct, " %")}
                        <div className="hint">de ≈ {r.cifras == null ? "—" : Math.round(r.cifras)} cifras</div>
                      </td>
                      <td>
                        <strong>{r.costo_clp == null ? "—" : `CLP ${n1(r.costo_clp)}`}</strong>
                        <Barra valor={r.costo_clp} max={maxC} tono="var(--res)" />
                      </td>
                      <td className="num">{n1(r.contradicciones)}</td>
                    </tr>
                  ))}
                  {noDisp.map((n: any) => (
                    <tr key={n.motor}>
                      <td>
                        <div className="cell-strong">{n.motor}</div>
                        <div className="hint mono">{n.modelo}</div>
                      </td>
                      <td colSpan={6}>
                        <span className="pill" style={{ color: "var(--sec)", background: "var(--sec-bg)" }}>
                          <span className="pill__dot" />
                          No se pudo probar
                        </span>{" "}
                        <span className="hint">{n.error}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card__body hint">
              Tiempo: solo el trabajo de la IA (extraer, detectar y redactar), sin la carga ni la exportación.
              Calidad: datos clave que el SITREP debe contener. Cifras correctas: números del SITREP que
              aparecen en los documentos (las sumas calculadas, como totales, figuran como no encontradas).
              Costo estimado con los precios oficiales de {data.precios?.fecha} (US$ 1 = CLP{" "}
              {data.precios?.usd_clp}).
            </div>
          </div>

          <div className="card">
            <div className="card__head">
              <div className="card__title">
                <Icon name="list" className="card__icon" />
                Corridas
              </div>
              <span className="hint">clic en una fila para ver el SITREP generado</span>
            </div>
            <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
              <table className="table table--clickable">
                <thead>
                  <tr>
                    <th>Motor</th>
                    <th>Corrida</th>
                    <th>Fecha</th>
                    <th>Estado</th>
                    <th className="num">Tiempo</th>
                    <th className="num">Calidad</th>
                    <th className="num">Cifras correctas</th>
                    <th className="num">Costo</th>
                    <th className="num">Hechos</th>
                  </tr>
                </thead>
                <tbody>
                  {corridas.map((c) => (
                    <tr key={c.id} onClick={() => nav(`/pruebas-qa/${c.id}`)}>
                      <td className="cell-strong">{c.motor}</td>
                      <td>#{c.corrida}</td>
                      <td className="mono">{fmtFecha(c.inicio)}</td>
                      <td>
                        <span
                          className="pill"
                          title={c.error || ""}
                          style={
                            c.estado === "OK"
                              ? { color: "var(--pub)", background: "var(--pub-bg)" }
                              : { color: "var(--sec)", background: "var(--sec-bg)" }
                          }
                        >
                          <span className="pill__dot" />
                          {c.estado}
                        </span>
                      </td>
                      <td className="num">{n1(c.tiempo_s, " s")}</td>
                      <td className="num">{c.calidad || "—"}</td>
                      <td className="num">{n1(c.exactitud_pct, " %")}</td>
                      <td className="num">{c.costo_clp == null ? "—" : `CLP ${n1(c.costo_clp)}`}</td>
                      <td className="num">{c.hechos}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================ DETALLE DE UNA CORRIDA ============================
export function PruebaQADetalle() {
  const { id = "" } = useParams();
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState("");
  const [bajando, setBajando] = useState("");

  // El SITREP de la corrida con la plantilla institucional (mismo exportador que un briefing).
  async function exportar(formato: string) {
    const ext = formato === "PDF" ? "pdf" : formato === "WORD" ? "docx" : "txt";
    setBajando(formato);
    setError("");
    try {
      const blob = await api.qaExportar(id, formato);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `QA_${id}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(mensajeError(e));
    } finally {
      setBajando("");
    }
  }

  useEffect(() => {
    api
      .qaCorrida(id)
      .then(setD)
      .catch((e) => setError(mensajeError(e)));
  }, [id]);

  const c = d?.sitrep || {};
  const asuntos: any[] = c.asuntos_criticos || [];
  const hechosPorId: Record<string, any> = useMemo(
    () => Object.fromEntries((d?.hechos_detalle || []).map((h: any) => [h.id, h])),
    [d]
  );

  return (
    <div className="page">
      <div className="row gap2" style={{ marginBottom: "var(--sp-4)" }}>
        <Link className="btn btn--ghost btn--sm" to="/pruebas-qa">
          <Icon name="arrow-left" />
          Pruebas QA
        </Link>
      </div>
      {error && <div className="alert alert--err">{error}</div>}
      {!d && !error && <p className="muted">Cargando…</p>}
      {d && (
        <>
          <div className="page-head">
            <div>
              <div className="eyebrow">
                {d.lote} · corrida #{d.corrida} · {fmtFecha(d.inicio)}
              </div>
              <h1 className="page-title">{d.motor}</h1>
              <p className="page-sub mono">
                {d.proveedor} · {d.modelo} · síntesis {d.modo_sintesis || "—"}
              </p>
            </div>
            {d.sitrep && (
              <div className="row gap2">
                <button className="btn btn--secondary" onClick={() => exportar("PDF")} disabled={!!bajando}>
                  <Icon name="file-text" />
                  {bajando === "PDF" ? "Generando PDF…" : "PDF"}
                </button>
                <button className="btn btn--secondary" onClick={() => exportar("WORD")} disabled={!!bajando}>
                  <Icon name="file" />
                  Word
                </button>
                <button className="btn btn--secondary" onClick={() => exportar("TEXTO")} disabled={!!bajando}>
                  <Icon name="text-lines" />
                  Texto
                </button>
              </div>
            )}
          </div>

          <div className="qa-kpis">
            <div className="metric">
              <div className="metric__k">Tiempo total</div>
              <div className="metric__v">{n1(d.tiempo_s, " s")}</div>
              <div className="hint">
                extraer {n1(d.t_extraccion_s)} · detectar {n1(d.t_contradicciones_s)} · redactar{" "}
                {n1(d.t_sintesis_s)} s
              </div>
            </div>
            <div className="metric">
              <div className="metric__k">Calidad (datos clave)</div>
              <div className="metric__v">{d.calidad || "—"}</div>
              <div className="hint">{n1(d.calidad_pct, " %")}</div>
            </div>
            <div className="metric">
              <div className="metric__k">Cifras correctas</div>
              <div className="metric__v">{n1(d.exactitud_pct, " %")}</div>
              <div className="hint">de {n1(d.cifras)} cifras en el SITREP</div>
            </div>
            <div className="metric">
              <div className="metric__k">Costo estimado</div>
              <div className="metric__v">{d.costo_clp == null ? "—" : `CLP ${n1(d.costo_clp)}`}</div>
              <div className="hint">
                {n1(d.tokens_in)} tokens de entrada · {n1(d.tokens_out)} de salida
              </div>
            </div>
          </div>

          {d.error && <div className="alert alert--err mt4">Corrida fallida: {d.error}</div>}
          {d.avisos_detalle?.length > 0 && (
            <div className="alert alert--warn mt4">{d.avisos_detalle.join(" ")}</div>
          )}

          <div className="detail-grid mt6">
            <div className="stack">
              <div className="card">
                <div className="card__head">
                  <div className="card__title">
                    <Icon name="clipboard" className="card__icon" />
                    Resumen ejecutivo
                  </div>
                </div>
                <div className="card__body">
                  <ul className="bullets">
                    {(c.resumen_ejecutivo || []).map((t: string, i: number) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="card">
                <div className="card__head">
                  <div className="card__title">Situación</div>
                </div>
                <div className="card__body">
                  <p style={{ lineHeight: 1.6 }}>{c.situacion?.resumen || "-.-"}</p>
                  {(c.situacion?.aspectos || []).length > 0 && (
                    <ul className="bullets mt2">
                      {c.situacion.aspectos.map((a: string, i: number) => (
                        <li key={i}>{a}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              <div className="card">
                <div className="card__head">
                  <div className="card__title">
                    <Icon name="alert-triangle" className="card__icon" style={{ color: "var(--res)" }} />
                    Asuntos críticos
                  </div>
                </div>
                <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th style={{ width: "36%" }}>Asunto</th>
                        <th>Impacto</th>
                        <th>Responsable</th>
                      </tr>
                    </thead>
                    <tbody>
                      {asuntos.map((a, i) => (
                        <tr key={i}>
                          <td className="cell-strong">{a.asunto || "-.-"}</td>
                          <td>{a.impacto || "-.-"}</td>
                          <td>{a.responsable || "-.-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="card">
                <div className="card__head">
                  <div className="card__title">
                    <Icon name="trending" className="card__icon" />
                    Proyección 24–72 h
                  </div>
                </div>
                <div className="card__body">
                  <p style={{ lineHeight: 1.6 }}>{c.proyeccion_24_72h || "-.-"}</p>
                </div>
              </div>

              <div>
                <div className="eyebrow" style={{ marginBottom: "var(--sp-3)" }}>
                  Secciones institucionales
                </div>
                {SECCIONES.map((s, i) => (
                  <SeccionInstitucional key={s.key} titulo={s.titulo} icon={s.icon} data={c[s.key]} defaultOpen={i === 0} />
                ))}
              </div>

              <div className="card">
                <div className="card__head">
                  <div className="card__title">
                    <Icon name="file-text" className="card__icon" />
                    Hechos extraídos
                  </div>
                  <span className="hint">{(d.hechos_detalle || []).length}</span>
                </div>
                <div className="table-wrap" style={{ border: 0, borderRadius: 0, maxHeight: 520 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th style={{ width: "34%" }}>Qué</th>
                        <th>Cuándo</th>
                        <th>Dónde</th>
                        <th>Quién</th>
                        <th>Estado</th>
                        <th>Fuente</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(d.hechos_detalle || []).map((h: any) => (
                        <tr key={h.id} title={h.texto_origen || ""}>
                          <td>
                            <div className="cell-strong">{h.evento || "-.-"}</div>
                            {h.impacto && <div className="hint">{h.impacto}</div>}
                          </td>
                          <td className="mono">{h.ocurrido_en || "—"}</td>
                          <td>{h.ubicacion || "—"}</td>
                          <td>{h.responsable || "—"}</td>
                          <td>{h.estado || "—"}</td>
                          <td className="mono hint">{h.fuente || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="stack">
              <div className="card">
                <div className="card__head">
                  <div className="card__title">
                    <Icon name="check-circle" className="card__icon" />
                    Datos clave verificados
                  </div>
                  <span className="hint">{d.calidad}</span>
                </div>
                <div className="card__body">
                  {Object.entries(d.calidad_por_seccion || {}).map(([s, v]) => (
                    <div key={s} className="row row--between">
                      <span>{s}</span>
                      <span className="mono">{String(v)}</span>
                    </div>
                  ))}
                  <ul className="qa-checks mt4">
                    {(d.calidad_detalle || []).map((x: any, i: number) => (
                      <li key={i} className={x.ok ? "is-ok" : "is-bad"}>
                        <span aria-hidden="true">{x.ok ? "✓" : "✗"}</span> {x.dato}
                        <span className="hint"> · {x.seccion}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="card">
                <div className="card__head">
                  <div className="card__title">Cifras no encontradas en las fuentes</div>
                  <span className="hint">{d.exactitud_detalle?.no_encontradas?.length ?? 0}</span>
                </div>
                <div className="card__body">
                  {(d.exactitud_detalle?.no_encontradas || []).length === 0 ? (
                    <p className="muted">Todas las cifras del SITREP aparecen en los documentos.</p>
                  ) : (
                    <>
                      <p className="mono">{d.exactitud_detalle.no_encontradas.join(" · ")}</p>
                      <p className="hint mt2">Revíselas a mano: pueden ser sumas calculadas (totales) o un error del modelo.</p>
                    </>
                  )}
                </div>
              </div>

              <div className="card">
                <div className="card__head">
                  <div className="card__title">
                    <Icon name="alert-circle" className="card__icon" style={{ color: "var(--inc-con)" }} />
                    Contradicciones detectadas
                  </div>
                  <span className="hint">{(d.contradicciones_detalle || []).length}</span>
                </div>
                <div className="card__body">
                  {(d.contradicciones_detalle || []).length === 0 ? (
                    <p className="muted">Sin contradicciones.</p>
                  ) : (
                    <div className="qa-contra">
                      {d.contradicciones_detalle.map((x: any, i: number) => (
                        <div key={i} className="qa-contra__item">
                          <p>{x.descripcion}</p>
                          <div className="hint mono">
                            {(x.hechos_involucrados || [])
                              .map((hid: string) => hechosPorId[hid]?.fuente || hid)
                              .join(" ↔ ")}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="card">
                <div className="card__head">
                  <div className="card__title">Hechos por documento</div>
                </div>
                <div className="card__body">
                  {Object.entries(d.hechos_por_doc || {}).map(([doc, n]) => (
                    <div key={doc} className="row row--between">
                      <span className="mono hint">{doc}</span>
                      <span className={Number(n) === 0 ? "qa-zero" : ""}>{String(n)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
