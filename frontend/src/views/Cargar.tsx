import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, wsUrl } from "../api";
import { encolarCargas, pendientes, sincronizar } from "../offline";
import { Icon } from "../components/icons";
import { fmtTamano, tipoArchivo } from "../components/ui";

const NIVELES = ["PUBLICO", "RESERVADO", "SECRETO"] as const;
const STEPS = [
  { id: "ingestar", name: "Ingestar" },
  { id: "normalizar", name: "Normalizar" },
  { id: "extraer", name: "Extraer" },
  { id: "detectar", name: "Detectar" },
  { id: "sintetizar", name: "Sintetizar" },
];

type LogKind = "" | "ok" | "err" | "warn" | "accent";
type LogLine = { t: string; text: string; kind: LogKind };

// El worker publica etapas crudas por WebSocket; aquí se traducen al stepper de
// 5 fases y a líneas de consola legibles.
function etapaAFase(etapa: string): number | null {
  switch (etapa) {
    case "procesando":
    case "documento_ok":
    case "documento_error":
      return 2; // ingesta + normalización + extracción por documento
    case "detectando":
      return 3;
    case "sintetizando":
      return 4;
    case "completado":
      return 5;
    default:
      return null;
  }
}

export default function Cargar() {
  const [files, setFiles] = useState<File[]>([]);
  const [nivel, setNivel] = useState<string>("RESERVADO");
  const [titulo, setTitulo] = useState(
    "SITREP operacional " + new Date().toLocaleDateString("es-CL")
  );
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  const [cola, setCola] = useState(0);

  const [log, setLog] = useState<LogLine[]>([]);
  const [generando, setGenerando] = useState(false);
  const [mostrarPipe, setMostrarPipe] = useState(false);
  const [phase, setPhase] = useState(0); // 0..5 (5 = completado)
  const [errIdx, setErrIdx] = useState<number | null>(null);
  const [pipeEstado, setPipeEstado] = useState<"run" | "ok" | "err">("run");
  const [briefingId, setBriefingId] = useState<string | null>(null);

  const consoleRef = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    pendientes().then(setCola);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  useEffect(() => {
    consoleRef.current?.scrollTo(0, consoleRef.current.scrollHeight);
  }, [log]);

  function push(text: string, kind: LogKind = "") {
    const t = new Date().toLocaleTimeString("es-CL", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    setLog((l) => [...l, { t, text, kind }]);
  }

  function addFiles(nuevos: File[]) {
    if (nuevos.length) setFiles((f) => [...f, ...nuevos]);
  }
  function quitar(i: number) {
    setFiles((f) => f.filter((_, idx) => idx !== i));
  }

  async function sync() {
    const n = await sincronizar();
    push(`Sincronizados ${n} documentos de la cola.`, "ok");
    setCola(await pendientes());
  }

  // Traduce un mensaje del WebSocket a stepper + consola.
  function aplicarEtapa(d: any) {
    const etapa: string = d.etapa;
    if (etapa === "completado") {
      setPhase(5);
      setPipeEstado("ok");
      setGenerando(false);
      push("✅ SITREP listo.", "ok");
      if (d.briefing_id) setBriefingId(String(d.briefing_id));
      return;
    }
    if (etapa === "error" || etapa === "documento_error") {
      const msg = d.error ? " — " + d.error : "";
      const doc = d.doc_nombre ? " — " + d.doc_nombre : "";
      if (etapa === "error") {
        setPipeEstado("err");
        setGenerando(false);
        setErrIdx((prev) => (prev ?? Math.min(phase, 4)));
        push("❌ Falló la generación." + msg, "err");
      } else {
        push("· Error en documento" + doc + msg, "err");
      }
      return;
    }
    const fase = etapaAFase(etapa);
    if (fase !== null) setPhase((p) => Math.max(p, fase));
    if (etapa === "procesando") push("· Procesando — " + (d.doc_nombre || ""), "");
    else if (etapa === "documento_ok") push("· Documento procesado — " + (d.doc_nombre || ""), "");
    else if (etapa === "detectando")
      push("· Detectando inconsistencias" + (d.total_hechos != null ? ` — ${d.total_hechos} hechos` : ""), "accent");
    else if (etapa === "sintetizando") push("· Sintetizando SITREP institucional", "accent");
    else push("· " + etapa, "");
  }

  async function generar() {
    if (generando) return;
    setGenerando(true);
    setLog([]);
    setMostrarPipe(true);
    setPhase(0);
    setErrIdx(null);
    setPipeEstado("run");
    setBriefingId(null);
    push("Iniciando síntesis · nivel " + nivel, "accent");

    try {
      // 1) Cargar los documentos preparados (RF-001). Sin red → cola offline.
      if (files.length) {
        if (online) {
          const r = await api.upload(files, nivel);
          push(`Cargados ${r.fuentes?.length ?? files.length} documentos.`, "ok");
          setFiles([]);
          setCola(await pendientes());
        } else {
          await encolarCargas(files, nivel);
          push(`Sin conexión: ${files.length} documentos en cola de sincronización.`, "warn");
          setFiles([]);
          setCola(await pendientes());
          setPipeEstado("err");
          setErrIdx(0);
          setGenerando(false);
          return;
        }
      }

      // 2) Generar el briefing (RF-004) y seguir el progreso por WebSocket.
      const r = await api.createBriefing(titulo);
      setBriefingId(String(r.briefing_id));
      push(`Generación encolada (${r.fuentes} fuentes). Procesando…`, "accent");

      const ws = new WebSocket(wsUrl(r.task_id));
      ws.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data);
          aplicarEtapa(d);
          if (d.etapa === "completado" || d.etapa === "error") ws.close();
        } catch {
          /* ignora mensajes no-JSON */
        }
      };
      ws.onerror = () => push("(WS sin conexión; el SITREP igual se está generando)", "warn");
    } catch (e: any) {
      push("Error: " + (e?.message || e), "err");
      setPipeEstado("err");
      setErrIdx((prev) => prev ?? Math.min(phase, 4));
      setGenerando(false);
    }
  }

  function stepStatus(i: number): string {
    if (errIdx !== null && i === errIdx) return "is-error";
    if (i < phase) return "is-done";
    if (i === phase && generando) return "is-active";
    if (i === phase && pipeEstado === "run") return "is-active";
    return "";
  }
  function stepEstadoTexto(s: string): string {
    if (s === "is-done") return "Completado";
    if (s === "is-active") return "En proceso…";
    if (s === "is-error") return "Error";
    return "En espera";
  }

  return (
    <div className="page page--narrow">
      <div className="page-head">
        <div>
          <div className="eyebrow">Flujo operativo · Cargar → Generar → Exportar</div>
          <h1 className="page-title">Cargar documentos y generar SITREP</h1>
        </div>
        <div className="row gap2">
          {!online && (
            <div className="conn is-off">
              <span className="conn__led" />
              <span>OFFLINE</span>
            </div>
          )}
          {cola > 0 && (
            <button className="btn btn--secondary" onClick={sync} disabled={!online}>
              <Icon name="sync" />
              Sincronizar cola ({cola})
            </button>
          )}
        </div>
      </div>

      <div className="detail-grid" style={{ gridTemplateColumns: "1fr 320px" }}>
        {/* ---- columna principal ---- */}
        <div className="stack">
          <div className="card">
            <div className="card__head">
              <div className="card__title">Documentos fuente</div>
              <span className="hint">{files.length} archivo{files.length === 1 ? "" : "s"}</span>
            </div>
            <div className="card__body">
              <input
                ref={fileInput}
                type="file"
                multiple
                hidden
                onChange={(e) => {
                  addFiles(Array.from(e.target.files || []));
                  e.target.value = "";
                }}
              />
              <div
                className={"dropzone" + (drag ? " is-drag" : "")}
                onClick={() => fileInput.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDrag(true);
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDrag(false);
                  addFiles(Array.from(e.dataTransfer.files || []));
                }}
              >
                <div className="dropzone__ico">
                  <Icon name="upload" />
                </div>
                <div className="dropzone__main">
                  Arrastre documentos aquí o haga clic para seleccionar
                </div>
                <div className="dropzone__sub">
                  PDF · Word · Excel · correos (.msg/.eml) · bitácoras (.txt) — múltiples archivos
                </div>
              </div>

              {files.length > 0 && (
                <div className="filelist">
                  {files.map((f, i) => {
                    const t = tipoArchivo(f.name);
                    return (
                      <div className="fileitem" key={i}>
                        <div className={"fileitem__ico " + t.cls}>{t.label}</div>
                        <div className="fileitem__name">{f.name}</div>
                        <div className="fileitem__size tnum">{fmtTamano(f.size)}</div>
                        <button className="fileitem__x" title="Quitar" onClick={() => quitar(i)}>
                          <Icon name="x" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* ---- pipeline ---- */}
          {mostrarPipe && (
            <div className="card">
              <div className="card__head">
                <div className="card__title">
                  {generando && <span className="spin" />}
                  <span>
                    {pipeEstado === "ok"
                      ? "Síntesis completada"
                      : pipeEstado === "err"
                      ? "Error en la generación"
                      : "Procesando pipeline…"}
                  </span>
                </div>
                <span
                  className={
                    "pill " +
                    (pipeEstado === "ok"
                      ? "pill--listo"
                      : pipeEstado === "err"
                      ? "pill--borrador"
                      : "pill--generando")
                  }
                >
                  <span className="pill__dot" />
                  {pipeEstado === "ok" ? "Listo" : pipeEstado === "err" ? "Detenido" : "Generando"}
                </span>
              </div>
              <div className="card__body">
                <div className="stepper">
                  {STEPS.map((s, i) => {
                    const st = stepStatus(i);
                    return (
                      <div className={"step " + st} data-step={s.id} key={s.id}>
                        <div className="step__bar" />
                        <div className="step__row">
                          <span className="step__ico">{i + 1}</span>
                          <span className="step__name">{s.name}</span>
                        </div>
                        <div className="step__state">{stepEstadoTexto(st)}</div>
                      </div>
                    );
                  })}
                </div>

                <div className="console mt4" ref={consoleRef}>
                  <div className="console__head">
                    <span style={{ color: "var(--ok)" }}>●</span> proceso/pipeline.log — síntesis
                  </div>
                  <div>
                    {log.map((l, i) => (
                      <div className={"log-line" + (l.kind ? " log-line--" + l.kind : "")} key={i}>
                        <span className="log-line__t">{l.t}</span>
                        <span>{l.text}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {(pipeEstado === "ok" || pipeEstado === "err") && (
                  <div className="row gap2 mt4">
                    {pipeEstado === "ok" && briefingId && (
                      <Link className="btn btn--primary" to={`/briefings/${briefingId}`}>
                        <Icon name="arrow-right" />
                        Ver SITREP generado
                      </Link>
                    )}
                    {pipeEstado === "err" && (
                      <button className="btn btn--secondary" onClick={generar}>
                        <Icon name="sync" />
                        Reintentar
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ---- panel de parámetros ---- */}
        <div className="stack">
          <div className="card">
            <div className="card__head">
              <div className="card__title">Parámetros</div>
            </div>
            <div className="card__body stack" style={{ gap: "var(--sp-5)" }}>
              <div className="field">
                <label className="label">Título del SITREP</label>
                <input
                  className="input"
                  value={titulo}
                  onChange={(e) => setTitulo(e.target.value)}
                />
              </div>
              <div className="field">
                <label className="label">
                  Nivel de clasificación de la carga <span className="req">*</span>
                </label>
                <div className="seg" style={{ width: "100%" }}>
                  {NIVELES.map((nv) => (
                    <button
                      key={nv}
                      className={"seg__opt" + (nivel === nv ? " is-on" : "")}
                      data-v={nv}
                      style={{ flex: 1, justifyContent: "center" }}
                      onClick={() => setNivel(nv)}
                      type="button"
                    >
                      <span className="pip" />
                      {nv.charAt(0) + nv.slice(1).toLowerCase()}
                    </button>
                  ))}
                </div>
                <p className="hint">
                  Determina la cinta de clasificación y los permisos de visualización de los
                  documentos cargados.
                </p>
              </div>
              <hr className="divider" style={{ margin: 0 }} />
              <button
                className="btn btn--primary btn--lg btn--block"
                onClick={generar}
                disabled={generando}
              >
                <Icon name="bolt" />
                Cargar → Generar → Exportar
              </button>
              <p className="hint" style={{ textAlign: "center" }}>
                5 etapas · Ingestar → Normalizar → Extraer → Detectar → Sintetizar
              </p>
            </div>
          </div>

          <div className="card" style={{ background: "var(--surface-2)" }}>
            <div className="card__body">
              <div className="row gap2" style={{ alignItems: "flex-start" }}>
                <Icon name="info" style={{ width: 18, height: 18, flex: "none", marginTop: 1, color: "var(--text-muted)" }} />
                <p className="hint" style={{ margin: 0 }}>
                  El pipeline recorre <strong>Ingestar → Normalizar → Extraer → Detectar →
                  Sintetizar</strong>. La consola emite el progreso en vivo por WebSocket. Sin
                  conexión, los documentos quedan en una cola de sincronización (RF-010).
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
