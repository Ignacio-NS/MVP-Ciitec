import { useEffect, useState } from "react";
import { api } from "../api";
import { Icon } from "./icons";

// Hojas adicionales del reporte: el usuario agrega páginas nuevas al PDF, elige el
// formato de cada una (bloques de texto, viñetas, tabla, KPIs, gráfico o imagen), la
// posición, y puede pedir a la IA que la complete con los hechos del briefing.

const SECCIONES_HOJA = ["PERSONAL", "INTELIGENCIA", "OPERACIONES", "LOGÍSTICA", "INFORMACIÓN ADICIONAL"];
const POSICIONES: { v: string; l: string }[] = [
  { v: "", l: "Al final del reporte" },
  { v: "0", l: "Después de la Portada" },
  { v: "1", l: "Después de Personal" },
  { v: "2", l: "Después de Inteligencia" },
  { v: "3", l: "Después de Operaciones (1/2)" },
  { v: "4", l: "Después de Operaciones (2/2)" },
  { v: "5", l: "Después de Logística" },
];
const TIPOS: { v: string; l: string }[] = [
  { v: "texto", l: "Texto" },
  { v: "vinetas", l: "Viñetas" },
  { v: "tabla", l: "Tabla" },
  { v: "kpis", l: "Indicadores (KPI)" },
  { v: "grafico", l: "Gráfico" },
  { v: "imagen", l: "Imagen" },
];

function bloqueVacio(tipo: string): any {
  switch (tipo) {
    case "vinetas":
      return { tipo, titulo: "", items: [""] };
    case "tabla":
      return { tipo, titulo: "", columnas: ["Columna 1", "Columna 2"], filas: [["", ""]] };
    case "kpis":
      return { tipo, titulo: "", items: [{ etiqueta: "", valor: "" }] };
    case "grafico":
      return { tipo, titulo: "", estilo: "barras", categorias: [""], valores: [""] };
    case "imagen":
      return { tipo, titulo: "", objeto: "", pie: "" };
    default:
      return { tipo: "texto", titulo: "", texto: "" };
  }
}

function hojaNueva(): any {
  return {
    id: "h_" + Math.random().toString(36).slice(2, 10),
    seccion: "INFORMACIÓN ADICIONAL",
    titulo: "",
    despues_de: null,
    instrucciones_ia: "",
    bloques: [bloqueVacio("texto")],
  };
}

function mover<T>(arr: T[], i: number, d: number): T[] {
  const j = i + d;
  if (j < 0 || j >= arr.length) return arr;
  const c = [...arr];
  [c[i], c[j]] = [c[j], c[i]];
  return c;
}

function tieneContenido(b: any): boolean {
  const lleno = (x: any) => String(x ?? "").trim() !== "";
  switch (b.tipo) {
    case "texto":
      return lleno(b.texto);
    case "vinetas":
      return (b.items || []).some(lleno);
    case "tabla":
      return (b.filas || []).some((f: any[]) => f.some(lleno));
    case "kpis":
      return (b.items || []).some((i: any) => lleno(i.etiqueta) || lleno(i.valor));
    case "grafico":
      return (b.categorias || []).some(lleno);
    default:
      return false;
  }
}

// Imagen guardada en MinIO, servida por la API con el JWT (no se puede usar <img src> directo).
function ImagenHoja({ briefingId, objeto }: { briefingId: string; objeto: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revocar: string | null = null;
    let vivo = true;
    setUrl(null);
    if (!objeto) return;
    api
      .imagenHoja(briefingId, objeto)
      .then((blob: Blob) => {
        if (!vivo) return;
        revocar = URL.createObjectURL(blob);
        setUrl(revocar);
      })
      .catch(() => {});
    return () => {
      vivo = false;
      if (revocar) URL.revokeObjectURL(revocar);
    };
  }, [briefingId, objeto]);
  if (!objeto) return null;
  return url ? (
    <img src={url} alt="" style={{ maxWidth: "100%", maxHeight: 320, borderRadius: 4 }} />
  ) : (
    <p className="muted">Cargando imagen…</p>
  );
}

function Txt({
  value,
  onChange,
  area,
  ph,
}: {
  value: any;
  onChange: (v: string) => void;
  area?: boolean;
  ph?: string;
}) {
  const v = value == null ? "" : String(value);
  return area ? (
    <textarea className="input" rows={3} placeholder={ph} value={v} onChange={(e) => onChange(e.target.value)} />
  ) : (
    <input className="input" placeholder={ph} value={v} onChange={(e) => onChange(e.target.value)} />
  );
}

function Mini({ children, onClick, title }: { children: any; onClick: () => void; title: string }) {
  return (
    <button type="button" className="btn btn--ghost btn--sm" title={title} onClick={onClick}>
      {children}
    </button>
  );
}

// ---------------------------- editor de un bloque ----------------------------
function EdBloque({
  b,
  onChange,
  briefingId,
}: {
  b: any;
  onChange: (nb: any) => void;
  briefingId: string;
}) {
  const [subiendo, setSubiendo] = useState(false);
  const set = (patch: any) => onChange({ ...b, ...patch });

  async function subir(file: File | undefined) {
    if (!file) return;
    setSubiendo(true);
    try {
      const r = await api.subirImagenHoja(briefingId, file);
      set({ objeto: r.objeto });
    } catch (e: any) {
      alert("No se pudo subir la imagen: " + (e?.message || e));
    } finally {
      setSubiendo(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 8 }}>
      <Txt value={b.titulo} onChange={(v) => set({ titulo: v })} ph="Título del bloque (opcional, se muestra como banda)" />

      {b.tipo === "texto" && (
        <Txt area value={b.texto} onChange={(v) => set({ texto: v })} ph="Texto (un párrafo por línea)" />
      )}

      {b.tipo === "vinetas" && (
        <div className="stack" style={{ gap: 6 }}>
          {(b.items || []).map((it: string, i: number) => (
            <div className="row gap2" key={i}>
              <div className="grow">
                <Txt value={it} onChange={(v) => set({ items: b.items.map((x: string, j: number) => (j === i ? v : x)) })} />
              </div>
              <Mini title="Eliminar" onClick={() => set({ items: b.items.filter((_: any, j: number) => j !== i) })}>
                ✕
              </Mini>
            </div>
          ))}
          <div>
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => set({ items: [...(b.items || []), ""] })}>
              + Viñeta
            </button>
          </div>
        </div>
      )}

      {b.tipo === "tabla" && (
        <div>
          <div className="table-wrap">
            <table className="table ed-table">
              <thead>
                <tr>
                  {(b.columnas || []).map((c: string, ci: number) => (
                    <th key={ci}>
                      <div className="row gap2">
                        <Txt
                          value={c}
                          onChange={(v) => set({ columnas: b.columnas.map((x: string, j: number) => (j === ci ? v : x)) })}
                        />
                        <Mini
                          title="Quitar columna"
                          onClick={() =>
                            set({
                              columnas: b.columnas.filter((_: any, j: number) => j !== ci),
                              filas: (b.filas || []).map((f: string[]) => f.filter((_, j) => j !== ci)),
                            })
                          }
                        >
                          ✕
                        </Mini>
                      </div>
                    </th>
                  ))}
                  <th style={{ width: 34 }} />
                </tr>
              </thead>
              <tbody>
                {(b.filas || []).map((f: string[], ri: number) => (
                  <tr key={ri}>
                    {(b.columnas || []).map((_: any, ci: number) => (
                      <td key={ci}>
                        <Txt
                          value={f[ci]}
                          onChange={(v) =>
                            set({
                              filas: b.filas.map((row: string[], rj: number) => {
                                if (rj !== ri) return row;
                                const nr = [...row];
                                while (nr.length < b.columnas.length) nr.push("");
                                nr[ci] = v;
                                return nr;
                              }),
                            })
                          }
                        />
                      </td>
                    ))}
                    <td>
                      <Mini title="Eliminar fila" onClick={() => set({ filas: b.filas.filter((_: any, j: number) => j !== ri) })}>
                        ✕
                      </Mini>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row gap2 mt2">
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => set({ filas: [...(b.filas || []), (b.columnas || []).map(() => "")] })}
            >
              + Fila
            </button>
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() =>
                set({
                  columnas: [...(b.columnas || []), `Columna ${(b.columnas || []).length + 1}`],
                  filas: (b.filas || []).map((f: string[]) => [...f, ""]),
                })
              }
            >
              + Columna
            </button>
          </div>
        </div>
      )}

      {b.tipo === "kpis" && (
        <div className="stack" style={{ gap: 6 }}>
          {(b.items || []).map((it: any, i: number) => (
            <div className="row gap2" key={i}>
              <div className="grow">
                <Txt
                  value={it.etiqueta}
                  ph="Etiqueta (ej. Fuerza en terreno)"
                  onChange={(v) => set({ items: b.items.map((x: any, j: number) => (j === i ? { ...x, etiqueta: v } : x)) })}
                />
              </div>
              <div className="grow">
                <Txt
                  value={it.valor}
                  ph="Valor (ej. 1.234)"
                  onChange={(v) => set({ items: b.items.map((x: any, j: number) => (j === i ? { ...x, valor: v } : x)) })}
                />
              </div>
              <Mini title="Eliminar" onClick={() => set({ items: b.items.filter((_: any, j: number) => j !== i) })}>
                ✕
              </Mini>
            </div>
          ))}
          <div>
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => set({ items: [...(b.items || []), { etiqueta: "", valor: "" }] })}
            >
              + Indicador
            </button>
          </div>
        </div>
      )}

      {b.tipo === "grafico" && (
        <div className="stack" style={{ gap: 6 }}>
          <select className="select" value={b.estilo || "barras"} onChange={(e) => set({ estilo: e.target.value })}>
            <option value="barras">Barras verticales</option>
            <option value="barras_h">Barras horizontales</option>
            <option value="dona">Dona</option>
          </select>
          {(b.categorias || []).map((c: string, i: number) => (
            <div className="row gap2" key={i}>
              <div className="grow">
                <Txt
                  value={c}
                  ph="Categoría"
                  onChange={(v) => set({ categorias: b.categorias.map((x: string, j: number) => (j === i ? v : x)) })}
                />
              </div>
              <div className="grow">
                <input
                  className="input"
                  placeholder="Valor numérico"
                  defaultValue={String(b.valores?.[i] ?? "")}
                  key={`${i}-${b.valores?.length}`}
                  onBlur={(e) => {
                    const t = e.target.value.trim().replace(",", ".");
                    const n = Number(t);
                    const nv = t !== "" && Number.isFinite(n) ? n : e.target.value;
                    set({ valores: b.categorias.map((_: any, j: number) => (j === i ? nv : b.valores?.[j] ?? "")) });
                  }}
                />
              </div>
              <Mini
                title="Eliminar"
                onClick={() =>
                  set({
                    categorias: b.categorias.filter((_: any, j: number) => j !== i),
                    valores: (b.valores || []).filter((_: any, j: number) => j !== i),
                  })
                }
              >
                ✕
              </Mini>
            </div>
          ))}
          <div>
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => set({ categorias: [...(b.categorias || []), ""], valores: [...(b.valores || []), ""] })}
            >
              + Dato
            </button>
          </div>
        </div>
      )}

      {b.tipo === "imagen" && (
        <div className="stack" style={{ gap: 6 }}>
          <input
            type="file"
            accept="image/png,image/jpeg"
            disabled={subiendo}
            onChange={(e) => subir(e.target.files?.[0])}
          />
          {subiendo && <p className="hint">Subiendo…</p>}
          <ImagenHoja briefingId={briefingId} objeto={b.objeto} />
          <Txt value={b.pie} onChange={(v) => set({ pie: v })} ph="Pie de imagen (opcional)" />
        </div>
      )}
    </div>
  );
}

// ---------------------------- editor de hojas ----------------------------
export function EdHojas({
  hojas,
  onChange,
  briefingId,
  onTraza,
}: {
  hojas: any[];
  onChange: (h: any[]) => void;
  briefingId: string;
  onTraza: (t: Record<string, string[]>) => void;
}) {
  const [cargando, setCargando] = useState<string | null>(null);
  const [subiendoDoc, setSubiendoDoc] = useState<string | null>(null);
  const setHoja = (i: number, patch: any) => onChange(hojas.map((h, j) => (j === i ? { ...h, ...patch } : h)));

  // ¿Los bloques son solo el placeholder por defecto (texto/viñetas vacíos)? Entonces la IA propone el formato.
  const soloPlaceholder = (bl: any[]) => (bl || []).every((b) => (b.tipo === "texto" || b.tipo === "vinetas") && !tieneContenido(b));

  // Completa la hoja `h` (ya con sus documentos) y aplica el resultado sobre el estado.
  async function ejecutarCompletar(i: number, h: any) {
    setCargando(h.id);
    try {
      const envio = { ...h, bloques: soloPlaceholder(h.bloques) ? [] : h.bloques };
      const r = await api.completarHoja(briefingId, envio);
      onChange(
        hojas.map((x, j) =>
          j === i ? { ...h, id: r.id || h.id, titulo: h.titulo.trim() ? h.titulo : r.titulo || h.titulo, bloques: r.bloques } : x
        )
      );
      if (r.trazabilidad && Object.keys(r.trazabilidad).length) onTraza(r.trazabilidad);
    } catch (e: any) {
      alert("La IA no pudo completar la hoja: " + (e?.message || e));
    } finally {
      setCargando(null);
    }
  }

  async function completar(i: number) {
    const h = hojas[i];
    if (!h.titulo.trim() && !h.instrucciones_ia.trim() && !(h.documentos || []).length) {
      alert("Indica un título, instrucciones o adjunta un documento para que la IA sepa qué completar.");
      return;
    }
    if ((h.bloques || []).some(tieneContenido) && !window.confirm("La IA reemplazará el contenido actual de los bloques de esta hoja. ¿Continuar?")) return;
    await ejecutarCompletar(i, h);
  }

  // Sube uno o varios documentos a la hoja; si la hoja aún está vacía, la completa de inmediato con ellos.
  async function adjuntar(i: number, files: FileList | null) {
    if (!files || files.length === 0) return;
    const h = hojas[i];
    const actuales = h.documentos || [];
    if (actuales.length + files.length > 5) {
      alert("Máximo 5 documentos por hoja.");
      return;
    }
    setSubiendoDoc(h.id);
    const nuevos: any[] = [];
    for (const f of Array.from(files)) {
      try {
        const r = await api.subirDocumentoHoja(briefingId, f);
        nuevos.push({ nombre: r.nombre, objeto: r.objeto, tipo: r.tipo });
      } catch (e: any) {
        alert(`No se pudo adjuntar "${f.name}": ` + (e?.message || e));
      }
    }
    setSubiendoDoc(null);
    if (nuevos.length === 0) return;
    const conDocs = { ...h, documentos: [...actuales, ...nuevos] };
    if ((h.bloques || []).some(tieneContenido)) {
      onChange(hojas.map((x, j) => (j === i ? conDocs : x)));
      return; // ya tenía contenido: el usuario decide cuándo pedir "Completar con IA"
    }
    await ejecutarCompletar(i, conDocs);
  }

  return (
    <div className="stack">
      {hojas.length === 0 && (
        <p className="muted">
          Sin hojas adicionales. Agrega una para incluir información extra en el PDF (por ejemplo, lo que pida el mando).
        </p>
      )}
      {hojas.map((h, i) => (
        <div key={h.id || i} className="hoja-ed">
          <div className="row row--between gap2 row--wrap">
            <div className="eyebrow">Hoja adicional {i + 1}</div>
            <div className="btn-group">
              <Mini title="Subir" onClick={() => onChange(mover(hojas, i, -1))}>↑</Mini>
              <Mini title="Bajar" onClick={() => onChange(mover(hojas, i, 1))}>↓</Mini>
              <Mini
                title="Eliminar hoja"
                onClick={() => window.confirm("¿Eliminar esta hoja?") && onChange(hojas.filter((_, j) => j !== i))}
              >
                ✕
              </Mini>
            </div>
          </div>

          <div className="ed-grid mt2">
            <div>
              <div className="metric__k" style={{ marginBottom: 4 }}>Sección (caja del encabezado)</div>
              <input
                className="input"
                list="secciones-hoja"
                value={h.seccion}
                onChange={(e) => setHoja(i, { seccion: e.target.value })}
              />
            </div>
            <div>
              <div className="metric__k" style={{ marginBottom: 4 }}>Título de la hoja</div>
              <Txt value={h.titulo} onChange={(v) => setHoja(i, { titulo: v })} ph="Ej. Situación frontera norte" />
            </div>
            <div>
              <div className="metric__k" style={{ marginBottom: 4 }}>Posición en el PDF</div>
              <select
                className="select"
                value={h.despues_de == null ? "" : String(h.despues_de)}
                onChange={(e) => setHoja(i, { despues_de: e.target.value === "" ? null : Number(e.target.value) })}
              >
                {POSICIONES.map((p) => (
                  <option key={p.v} value={p.v}>{p.l}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt3">
            <div className="metric__k" style={{ marginBottom: 4 }}>
              Documentos de origen (PDF, Word, Excel, correo, texto) — la IA los lee y completa la hoja
            </div>
            <input
              type="file"
              multiple
              accept=".pdf,.doc,.docx,.xls,.xlsx,.xlsm,.eml,.msg,.txt,.csv,.log"
              disabled={subiendoDoc !== null || cargando !== null}
              onChange={(e) => {
                adjuntar(i, e.target.files);
                e.target.value = "";
              }}
            />
            {subiendoDoc === h.id && <p className="hint">Subiendo y leyendo documentos…</p>}
            {(h.documentos || []).length > 0 && (
              <ul className="bullets mt2">
                {h.documentos.map((d: any, k: number) => (
                  <li key={d.objeto || k}>
                    {d.nombre}{" "}
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      title="Quitar documento"
                      onClick={() => setHoja(i, { documentos: h.documentos.filter((_: any, j: number) => j !== k) })}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="hint mt2">
              Con documentos adjuntos, la hoja se completa solo con su contenido (no con los hechos del briefing).
            </p>
          </div>

          <div className="mt3">
            <div className="metric__k" style={{ marginBottom: 4 }}>Instrucciones para la IA (opcional)</div>
            <Txt
              area
              value={h.instrucciones_ia}
              onChange={(v) => setHoja(i, { instrucciones_ia: v })}
              ph="Ej. Resumir los incidentes de la última semana en la frontera norte, con unidades involucradas"
            />
          </div>

          <div className="stack mt3" style={{ gap: "var(--sp-3)" }}>
            {(h.bloques || []).map((b: any, bi: number) => (
              <div key={bi} className="hoja-bloque">
                <div className="row row--between gap2">
                  <span className="tag-tipo">{TIPOS.find((t) => t.v === b.tipo)?.l || b.tipo}</span>
                  <div className="btn-group">
                    <Mini title="Subir" onClick={() => setHoja(i, { bloques: mover(h.bloques, bi, -1) })}>↑</Mini>
                    <Mini title="Bajar" onClick={() => setHoja(i, { bloques: mover(h.bloques, bi, 1) })}>↓</Mini>
                    <Mini title="Eliminar bloque" onClick={() => setHoja(i, { bloques: h.bloques.filter((_: any, j: number) => j !== bi) })}>✕</Mini>
                  </div>
                </div>
                <div className="mt2">
                  <EdBloque
                    b={b}
                    briefingId={briefingId}
                    onChange={(nb) => setHoja(i, { bloques: h.bloques.map((x: any, j: number) => (j === bi ? nb : x)) })}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="row gap2 row--wrap mt3">
            <select
              className="select"
              style={{ width: 220 }}
              value=""
              onChange={(e) => e.target.value && setHoja(i, { bloques: [...(h.bloques || []), bloqueVacio(e.target.value)] })}
            >
              <option value="">+ Agregar bloque…</option>
              {TIPOS.map((t) => (
                <option key={t.v} value={t.v}>{t.l}</option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              disabled={cargando !== null}
              onClick={() => completar(i)}
            >
              <Icon name="bolt" />
              {cargando === h.id ? "La IA está completando…" : "Completar con IA"}
            </button>
          </div>
          <p className="hint mt2">
            Sin documentos, la IA usa los hechos y fuentes ya cargados. Si no hay dato, deja el campo vacío. Revisa el resultado antes de guardar.
          </p>
        </div>
      ))}
      <datalist id="secciones-hoja">
        {SECCIONES_HOJA.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <div>
        <button type="button" className="btn btn--secondary" onClick={() => onChange([...hojas, hojaNueva()])}>
          + Agregar hoja
        </button>
      </div>
    </div>
  );
}

// ---------------------------- vista de lectura ----------------------------
export function HojasLectura({ hojas, briefingId }: { hojas: any[]; briefingId: string }) {
  if (!hojas || hojas.length === 0) return null;
  const pos = (d: any) => POSICIONES.find((p) => p.v === (d == null ? "" : String(d)))?.l || "";
  return (
    <div>
      <div className="eyebrow" style={{ marginBottom: "var(--sp-3)" }}>
        Hojas adicionales
      </div>
      {hojas.map((h, i) => (
        <div className="card" key={h.id || i} style={{ marginBottom: "var(--sp-3)" }}>
          <div className="card__head">
            <div className="card__title">
              {h.seccion ? `${h.seccion} — ` : ""}
              {h.titulo || "Hoja adicional"}
            </div>
            <span className="hint">{pos(h.despues_de)}</span>
          </div>
          <div className="card__body stack" style={{ gap: "var(--sp-4)" }}>
            {(h.bloques || []).map((b: any, bi: number) => (
              <div key={bi}>
                {b.titulo && <div className="eyebrow" style={{ marginBottom: 6 }}>{b.titulo}</div>}
                {b.tipo === "texto" &&
                  String(b.texto || "")
                    .split("\n")
                    .filter((p) => p.trim())
                    .map((p, k) => (
                      <p key={k} style={{ lineHeight: 1.6, marginBottom: 6 }}>{p}</p>
                    ))}
                {b.tipo === "vinetas" && (
                  <ul className="bullets">
                    {(b.items || []).filter((x: string) => String(x).trim()).map((x: string, k: number) => (
                      <li key={k}>{x}</li>
                    ))}
                  </ul>
                )}
                {b.tipo === "tabla" && (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>{(b.columnas || []).map((c: string, k: number) => <th key={k}>{c}</th>)}</tr>
                      </thead>
                      <tbody>
                        {(b.filas || []).map((f: string[], r: number) => (
                          <tr key={r}>{(b.columnas || []).map((_: any, k: number) => <td key={k}>{f[k]}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {b.tipo === "kpis" && (
                  <div className="metrics">
                    {(b.items || []).map((it: any, k: number) => (
                      <div className="metric" key={k}>
                        <div className="metric__k">{it.etiqueta}</div>
                        <div className="metric__v">{it.valor}</div>
                      </div>
                    ))}
                  </div>
                )}
                {b.tipo === "grafico" && (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr><th>Categoría</th><th>Valor</th></tr>
                      </thead>
                      <tbody>
                        {(b.categorias || []).map((c: string, k: number) => (
                          <tr key={k}><td>{c}</td><td>{String(b.valores?.[k] ?? "")}</td></tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="hint">Se dibuja como gráfico ({b.estilo || "barras"}) en el PDF.</p>
                  </div>
                )}
                {b.tipo === "imagen" && (
                  <div>
                    <ImagenHoja briefingId={briefingId} objeto={b.objeto} />
                    {b.pie && <p className="hint">{b.pie}</p>}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
