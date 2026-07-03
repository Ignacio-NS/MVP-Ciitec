import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Icon } from "../components/icons";
import { Badge, Pill, Tag, fmtFecha } from "../components/ui";

const ROLES_APROBACION = ["Comandante", "Administrador del Sistema"];
const SECCIONES: { key: string; titulo: string; icon: string }[] = [
  { key: "personal", titulo: "Personal", icon: "personal" },
  { key: "inteligencia", titulo: "Inteligencia", icon: "inteligencia" },
  { key: "operaciones", titulo: "Operaciones", icon: "operaciones" },
  { key: "logistica", titulo: "Logística", icon: "logistica" },
];

function descargar(blob: Blob, nombre: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  a.click();
  URL.revokeObjectURL(url);
}

function esVacio(v: any): boolean {
  if (v == null) return true;
  if (typeof v === "string") return v.trim() === "" || v.trim() === "-.-";
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") return Object.keys(v).length === 0;
  return false;
}
function esPrimitivo(v: any): boolean {
  return v == null || ["string", "number", "boolean"].includes(typeof v);
}
function humaniza(k: string): string {
  const s = k.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function valor(v: any): string {
  if (typeof v === "boolean") return v ? "Sí" : "No";
  return String(v);
}
function impactoStyle(imp?: string): React.CSSProperties {
  const s = (imp || "").toLowerCase();
  if (s.includes("alto")) return { color: "var(--sec)", background: "var(--sec-bg)" };
  if (s.includes("medio")) return { color: "var(--res)", background: "var(--res-bg)" };
  if (s.includes("bajo")) return { color: "var(--pub)", background: "var(--pub-bg)" };
  return { color: "var(--st-borrador)", background: "var(--st-borrador-bg)" };
}

// Renderiza una sección institucional (dict libre del LLM) de forma genérica:
// primitivas como métricas de tablero, listas/objetos como sub-bloques.
function SeccionInstitucional({
  titulo,
  icon,
  data,
  defaultOpen,
}: {
  titulo: string;
  icon: string;
  data: any;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  const entries: [string, any][] = data && typeof data === "object" ? Object.entries(data) : [];
  const prim = entries.filter(([, v]) => esPrimitivo(v) || esVacio(v));
  const comp = entries.filter(([, v]) => !esPrimitivo(v) && !esVacio(v));

  return (
    <div className={"collapse" + (open ? " is-open" : "")}>
      <div className="collapse__head" onClick={() => setOpen((o) => !o)}>
        <div className="collapse__title">
          <Icon name={icon} />
          {titulo}
        </div>
        <Icon name="chevron" className="collapse__chev" />
      </div>
      <div className="collapse__body">
        {entries.length === 0 && <p className="muted">-.-</p>}
        {prim.length > 0 && (
          <div className="metrics">
            {prim.map(([k, v]) => {
              const vacio = esVacio(v);
              return (
                <div className="metric" key={k}>
                  <div className="metric__k">{humaniza(k)}</div>
                  <div className={"metric__v" + (vacio ? " is-empty" : "")}>
                    {vacio ? "-.-" : valor(v)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {comp.map(([k, v]) => (
          <div key={k} className="mt4">
            <div className="eyebrow">{humaniza(k)}</div>
            {Array.isArray(v) ? (
              <ul className="bullets mt2">
                {v.map((item, i) => (
                  <li key={i}>
                    {esPrimitivo(item)
                      ? valor(item)
                      : Object.values(item)
                          .filter((x) => esPrimitivo(x) && !esVacio(x))
                          .map(valor)
                          .join(" · ")}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="metrics mt2">
                {Object.entries(v).map(([sk, sv]) => (
                  <div className="metric" key={sk}>
                    <div className="metric__k">{humaniza(sk)}</div>
                    <div className={"metric__v" + (esVacio(sv) ? " is-empty" : "")}>
                      {esVacio(sv) ? "-.-" : esPrimitivo(sv) ? valor(sv) : JSON.stringify(sv)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================ MODO EDICIÓN ============================
// Editores genéricos que preservan la estructura del JSON `contenido`. Al
// guardar, el backend crea SIEMPRE una versión nueva (append-only, RF-007):
// editar v1 produce v2, editar v2 produce v3, etc.

function EdTexto({
  value,
  onChange,
  area,
}: {
  value: any;
  onChange: (v: string) => void;
  area?: boolean;
}) {
  const v = value == null ? "" : String(value);
  if (area)
    return <textarea className="input" rows={2} value={v} onChange={(e) => onChange(e.target.value)} />;
  return <input className="input" value={v} onChange={(e) => onChange(e.target.value)} />;
}

function EdLista({
  items,
  onChange,
  area,
}: {
  items: any[];
  onChange: (v: any[]) => void;
  area?: boolean;
}) {
  return (
    <div className="stack" style={{ gap: 8 }}>
      {items.map((item, i) => (
        <div className="row gap2" key={i} style={{ alignItems: "flex-start" }}>
          <div className="grow">
            <EdTexto
              area={area}
              value={item}
              onChange={(nv) => onChange(items.map((x, j) => (j === i ? nv : x)))}
            />
          </div>
          <button
            className="btn btn--ghost btn--sm"
            title="Eliminar"
            onClick={() => onChange(items.filter((_, j) => j !== i))}
          >
            ✕
          </button>
        </div>
      ))}
      <div>
        <button className="btn btn--secondary btn--sm" onClick={() => onChange([...items, ""])}>
          + Añadir
        </button>
      </div>
    </div>
  );
}

function EdTabla({
  rows,
  onChange,
  columnas,
}: {
  rows: any[];
  onChange: (v: any[]) => void;
  columnas?: string[];
}) {
  const cols =
    columnas ||
    Array.from(new Set(rows.flatMap((r) => (r && typeof r === "object" ? Object.keys(r) : []))));
  if (cols.length === 0) return <p className="muted">-.-</p>;
  return (
    <div>
      <div className="table-wrap">
        <table className="table ed-table">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>{humaniza(c)}</th>
              ))}
              <th style={{ width: 34 }} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c}>
                    <EdTexto
                      value={row?.[c]}
                      onChange={(nv) =>
                        onChange(rows.map((x, j) => (j === i ? { ...(x || {}), [c]: nv } : x)))
                      }
                    />
                  </td>
                ))}
                <td>
                  <button
                    className="btn btn--ghost btn--sm"
                    title="Eliminar fila"
                    onClick={() => onChange(rows.filter((_, j) => j !== i))}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button
        className="btn btn--secondary btn--sm mt2"
        onClick={() => onChange([...rows, Object.fromEntries(cols.map((c) => [c, ""]))])}
      >
        + Fila
      </button>
    </div>
  );
}

// Editor recursivo de un valor arbitrario del JSON (secciones institucionales).
function EdValor({ v, onChange }: { v: any; onChange: (nv: any) => void }) {
  if (Array.isArray(v)) {
    if (v.length > 0 && v.every((x) => !esPrimitivo(x))) return <EdTabla rows={v} onChange={onChange} />;
    return <EdLista items={v} onChange={onChange} />;
  }
  if (v !== null && typeof v === "object") {
    const entries = Object.entries(v);
    const prim = entries.filter(([, sv]) => esPrimitivo(sv));
    const comp = entries.filter(([, sv]) => !esPrimitivo(sv));
    return (
      <div className="stack" style={{ gap: "var(--sp-4)" }}>
        {prim.length > 0 && (
          <div className="ed-grid">
            {prim.map(([k, sv]) => (
              <div key={k}>
                <div className="metric__k" style={{ marginBottom: 4 }}>
                  {humaniza(k)}
                </div>
                <EdTexto value={sv} onChange={(nv) => onChange({ ...v, [k]: nv })} />
              </div>
            ))}
          </div>
        )}
        {comp.map(([k, sv]) => (
          <div key={k}>
            <div className="eyebrow" style={{ marginBottom: 6 }}>
              {humaniza(k)}
            </div>
            <EdValor v={sv} onChange={(nv) => onChange({ ...v, [k]: nv })} />
          </div>
        ))}
      </div>
    );
  }
  return <EdTexto value={v} onChange={onChange} />;
}

function EdSeccion({
  titulo,
  icon,
  data,
  onChange,
  defaultOpen,
}: {
  titulo: string;
  icon: string;
  data: any;
  onChange: (nv: any) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div className={"collapse" + (open ? " is-open" : "")}>
      <div className="collapse__head" onClick={() => setOpen((o) => !o)}>
        <div className="collapse__title">
          <Icon name={icon} />
          {titulo}
        </div>
        <Icon name="chevron" className="collapse__chev" />
      </div>
      <div className="collapse__body">
        {data == null ? (
          <p className="muted">Sin datos en esta sección.</p>
        ) : (
          <EdValor v={data} onChange={onChange} />
        )}
      </div>
    </div>
  );
}

// Editor completo del reporte: refleja las mismas secciones de la vista de lectura.
function EditorReporte({
  draft,
  setDraft,
  proximaVersion,
  baseVersion,
  guardando,
  onGuardar,
  onCancelar,
}: {
  draft: any;
  setDraft: (d: any) => void;
  proximaVersion: number;
  baseVersion: number | null;
  guardando: boolean;
  onGuardar: (exportarPdf: boolean) => void;
  onCancelar: () => void;
}) {
  const sit = draft.situacion || {};
  return (
    <div className="stack">
      <div className="card ed-bar">
        <div className="card__body row row--between gap2 row--wrap">
          <div>
            <div style={{ fontWeight: 600 }}>
              Editando reporte{baseVersion != null ? ` (desde v${baseVersion})` : ""}
            </div>
            <div className="hint">
              Al guardar se creará la versión v{proximaVersion}; las anteriores se conservan intactas.
            </div>
          </div>
          <div className="btn-group">
            <button className="btn btn--ghost" onClick={onCancelar} disabled={guardando}>
              Cancelar
            </button>
            <button className="btn btn--secondary" onClick={() => onGuardar(false)} disabled={guardando}>
              Guardar v{proximaVersion}
            </button>
            <button className="btn btn--primary" onClick={() => onGuardar(true)} disabled={guardando}>
              <Icon name="file-text" />
              {guardando ? "Guardando…" : `Guardar y exportar PDF (v${proximaVersion})`}
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <div className="card__title">
            <Icon name="clipboard" className="card__icon" />
            Resumen ejecutivo
          </div>
        </div>
        <div className="card__body">
          <EdLista
            area
            items={draft.resumen_ejecutivo || []}
            onChange={(nv) => setDraft({ ...draft, resumen_ejecutivo: nv })}
          />
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <div className="card__title">Situación</div>
        </div>
        <div className="card__body stack" style={{ gap: "var(--sp-4)" }}>
          <div>
            <div className="eyebrow" style={{ marginBottom: 6 }}>
              Resumen
            </div>
            <EdTexto
              area
              value={sit.resumen}
              onChange={(nv) => setDraft({ ...draft, situacion: { ...sit, resumen: nv } })}
            />
          </div>
          <div>
            <div className="eyebrow" style={{ marginBottom: 6 }}>
              Aspectos relevantes
            </div>
            <EdLista
              area
              items={sit.aspectos || []}
              onChange={(nv) => setDraft({ ...draft, situacion: { ...sit, aspectos: nv } })}
            />
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <div className="card__title">
            <Icon name="alert-triangle" className="card__icon" style={{ color: "var(--res)" }} />
            Asuntos críticos
          </div>
        </div>
        <div className="card__body">
          <EdTabla
            rows={draft.asuntos_criticos || []}
            columnas={["asunto", "impacto", "responsable"]}
            onChange={(nv) => setDraft({ ...draft, asuntos_criticos: nv })}
          />
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
          <EdTexto
            area
            value={draft.proyeccion_24_72h}
            onChange={(nv) => setDraft({ ...draft, proyeccion_24_72h: nv })}
          />
        </div>
      </div>

      <div>
        <div className="eyebrow" style={{ marginBottom: "var(--sp-3)" }}>
          Secciones institucionales
        </div>
        {SECCIONES.map((s, i) => (
          <EdSeccion
            key={s.key}
            titulo={s.titulo}
            icon={s.icon}
            data={draft[s.key]}
            onChange={(nv) => setDraft({ ...draft, [s.key]: nv })}
            defaultOpen={i === 0}
          />
        ))}
      </div>
    </div>
  );
}

const INC_LABEL: Record<string, string> = {
  DUPLICADO: "Duplicados",
  CONTRADICCION: "Contradicciones",
  DESACTUALIZADO: "Desactualizados",
  INCOMPLETO: "Incompletos",
};
const INC_ORDEN = ["CONTRADICCION", "DUPLICADO", "DESACTUALIZADO", "INCOMPLETO"];

// Chip clickeable con el archivo origen de un hecho → navega a la vista de fuente
// resaltando la cita (RF-006).
function FuenteChip({ hecho, onAbrir }: { hecho: any; onAbrir: (h: any) => void }) {
  if (!hecho?.fuente_id) return null;
  return (
    <button className="src-chip" title={hecho.evento || ""} onClick={() => onAbrir(hecho)}>
      <Icon name="file" />
      {hecho.fuente_nombre || hecho.fuente_id.slice(0, 8)}
    </button>
  );
}

// Un grupo colapsable de inconsistencias del mismo tipo, con archivos origen.
function IncGrupo({
  tipo,
  items,
  onAbrir,
  defaultOpen,
}: {
  tipo: string;
  items: any[];
  onAbrir: (h: any) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div className={"collapse" + (open ? " is-open" : "")}>
      <div className="collapse__head" onClick={() => setOpen((o) => !o)}>
        <div className="collapse__title">
          <Tag tipo={tipo} />
          {INC_LABEL[tipo] || tipo}
          <span className="hint" style={{ marginLeft: 6 }}>{items.length}</span>
        </div>
        <Icon name="chevron" className="collapse__chev" />
      </div>
      <div className="collapse__body">
        <div className="inc-list">
          {items.map((i) => (
            <div className="inc-item" key={i.id}>
              <div className="inc-item__body">
                <div className="inc-item__desc">{i.descripcion}</div>
                {i.hechos?.length > 0 && (
                  <div className="inc-item__src">
                    {i.hechos.map((h: any, k: number) => (
                      <span key={h.id} className="row gap1" style={{ alignItems: "center" }}>
                        {k > 0 && <span className="muted">↔</span>}
                        <FuenteChip hecho={h} onAbrir={onAbrir} />
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function Briefing() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [b, setB] = useState<any>(null);
  const [versiones, setVersiones] = useState<any[]>([]);
  const [inc, setInc] = useState<any[]>([]);
  const [trazas, setTrazas] = useState<any[]>([]);
  const [at, setAt] = useState("");
  const [reconstruido, setReconstruido] = useState<any>(null);
  const [lit, setLit] = useState<string | null>(null);
  const [diff, setDiff] = useState<string[] | null>(null);
  const [verDiff, setVerDiff] = useState(false);
  // Versión seleccionada del historial (null = versión activa) y modo edición.
  const [verSel, setVerSel] = useState<{ numero: number; version_id: string; contenido: any } | null>(null);
  const [editando, setEditando] = useState(false);
  const [draft, setDraft] = useState<any>(null);
  const [guardando, setGuardando] = useState(false);

  const puedeAprobar = user?.roles?.some((r) => ROLES_APROBACION.includes(r));

  async function recargar() {
    const [det, vs, ins, trz] = await Promise.all([
      api.getBriefing(id),
      api.getVersiones(id),
      api.getInconsistencias(id),
      api.getTrazabilidad(id),
    ]);
    setB(det);
    setVersiones(vs.versiones || []);
    setInc(ins.inconsistencias || []);
    setTrazas(trz.trazas || []);
  }
  useEffect(() => {
    recargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Exporta la versión mostrada; el archivo queda trazado con su número (Titulo_v2.pdf).
  async function exportar(formato: string) {
    const ext = formato === "PDF" ? "pdf" : formato === "WORD" ? "docx" : "txt";
    const numero = verSel ? verSel.numero : b.version;
    const blob = await api.exportar(id, formato, verSel?.version_id ?? null);
    descargar(blob, `${b.titulo.replace(/ /g, "_")}_v${numero ?? 1}.${ext}`);
  }

  // Abre una versión del historial para verla (y poder editarla desde ahí).
  async function abrirVersion(numero: number) {
    if (editando) return; // no cambiar de versión a mitad de una edición
    if (b?.version != null && numero === b.version) {
      setVerSel(null);
      return;
    }
    const r = await api.getVersion(id, numero);
    setVerSel({ numero: r.numero_version, version_id: r.id, contenido: r.contenido });
  }

  function empezarEdicion(contenido: any) {
    setDraft(JSON.parse(JSON.stringify(contenido)));
    setEditando(true);
  }

  // Guarda el borrador como versión nueva (v1 -> v2 -> v3, RF-007) y opcionalmente
  // descarga el PDF de esa versión recién creada.
  async function guardarEdicion(exportarPdf: boolean) {
    setGuardando(true);
    try {
      const base = verSel ? verSel.numero : b.version;
      const r = await api.editarVersion(id, draft, base);
      if (exportarPdf) {
        const blob = await api.exportar(id, "PDF", r.version_id);
        descargar(blob, `${b.titulo.replace(/ /g, "_")}_v${r.numero_version}.pdf`);
      }
      setEditando(false);
      setDraft(null);
      setVerSel(null);
      await recargar();
    } catch (e: any) {
      alert("No se pudo guardar la versión: " + (e?.message || e));
    } finally {
      setGuardando(false);
    }
  }
  async function reconstruir() {
    if (!at) return;
    setReconstruido(await api.reconstruir(id, new Date(at).toISOString()));
  }
  async function aprobar(versionId: string) {
    await api.aprobar(versionId);
    await recargar();
  }
  async function toggleDiff() {
    if (verDiff) {
      setVerDiff(false);
      return;
    }
    if (versiones.length >= 2) {
      const a = versiones[versiones.length - 2].numero_version;
      const bb = versiones[versiones.length - 1].numero_version;
      try {
        const r = await api.getDiff(id, a, bb);
        setDiff(r.diff || []);
      } catch {
        setDiff([]);
      }
    }
    setVerDiff(true);
  }

  if (!b) return <div className="page">Cargando…</div>;

  // Contenido mostrado: la versión seleccionada del historial o la activa.
  const c = verSel ? verSel.contenido : b.contenido;
  const numeroMostrado = verSel ? verSel.numero : b.version;
  const proximaVersion =
    versiones.length > 0 ? versiones[versiones.length - 1].numero_version + 1 : 1;

  // Navega a la fuente origen del hecho resaltando su cita textual (RF-006).
  function abrirFuente(h: any) {
    if (h?.fuente_id) navigate(`/fuentes/${h.fuente_id}`, { state: { cita: h.texto_origen || "" } });
  }

  // Correlación bullet ↔ traza por su bullet_key (p.ej. "resumen_ejecutivo[0]"), no por
  // orden de inserción → no se desalinea bullet↔hecho (RF-006).
  const trazaPorKey: Record<string, any[]> = {};
  trazas.forEach((t: any) => {
    (trazaPorKey[t.bullet_key] ||= []).push(t.hecho || { id: t.hecho_id });
  });
  const grupos = Object.keys(trazaPorKey).map((k) => ({ key: k, hechos: trazaPorKey[k] }));
  const resumen: string[] = c?.resumen_ejecutivo || [];
  const aspectos: string[] = c?.situacion?.aspectos || [];
  const asuntos: any[] = c?.asuntos_criticos || [];

  const ultimaDiff =
    versiones.length >= 2
      ? `v${versiones[versiones.length - 2].numero_version}→v${versiones[versiones.length - 1].numero_version}`
      : "";

  return (
    <div className="page">
      <div className="row gap2" style={{ marginBottom: "var(--sp-4)" }}>
        <Link className="btn btn--ghost btn--sm" to="/briefings">
          <Icon name="arrow-left" />
          SITREP
        </Link>
        <span className="muted">/</span>
        <span className="muted mono" style={{ fontSize: "var(--tx-sm)" }}>
          {id.slice(0, 8)}
        </span>
      </div>

      <div className="page-head">
        <div>
          <div className="row gap2 row--wrap" style={{ marginBottom: 8 }}>
            <Badge nivel={b.nivel_clasificacion} lg />
            <Pill estado={b.estado} />
            <span className="muted" style={{ fontSize: "var(--tx-sm)" }}>
              Versión activa <strong className="mono">{b.version != null ? `v${b.version}` : "—"}</strong>
            </span>
            {verSel && (
              <span className="pill" style={{ color: "var(--res)", background: "var(--res-bg)" }}>
                <span className="pill__dot" />
                Viendo v{verSel.numero} (histórica)
              </span>
            )}
          </div>
          <h1 className="page-title">{b.titulo}</h1>
          <p className="page-sub">Generado el {fmtFecha(b.creado_en)}</p>
        </div>
        {!editando && (
          <div className="btn-group">
            {verSel && (
              <button className="btn btn--ghost" onClick={() => setVerSel(null)}>
                Volver a v{b.version}
              </button>
            )}
            {c && (
              <button className="btn btn--primary" onClick={() => empezarEdicion(c)}>
                <Icon name="edit" />
                Editar reporte
              </button>
            )}
            <button className="btn btn--secondary" onClick={() => exportar("PDF")}>
              <Icon name="file-text" />
              PDF
            </button>
            <button className="btn btn--secondary" onClick={() => exportar("WORD")}>
              <Icon name="file" />
              Word
            </button>
            <button className="btn btn--secondary" onClick={() => exportar("TEXTO")}>
              <Icon name="text-lines" />
              Texto
            </button>
          </div>
        )}
      </div>

      {editando && draft ? (
        <EditorReporte
          draft={draft}
          setDraft={setDraft}
          proximaVersion={proximaVersion}
          baseVersion={numeroMostrado ?? null}
          guardando={guardando}
          onGuardar={guardarEdicion}
          onCancelar={() => {
            setEditando(false);
            setDraft(null);
          }}
        />
      ) : null}

      {editando ? null : !c ? (
        <div className="card">
          <div className="card__body muted">
            El SITREP aún no tiene una versión con contenido (estado {b.estado}).
          </div>
        </div>
      ) : (
        <div className="detail-grid">
          {/* ---- columna principal ---- */}
          <div className="stack">
            <div className="card">
              <div className="card__head">
                <div className="card__title">
                  <Icon name="clipboard" className="card__icon" />
                  Resumen ejecutivo
                </div>
                <span className="hint mono">
                  {trazas.length} vínculos bullet → hecho → fuente
                </span>
              </div>
              <div className="card__body">
                {resumen.length === 0 ? (
                  <p className="muted">-.-</p>
                ) : (
                  <ul className="bullets">
                    {resumen.map((t, i) => {
                      const key = `resumen_ejecutivo[${i}]`;
                      const hecho = trazaPorKey[key]?.[0];
                      return (
                        <li key={i}>
                          <div
                            className={"trace-bullet" + (lit === key ? " is-lit" : "")}
                            onMouseEnter={() => setLit(key)}
                            onMouseLeave={() => setLit(null)}
                          >
                            <span>{t}</span>
                            {hecho?.fuente_id && (
                              <button
                                className="trace-id mono"
                                title={hecho.fuente_nombre || ""}
                                onClick={() => abrirFuente(hecho)}
                              >
                                {hecho.fuente_nombre
                                  ? hecho.fuente_nombre.slice(0, 18)
                                  : String(hecho.id).slice(0, 8)}
                              </button>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card__head">
                <div className="card__title">Situación</div>
              </div>
              <div className="card__body">
                <p style={{ fontSize: "var(--tx-md)", lineHeight: 1.6, marginBottom: "var(--sp-4)" }}>
                  {c.situacion?.resumen || "-.-"}
                </p>
                {aspectos.length > 0 && (
                  <>
                    <div className="eyebrow">Aspectos relevantes</div>
                    <ul className="bullets">
                      {aspectos.map((a, i) => (
                        <li key={i}>{a}</li>
                      ))}
                    </ul>
                  </>
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
                      <th style={{ width: "42%" }}>Asunto</th>
                      <th>Impacto</th>
                      <th>Responsable</th>
                    </tr>
                  </thead>
                  <tbody>
                    {asuntos.length === 0 && (
                      <tr>
                        <td colSpan={3} className="muted">
                          -.-
                        </td>
                      </tr>
                    )}
                    {asuntos.map((a, i) => (
                      <tr key={i}>
                        <td className="cell-strong">{a.asunto || "-.-"}</td>
                        <td>
                          <span className="pill" style={impactoStyle(a.impacto)}>
                            <span className="pill__dot" />
                            {a.impacto || "-.-"}
                          </span>
                        </td>
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
                <p style={{ fontSize: "var(--tx-md)", lineHeight: 1.6 }}>
                  {c.proyeccion_24_72h || "-.-"}
                </p>
              </div>
            </div>

            <div>
              <div className="eyebrow" style={{ marginBottom: "var(--sp-3)" }}>
                Secciones institucionales
              </div>
              {SECCIONES.map((s, i) => (
                <SeccionInstitucional
                  key={s.key}
                  titulo={s.titulo}
                  icon={s.icon}
                  data={c[s.key]}
                  defaultOpen={i === 0}
                />
              ))}
            </div>

            <div className="card">
              <div className="card__head">
                <div className="card__title">
                  <Icon name="alert-circle" className="card__icon" style={{ color: "var(--inc-con)" }} />
                  Inconsistencias detectadas
                </div>
                <span className="hint">{inc.length}</span>
              </div>
              <div className="card__body">
                {inc.length === 0 ? (
                  <p className="muted">Sin inconsistencias.</p>
                ) : (
                  <div className="inc-scroll">
                    {INC_ORDEN.filter((tipo) => inc.some((i) => i.tipo === tipo)).map((tipo, idx) => (
                      <IncGrupo
                        key={tipo}
                        tipo={tipo}
                        items={inc.filter((i) => i.tipo === tipo)}
                        onAbrir={abrirFuente}
                        defaultOpen={idx === 0}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ---- columna lateral ---- */}
          <div className="stack">
            <div className="card trace-panel">
              <div className="card__head">
                <div className="card__title">
                  <Icon name="link" className="card__icon" />
                  Trazabilidad
                </div>
              </div>
              <div className="card__body trace-panel__body">
                <p className="hint" style={{ marginBottom: "var(--sp-3)" }}>
                  Pase el cursor por un bullet para resaltarlo; haga clic en un vínculo para
                  abrir el documento origen con la cita resaltada.
                </p>
                {grupos.length === 0 ? (
                  <p className="muted">Sin vínculos de trazabilidad.</p>
                ) : (
                  <div className="stack" style={{ gap: 8 }}>
                    {grupos.map((g) => {
                      const h0 = g.hechos[0];
                      return (
                        <div
                          key={g.key}
                          className={"trace-link" + (lit === g.key ? " is-lit" : "")}
                          onMouseEnter={() => setLit(g.key)}
                          onMouseLeave={() => setLit(null)}
                          onClick={() => abrirFuente(h0)}
                          style={{ cursor: h0?.fuente_id ? "pointer" : "default" }}
                        >
                          <div className="trace-link__h">
                            <span className="badge badge--res" style={{ height: 18 }}>
                              {String(g.key).toUpperCase()}
                            </span>
                          </div>
                          {h0?.evento && <div className="trace-link__hecho">{h0.evento}</div>}
                          <div className="trace-link__src">
                            <Icon name="file" />
                            {h0?.fuente_nombre || "—"}
                            {g.hechos.length > 1 && (
                              <span className="muted">+{g.hechos.length - 1}</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card__head">
                <div className="card__title">Versiones</div>
                {versiones.length >= 2 && (
                  <button className="btn btn--ghost btn--sm" onClick={toggleDiff}>
                    {verDiff ? "Ocultar diff" : `Ver diff ${ultimaDiff}`}
                  </button>
                )}
              </div>
              <div className="card__body">
                <div className="stack" style={{ gap: "var(--sp-4)" }}>
                  {versiones.map((v) => (
                    <div
                      className={"ver-row" + (numeroMostrado === v.numero_version ? " is-current" : "")}
                      key={v.id}
                      onClick={() => abrirVersion(v.numero_version)}
                      title={`Ver v${v.numero_version}`}
                      style={{ cursor: "pointer" }}
                    >
                      <span className={"ver-dot" + (v.aprobado_en ? " is-appr" : "")} />
                      <div className="grow">
                        <div className="row row--between gap2">
                          <span className="cell-strong mono">v{v.numero_version}</span>
                          {v.aprobado_en ? (
                            <span className="pill pill--aprobado">
                              <span className="pill__dot" />
                              Aprobada
                            </span>
                          ) : puedeAprobar ? (
                            <button
                              className="btn btn--primary btn--sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                aprobar(v.id);
                              }}
                            >
                              Aprobar
                            </button>
                          ) : (
                            <span className="hint">Sin aprobar</span>
                          )}
                        </div>
                        {v.comentario_cambio && (
                          <div className="cell-sub" style={{ marginTop: 3 }}>
                            {v.comentario_cambio}
                          </div>
                        )}
                        <div className="cell-sub mono" style={{ marginTop: 2, fontSize: 11 }}>
                          {v.aprobado_en ? "Aprobada " + fmtFecha(v.aprobado_en) : "Creada " + fmtFecha(v.creado_en)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {verDiff && (
                  <div className="mt4">
                    {!diff || diff.length === 0 ? (
                      <p className="hint">Sin diferencias para mostrar.</p>
                    ) : (
                      <div className="diff">
                        {diff.map((ln, i) => {
                          const add = ln.startsWith("+") && !ln.startsWith("+++");
                          const del = ln.startsWith("-") && !ln.startsWith("---");
                          const cls = add ? "diff__line--add" : del ? "diff__line--del" : "diff__line--ctx";
                          const sign = add ? "+" : del ? "−" : "~";
                          return (
                            <div className={"diff__line " + cls} key={i}>
                              <span className="diff__sign">{sign}</span>
                              {ln.replace(/^[+\- ]/, "")}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card__head">
                <div className="card__title">
                  <Icon name="clock" className="card__icon" />
                  Reconstrucción point-in-time
                </div>
              </div>
              <div className="card__body">
                <label className="label" style={{ marginBottom: 6, display: "block" }}>
                  Estado del SITREP a una fecha/hora
                </label>
                <input
                  className="input"
                  type="datetime-local"
                  value={at}
                  onChange={(e) => setAt(e.target.value)}
                />
                <button className="btn btn--secondary btn--block mt2" onClick={reconstruir} disabled={!at}>
                  Reconstruir estado
                </button>
                {reconstruido && (
                  <div className="pit-result">
                    <Icon name="clock" style={{ color: "var(--accent)" }} />
                    <div>
                      <div style={{ fontWeight: 600 }}>
                        Estado del SITREP a esa hora — v{reconstruido.version}
                      </div>
                      <div className="hint">
                        Versión vigente el {new Date(at).toLocaleString("es-CL")}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
