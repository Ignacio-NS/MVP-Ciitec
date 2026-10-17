import { useEffect, useMemo, useRef, useState } from "react";
import { api, mensajeError } from "../api";
import { useAuth } from "../auth";
import { Icon } from "../components/icons";
import { fmtFecha } from "../components/ui";

// Ver el motor activo: Administrador, Auditor y Oficial de Seguridad. Cambiarlo: solo el
// Administrador del Sistema (el backend lo vuelve a exigir: esto solo ordena la interfaz).
const ROLES_VER = ["Auditor", "Oficial de Seguridad", "Administrador del Sistema"];

type Preset = {
  nombre: string;
  etiqueta: string;
  adaptador: string;
  resguardo: "MAXIMO" | "ALTO" | "BASICO";
  descripcion: string;
  base_url: string;
  modelo: string;
  requiere_api_key: boolean;
  clave_en_servidor: boolean;
  json_mode: boolean;
  temperature: number | null;
  token_param: string;
  extra_params: Record<string, unknown>;
  permitido: boolean;
};

type Efectiva = {
  proveedor: string;
  etiqueta: string;
  resguardo: Preset["resguardo"];
  modelo: string;
  base_url: string;
  host: string;
  origen: "env" | "ui";
  api_key_configurada: boolean;
  api_key_sufijo: string;
  json_mode: boolean;
  temperature: number | null;
  token_param: string;
  extra_params: Record<string, unknown>;
  context_tokens: number;
  timeout_s: number;
  sintesis_modo: string;
};

const MODO_SINTESIS: Record<string, string> = {
  auto: "Automática",
  completa: "De una vez",
  secciones: "Por secciones",
};

type Tarea = { id: string; estado: "PENDIENTE" | "EN_CURSO" | "OK" | "ERROR"; progreso?: any; resultado?: any; error?: string };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const RESGUARDO: Record<string, { txt: string; cls: string; detalle: string }> = {
  MAXIMO: {
    txt: "Red institucional",
    cls: "badge--pub",
    detalle: "El modelo corre en servidores del Ejército. Apto para información Reservada y Secreta.",
  },
  ALTO: {
    txt: "Nube privada",
    cls: "badge--res",
    detalle: "Nube dedicada con contrato institucional. Solo información sensible no clasificada, si la institución lo autoriza.",
  },
  BASICO: {
    txt: "API pública",
    cls: "badge--sec",
    detalle: "Los documentos salen a un proveedor externo. Usar solo con datos sintéticos o no clasificados.",
  },
};

function Resguardo({ nivel }: { nivel?: string }) {
  const r = RESGUARDO[nivel || ""] || RESGUARDO.BASICO;
  return <span className={"badge " + r.cls}>{r.txt}</span>;
}

const VACIO = {
  proveedor: "",
  modelo: "",
  base_url: "",
  api_key: "",
  json_mode: "" as "" | "si" | "no",
  temperature: "",
  token_param: "",
  context_tokens: "",
  timeout_s: "",
  extra_params: "",
  sintesis_modo: "",
};

export default function MotorIA() {
  const { user } = useAuth();
  const habilitado = user?.roles?.some((r) => ROLES_VER.includes(r));

  const [cfg, setCfg] = useState<any>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [historial, setHistorial] = useState<any[]>([]);
  const [form, setForm] = useState({ ...VACIO });
  const [ocupado, setOcupado] = useState<"" | "probar" | "activar" | "env" | "probar-actual">("");
  const [resultado, setResultado] = useState<any>(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [forzar, setForzar] = useState(false);
  // Modelos que ofrece el servicio elegido (para elegir de una lista).
  const [modelos, setModelos] = useState<{ lista: string[]; ollama: boolean; error: string; cargando: boolean }>({
    lista: [],
    ollama: false,
    error: "",
    cargando: false,
  });
  const [manual, setManual] = useState(false);
  const [verif, setVerif] = useState<(Tarea & { modelo: string }) | null>(null);
  const [descarga, setDescarga] = useState<(Tarea & { modelo: string }) | null>(null);
  const vivo = useRef(true);
  useEffect(() => () => void (vivo.current = false), []);

  async function cargar() {
    const [c, p, h] = await Promise.all([api.llmConfig(), api.llmProveedores(), api.llmHistorial()]);
    setCfg(c);
    setPresets(p.proveedores || []);
    setHistorial(h.cambios || []);
  }

  useEffect(() => {
    if (habilitado) cargar().catch((e) => setError(mensajeError(e)));
  }, [habilitado]);

  const preset = useMemo(() => presets.find((p) => p.nombre === form.proveedor), [presets, form.proveedor]);
  const efectiva: Efectiva | null = cfg?.efectiva || null;
  const puedeEditar = !!cfg?.puede_editar && !!cfg?.migracion_aplicada;

  function set<K extends keyof typeof VACIO>(k: K, v: (typeof VACIO)[K]) {
    setForm((f) => ({ ...f, [k]: v }));
    setResultado(null);
    setForzar(false);
  }

  function elegirProveedor(nombre: string) {
    // Al cambiar de proveedor se limpian los campos: los valores de un servicio no sirven en otro.
    setForm({ ...VACIO, proveedor: nombre });
    setResultado(null);
    setError("");
    setForzar(false);
    setManual(false);
    setModelos({ lista: [], ollama: false, error: "", cargando: false });
    const p = presets.find((x) => x.nombre === nombre);
    // Si el servidor ya tiene lo necesario (clave o servicio sin clave), se listan sus modelos de inmediato.
    if (p && (!p.requiere_api_key || p.clave_en_servidor)) cargarModelos({ ...VACIO, proveedor: nombre });
  }

  async function cargarModelos(f = form) {
    if (!f.proveedor) return;
    setModelos((m) => ({ ...m, cargando: true, error: "" }));
    try {
      const r = await api.llmModelos({
        proveedor: f.proveedor,
        base_url: f.base_url.trim() || null,
        api_key: f.api_key.trim() || null,
      });
      setModelos({ lista: r.modelos || [], ollama: !!r.ollama, error: r.error || "", cargando: false });
      if ((r.modelos || []).length === 0) setManual(true);
    } catch (e) {
      setModelos({ lista: [], ollama: false, error: mensajeError(e), cargando: false });
      setManual(true);
    }
  }

  // Sigue una tarea en segundo plano (verificación o descarga) hasta que termine.
  async function seguir(id: string, alAvanzar: (t: Tarea) => void): Promise<Tarea> {
    for (;;) {
      await sleep(1500);
      if (!vivo.current) return { id, estado: "ERROR", error: "cancelado" };
      const r = await api.llmTarea(id);
      const t: Tarea = { id, ...r };
      if (r.estado === "OK" || r.estado === "ERROR") return t;
      alAvanzar(t);
    }
  }

  async function verificar(actual = false) {
    setError("");
    setResultado(null);
    try {
      const r = await api.llmVerificar(actual ? undefined : cuerpo());
      setVerif({ id: r.tarea, estado: "PENDIENTE", modelo: r.modelo });
      const fin = await seguir(r.tarea, (t) => setVerif({ ...t, modelo: r.modelo }));
      setVerif({ ...fin, modelo: r.modelo });
    } catch (e) {
      setVerif(null);
      setError(mensajeError(e));
    }
  }

  async function descargar() {
    setError("");
    const modelo = form.modelo.trim();
    try {
      const r = await api.llmDescargar(cuerpo());
      setDescarga({ id: r.tarea, estado: "PENDIENTE", modelo });
      const fin = await seguir(r.tarea, (t) => setDescarga({ ...t, modelo }));
      setDescarga({ ...fin, modelo });
      if (fin.estado === "OK") await cargarModelos();
    } catch (e) {
      setDescarga(null);
      setError(mensajeError(e));
    }
  }

  function cuerpo() {
    let extra: Record<string, unknown> | null = null;
    if (form.extra_params.trim()) {
      try {
        extra = JSON.parse(form.extra_params);
      } catch {
        throw new Error('Los parámetros extra deben ser JSON válido, p. ej. {"reasoning_effort": "none"}');
      }
    }
    return {
      proveedor: form.proveedor,
      modelo: form.modelo.trim() || null,
      base_url: form.base_url.trim() || null,
      api_key: form.api_key.trim() ? form.api_key.trim() : null,
      json_mode: form.json_mode === "" ? null : form.json_mode === "si",
      temperature: form.temperature.trim() || null,
      token_param: form.token_param || null,
      context_tokens: form.context_tokens ? Number(form.context_tokens) : null,
      timeout_s: form.timeout_s ? Number(form.timeout_s) : null,
      extra_params: extra,
      sintesis_modo: form.sintesis_modo || null,
    };
  }

  async function probar() {
    setOcupado("probar");
    setError("");
    setAviso("");
    try {
      setResultado(await api.llmProbar(cuerpo()));
    } catch (e) {
      setError(mensajeError(e));
    } finally {
      setOcupado("");
    }
  }

  async function activar() {
    setOcupado("activar");
    setError("");
    setAviso("");
    try {
      const r = await api.llmActivar({ ...cuerpo(), probar: true, forzar });
      setResultado(r.prueba);
      setAviso(`Activado: ${r.efectiva.etiqueta} · ${r.efectiva.modelo}. Se aplica a la próxima generación.`);
      setForm({ ...VACIO });
      await cargar();
    } catch (e) {
      const msg = mensajeError(e);
      if (msg.startsWith("La prueba de conexión falló")) {
        // Se muestra como resultado de prueba para ofrecer "activar de todos modos".
        setResultado({ ok: false, proveedor: form.proveedor, modelo: form.modelo || preset?.modelo, error: msg });
      } else {
        setError(msg);
      }
    } finally {
      setOcupado("");
    }
  }

  async function volverEnv() {
    setOcupado("env");
    setError("");
    setAviso("");
    try {
      const r = await api.llmVolverEnv();
      setAviso(`Se volvió a la configuración del servidor: ${r.efectiva.etiqueta} · ${r.efectiva.modelo}.`);
      await cargar();
    } catch (e) {
      setError(mensajeError(e));
    } finally {
      setOcupado("");
    }
  }

  async function probarActual() {
    setOcupado("probar-actual");
    setError("");
    try {
      setResultado(await api.llmProbar());
    } catch (e) {
      setError(mensajeError(e));
    } finally {
      setOcupado("");
    }
  }

  if (!habilitado) {
    return (
      <div className="page">
        <div className="card">
          <div className="empty">
            <div className="empty__ico">
              <Icon name="lock" strokeWidth={1.6} />
            </div>
            <div className="empty__title">Acceso restringido</div>
            <p style={{ maxWidth: "46ch", margin: "0 auto" }}>
              La configuración del motor de IA está disponible para el <strong>Administrador del Sistema</strong>.
              Auditor y Oficial de Seguridad pueden consultarla.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const fallaPrueba = resultado && resultado.ok === false;
  const verificando = !!verif && (verif.estado === "PENDIENTE" || verif.estado === "EN_CURSO");
  const puedeDescargar =
    preset?.nombre === "local" &&
    modelos.ollama &&
    !!form.modelo.trim() &&
    !modelos.lista.includes(form.modelo.trim());

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Administración · Inteligencia artificial</div>
          <h1 className="page-title">Motor de IA</h1>
          <p className="page-sub">
            Qué modelo extrae los hechos y redacta el SITREP. Se puede cambiar sin reiniciar: el cambio se aplica a
            la próxima generación y queda en la auditoría.
          </p>
        </div>
      </div>

      {error && (
        <div className="alert alert--err">
          <Icon name="alert-circle" />
          <span>{error}</span>
        </div>
      )}
      {aviso && (
        <div className="alert alert--ok">
          <Icon name="check-circle" />
          <span>{aviso}</span>
        </div>
      )}
      {cfg && !cfg.migracion_aplicada && (
        <div className="alert alert--err">
          <Icon name="alert-triangle" />
          <span>
            Falta aplicar <span className="mono">db/migrations/003_llm_configurable.sql</span>. El sistema funciona
            con el .env del servidor, pero no se pueden guardar cambios desde aquí.
          </span>
        </div>
      )}
      {cfg && !cfg.ui_habilitada && (
        <div className="alert alert--ok" style={{ color: "var(--text-2)" }}>
          <Icon name="lock" />
          <span>
            El servidor bloqueó los cambios desde la interfaz (<span className="mono">LLM_CONFIG_UI=false</span>). El
            motor se cambia en el .env.
          </span>
        </div>
      )}

      <div className="stack">
        {/* ---------------- En uso ---------------- */}
        <div className="card">
          <div className="card__head">
            <div className="card__title">
              <Icon name="bolt" /> En uso ahora
            </div>
            <div className="btn-group">
              {efectiva && (
                <button className="btn btn--secondary btn--sm" onClick={probarActual} disabled={!!ocupado}>
                  {ocupado === "probar-actual" ? <span className="spin" /> : <Icon name="sync" />}
                  Probar conexión
                </button>
              )}
              {efectiva && cfg?.puede_editar && (
                <button
                  className="btn btn--secondary btn--sm"
                  onClick={() => verificar(true)}
                  disabled={!!ocupado || verificando}
                >
                  <Icon name="shield-check" />
                  Verificar modelo
                </button>
              )}
              {efectiva?.origen === "ui" && puedeEditar && (
                <button className="btn btn--ghost btn--sm" onClick={volverEnv} disabled={!!ocupado}>
                  {ocupado === "env" ? <span className="spin" /> : <Icon name="arrow-left" />}
                  Volver al .env del servidor
                </button>
              )}
            </div>
          </div>
          <div className="card__body">
            {!cfg && <span className="muted">Cargando…</span>}
            {cfg && !efectiva && (
              <div className="alert alert--err" style={{ marginBottom: 0 }}>
                <Icon name="alert-circle" />
                <span>
                  No hay un motor de IA válido: {cfg.error}. La generación de SITREP está detenida hasta corregirlo.
                </span>
              </div>
            )}
            {efectiva && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--sp-4)" }}>
                <Dato etiqueta="Proveedor" valor={efectiva.etiqueta} />
                <Dato etiqueta="Modelo" valor={<span className="mono">{efectiva.modelo}</span>} />
                <Dato etiqueta="Resguardo de la información" valor={<Resguardo nivel={efectiva.resguardo} />} />
                <Dato
                  etiqueta="Configurado desde"
                  valor={efectiva.origen === "ui" ? "Esta interfaz" : ".env del servidor"}
                />
                <Dato etiqueta="Servidor" valor={<span className="mono">{efectiva.host || "—"}</span>} />
                <Dato
                  etiqueta="API key"
                  valor={
                    efectiva.api_key_configurada ? (
                      <span className="mono">•••• {efectiva.api_key_sufijo}</span>
                    ) : (
                      <span className="muted">sin clave</span>
                    )
                  }
                />
                <Dato
                  etiqueta="Ventana de contexto"
                  valor={efectiva.context_tokens ? `${efectiva.context_tokens.toLocaleString("es-CL")} tokens` : "Topes fijos del .env"}
                />
                <Dato etiqueta="Modo JSON" valor={efectiva.json_mode ? "Sí" : "No"} />
                <Dato
                  etiqueta="Redacción del SITREP"
                  valor={MODO_SINTESIS[efectiva.sintesis_modo] || efectiva.sintesis_modo}
                />
              </div>
            )}
            {efectiva && (
              <p className="hint" style={{ marginTop: "var(--sp-4)", marginBottom: 0 }}>
                {RESGUARDO[efectiva.resguardo]?.detalle}
              </p>
            )}
          </div>
        </div>

        {/* ---------------- Resultado de prueba ---------------- */}
        {resultado && (
          <div className={"alert " + (resultado.ok ? "alert--ok" : "alert--err")} style={{ marginBottom: 0 }}>
            <Icon name={resultado.ok ? "check-circle" : "alert-circle"} />
            <span>
              {resultado.ok ? (
                <>
                  <strong>Conexión correcta</strong> con {resultado.proveedor} · {resultado.modelo} en{" "}
                  {(resultado.latencia_ms / 1000).toFixed(1)} s. El modelo respondió JSON válido.
                </>
              ) : (
                <>
                  <strong>La prueba falló</strong> ({resultado.proveedor} · {resultado.modelo}): {resultado.error}
                </>
              )}
            </span>
          </div>
        )}

        {verif && <PanelVerificacion v={verif} onCerrar={() => setVerif(null)} />}
        {descarga && <PanelDescarga d={descarga} onCerrar={() => setDescarga(null)} />}

        {/* ---------------- Cambiar ---------------- */}
        {puedeEditar && (
          <div className="card">
            <div className="card__head">
              <div className="card__title">
                <Icon name="edit" /> Cambiar motor de IA
              </div>
            </div>
            <div className="card__body">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "var(--sp-4)" }}>
                <div className="field">
                  <label className="label" htmlFor="ia-proveedor">
                    Proveedor <span className="req">*</span>
                  </label>
                  <select
                    id="ia-proveedor"
                    className="select"
                    value={form.proveedor}
                    onChange={(e) => elegirProveedor(e.target.value)}
                  >
                    <option value="">Elegir…</option>
                    {(["MAXIMO", "ALTO", "BASICO"] as const).map((nivel) => (
                      <optgroup key={nivel} label={RESGUARDO[nivel].txt}>
                        {presets
                          .filter((p) => p.resguardo === nivel)
                          .map((p) => (
                            <option key={p.nombre} value={p.nombre} disabled={!p.permitido}>
                              {p.etiqueta}
                              {!p.permitido ? " (no permitido en este servidor)" : ""}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                  </select>
                  {preset && <span className="hint">{preset.descripcion}</span>}
                </div>

                <div className="field">
                  <label className="label" htmlFor="ia-modelo">
                    Modelo {preset && !preset.modelo && <span className="req">*</span>}
                  </label>
                  {preset && modelos.lista.length > 0 && !manual ? (
                    <select
                      id="ia-modelo"
                      className="select mono"
                      value={form.modelo}
                      onChange={(e) => {
                        if (e.target.value === "__otro") {
                          setManual(true);
                          set("modelo", "");
                        } else set("modelo", e.target.value);
                      }}
                    >
                      <option value="">{preset.modelo ? `Por defecto (${preset.modelo})` : "Elegir…"}</option>
                      {modelos.lista.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                      <option value="__otro">Otro (escribir el nombre)…</option>
                    </select>
                  ) : (
                    <input
                      id="ia-modelo"
                      className="input mono"
                      placeholder={preset?.modelo || "p. ej. qwen3.8:27b"}
                      value={form.modelo}
                      onChange={(e) => set("modelo", e.target.value)}
                      disabled={!preset}
                    />
                  )}
                  {preset && (
                    <span className="hint">
                      {modelos.cargando ? (
                        <>Consultando los modelos del servicio…</>
                      ) : modelos.lista.length > 0 ? (
                        <>
                          {modelos.lista.length} modelos disponibles en el servicio
                          {modelos.ollama ? " (ya descargados en Ollama)" : ""}.{" "}
                          {manual && (
                            <>
                              <button className="linkbtn" onClick={() => setManual(false)}>
                                Elegir de la lista
                              </button>
                              {" · "}
                            </>
                          )}
                        </>
                      ) : modelos.error ? (
                        <>No se pudo obtener la lista ({modelos.error}). Escriba el nombre exacto. </>
                      ) : (
                        <>{preset.modelo ? `Vacío = ${preset.modelo}. ` : "Nombre exacto del modelo en el servicio. "}</>
                      )}
                      {!modelos.cargando && (
                        <button className="linkbtn" onClick={() => cargarModelos()}>
                          {modelos.lista.length ? "Actualizar lista" : "Ver modelos del servicio"}
                        </button>
                      )}
                    </span>
                  )}
                  {puedeDescargar && (
                    <button
                      className="btn btn--secondary btn--sm"
                      style={{ marginTop: 6, alignSelf: "flex-start" }}
                      onClick={descargar}
                      disabled={!!ocupado || (descarga?.estado === "PENDIENTE" || descarga?.estado === "EN_CURSO")}
                    >
                      <Icon name="download" />
                      Descargar «{form.modelo.trim()}» en el servidor
                    </button>
                  )}
                </div>

                {preset ? (
                  <div className="field">
                    <label className="label" htmlFor="ia-url">
                      URL del endpoint {preset && !preset.base_url && <span className="req">*</span>}
                    </label>
                    <input
                      id="ia-url"
                      className="input mono"
                      placeholder={preset?.base_url || "https://…/v1"}
                      value={form.base_url}
                      onChange={(e) => set("base_url", e.target.value)}
                    />
                    <span className="hint">
                      {preset?.nombre === "local"
                        ? "Servidor Ollama o vLLM de la red institucional."
                        : preset?.base_url
                          ? "Vacío = URL oficial del proveedor."
                          : "Azure, Bedrock, Vertex, OpenRouter o un gateway institucional."}
                    </span>
                  </div>
                ) : null}

                {preset && (
                  <div className="field">
                    <label className="label" htmlFor="ia-key">
                      API key
                    </label>
                    <input
                      id="ia-key"
                      className="input mono"
                      type="password"
                      autoComplete="new-password"
                      placeholder={preset.clave_en_servidor ? "Usar la clave del servidor" : preset.requiere_api_key ? "Obligatoria" : "Opcional"}
                      value={form.api_key}
                      onChange={(e) => set("api_key", e.target.value)}
                    />
                    <span className="hint">
                      Se guarda cifrada y nunca se vuelve a mostrar.{" "}
                      {preset.clave_en_servidor && "Si la dejas vacía se usa la que ya tiene el servidor."}
                    </span>
                  </div>
                )}
              </div>

              {preset && (
                <details style={{ marginTop: "var(--sp-5)" }}>
                  <summary className="label" style={{ cursor: "pointer" }}>
                    Opciones avanzadas
                  </summary>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                      gap: "var(--sp-4)",
                      marginTop: "var(--sp-4)",
                    }}
                  >
                    <div className="field">
                      <label className="label" htmlFor="ia-modo">Redacción del SITREP</label>
                      <select
                        id="ia-modo"
                        className="select"
                        value={form.sintesis_modo}
                        onChange={(e) => set("sintesis_modo", e.target.value)}
                      >
                        <option value="">Según servidor</option>
                        <option value="auto">Automática</option>
                        <option value="completa">De una vez</option>
                        <option value="secciones">Por secciones</option>
                      </select>
                      <span className="hint">
                        “Por secciones” permite usar modelos chicos o locales: el SITREP se redacta en 6 partes.
                        “Automática” lo hace de una vez y, si el modelo no alcanza, por secciones.
                      </span>
                    </div>
                    <div className="field">
                      <label className="label" htmlFor="ia-ctx">Ventana de contexto (tokens)</label>
                      <input
                        id="ia-ctx"
                        className="input mono"
                        type="number"
                        min={0}
                        placeholder="0 = topes fijos"
                        value={form.context_tokens}
                        onChange={(e) => set("context_tokens", e.target.value)}
                      />
                      <span className="hint">Declararla en modelos locales: el sistema ajusta la entrada y parte los documentos largos.</span>
                    </div>
                    <div className="field">
                      <label className="label" htmlFor="ia-json">Modo JSON</label>
                      <select
                        id="ia-json"
                        className="select"
                        value={form.json_mode}
                        onChange={(e) => set("json_mode", e.target.value as typeof VACIO.json_mode)}
                      >
                        <option value="">Según proveedor</option>
                        <option value="si">Sí</option>
                        <option value="no">No (el servicio no lo acepta)</option>
                      </select>
                    </div>
                    <div className="field">
                      <label className="label" htmlFor="ia-temp">Temperatura</label>
                      <input
                        id="ia-temp"
                        className="input mono"
                        placeholder={preset.temperature === null ? "no se envía" : String(preset.temperature)}
                        value={form.temperature}
                        onChange={(e) => set("temperature", e.target.value)}
                      />
                      <span className="hint">“none” = no enviarla (modelos de razonamiento).</span>
                    </div>
                    <div className="field">
                      <label className="label" htmlFor="ia-tok">Parámetro de tokens</label>
                      <select
                        id="ia-tok"
                        className="select"
                        value={form.token_param}
                        onChange={(e) => set("token_param", e.target.value)}
                      >
                        <option value="">Según proveedor</option>
                        <option value="max_tokens">max_tokens</option>
                        <option value="max_completion_tokens">max_completion_tokens</option>
                      </select>
                    </div>
                    <div className="field">
                      <label className="label" htmlFor="ia-to">Timeout por llamada (s)</label>
                      <input
                        id="ia-to"
                        className="input mono"
                        type="number"
                        min={1}
                        placeholder="300"
                        value={form.timeout_s}
                        onChange={(e) => set("timeout_s", e.target.value)}
                      />
                    </div>
                    <div className="field" style={{ gridColumn: "1 / -1" }}>
                      <label className="label" htmlFor="ia-extra">Parámetros extra (JSON)</label>
                      <textarea
                        id="ia-extra"
                        className="input mono"
                        rows={2}
                        placeholder={
                          Object.keys(preset.extra_params || {}).length
                            ? JSON.stringify(preset.extra_params)
                            : '{"reasoning_effort": "none"}'
                        }
                        value={form.extra_params}
                        onChange={(e) => set("extra_params", e.target.value)}
                      />
                      <span className="hint">Se agregan tal cual a cada llamada. Vacío = los del proveedor.</span>
                    </div>
                  </div>
                </details>
              )}

              {preset?.resguardo === "BASICO" && (
                <div className="alert alert--err" style={{ marginTop: "var(--sp-5)", marginBottom: 0 }}>
                  <Icon name="alert-triangle" />
                  <span>
                    <strong>API pública:</strong> los documentos que se procesen saldrán de la red institucional hacia{" "}
                    {preset.etiqueta}. Usar solo con datos sintéticos o no clasificados.
                  </span>
                </div>
              )}

              <div className="row row--wrap" style={{ marginTop: "var(--sp-5)" }}>
                <button className="btn btn--secondary" onClick={probar} disabled={!preset || !!ocupado}>
                  {ocupado === "probar" ? <span className="spin" /> : <Icon name="sync" />}
                  Probar sin guardar
                </button>
                <button className="btn btn--secondary" onClick={() => verificar(false)} disabled={!preset || !!ocupado || verificando}>
                  {verificando ? <span className="spin" /> : <Icon name="shield-check" />}
                  Verificar modelo
                </button>
                <button className="btn btn--primary" onClick={activar} disabled={!preset || !!ocupado}>
                  {ocupado === "activar" ? <span className="spin" /> : <Icon name="check-circle" />}
                  Probar y activar
                </button>
                {fallaPrueba && (
                  <label className="row hint" style={{ gap: 6 }}>
                    <input type="checkbox" checked={forzar} onChange={(e) => setForzar(e.target.checked)} />
                    Activar aunque la prueba falle (queda registrado)
                  </label>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ---------------- Historial ---------------- */}
        <div className="card">
          <div className="card__head">
            <div className="card__title">
              <Icon name="clock" /> Historial de cambios
            </div>
            <span className="hint mono">{historial.length} cambios</span>
          </div>
          <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Proveedor</th>
                  <th>Modelo</th>
                  <th>Servidor</th>
                  <th>Activado por</th>
                  <th>Desde</th>
                  <th>Hasta</th>
                </tr>
              </thead>
              <tbody>
                {historial.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted">
                      Sin cambios desde la interfaz: manda el .env del servidor.
                    </td>
                  </tr>
                )}
                {historial.map((h) => (
                  <tr key={h.id}>
                    <td>
                      {presets.find((p) => p.nombre === h.proveedor)?.etiqueta || h.proveedor}
                      {h.vigente && (
                        <span className="badge badge--pub" style={{ marginLeft: 6 }}>
                          vigente
                        </span>
                      )}
                    </td>
                    <td className="mono">{h.modelo || "—"}</td>
                    <td className="cell-sub mono">{h.base_url ? safeHost(h.base_url) : "—"}</td>
                    <td>{h.creado_por || "—"}</td>
                    <td className="cell-sub mono">{fmtFecha(h.creado_en)}</td>
                    <td className="cell-sub mono">{h.desactivado_en ? fmtFecha(h.desactivado_en) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function Dato({ etiqueta, valor }: { etiqueta: string; valor: React.ReactNode }) {
  return (
    <div>
      <div className="hint" style={{ marginBottom: 4 }}>
        {etiqueta}
      </div>
      <div style={{ fontWeight: 600, overflowWrap: "anywhere" }}>{valor}</div>
    </div>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

const VEREDICTO: Record<string, { txt: string; cls: string }> = {
  COMPATIBLE: { txt: "Compatible", cls: "badge--pub" },
  COMPATIBLE_CON_OBSERVACIONES: { txt: "Compatible con observaciones", cls: "badge--res" },
  NO_COMPATIBLE: { txt: "No compatible", cls: "badge--sec" },
};

function IconoPaso({ estado }: { estado: string }) {
  if (estado === "ok") return <Icon name="check-circle" style={{ color: "var(--ok)" }} />;
  if (estado === "advertencia") return <Icon name="alert-triangle" style={{ color: "var(--warn)" }} />;
  return <Icon name="alert-circle" style={{ color: "var(--danger)" }} />;
}

function ListaPasos({ pasos }: { pasos: any[] }) {
  return (
    <ul className="pasos">
      {pasos.map((p, i) => (
        <li key={i}>
          <IconoPaso estado={p.estado} />
          <span>
            <strong>{p.paso}.</strong> {p.detalle}
            {p.ejemplo && (
              <span className="hint" style={{ display: "block", marginTop: 2 }}>
                Ejemplo: “{p.ejemplo}”
              </span>
            )}
          </span>
          <span className="hint mono">{(p.latencia_ms / 1000).toFixed(1)} s</span>
        </li>
      ))}
    </ul>
  );
}

function PanelVerificacion({ v, onCerrar }: { v: Tarea & { modelo: string }; onCerrar: () => void }) {
  const enCurso = v.estado === "PENDIENTE" || v.estado === "EN_CURSO";
  const prog = v.progreso || {};
  const r = v.resultado;
  const ver = r ? VEREDICTO[r.veredicto] : null;
  return (
    <div className="card">
      <div className="card__head">
        <div className="card__title">
          <Icon name="shield-check" /> Verificación de <span className="mono">{v.modelo}</span>
        </div>
        <div className="btn-group">
          {ver && <span className={"badge badge--lg " + ver.cls}>{ver.txt}</span>}
          {!enCurso && (
            <button className="btn btn--ghost btn--sm" onClick={onCerrar} aria-label="Cerrar">
              <Icon name="x" />
            </button>
          )}
        </div>
      </div>
      <div className="card__body stack" style={{ gap: "var(--sp-4)" }}>
        {enCurso && (
          <>
            <div className="row" style={{ gap: 8 }}>
              <span className="spin" />
              <span>
                {prog.paso_actual
                  ? `Paso ${prog.paso_actual} de ${prog.total}: ${prog.descripcion}…`
                  : "En cola…"}
              </span>
            </div>
            <div className="progressbar">
              <span style={{ width: `${((prog.paso_actual || 0) - 1) * 25}%` }} />
            </div>
            <span className="hint">
              Se prueba con un parte operacional ficticio. Con modelos locales puede tardar varios minutos.
            </span>
          </>
        )}
        {(r?.pasos || prog.pasos || []).length > 0 && <ListaPasos pasos={r?.pasos || prog.pasos} />}
        {r && (
          <p className="hint" style={{ margin: 0 }}>
            {r.resumen}
            {r.modo_sintesis_recomendado === "secciones" &&
              " Recomendado: redacción del SITREP por secciones (Opciones avanzadas)."}
          </p>
        )}
        {v.estado === "ERROR" && (
          <div className="alert alert--err" style={{ marginBottom: 0 }}>
            <Icon name="alert-circle" />
            <span>La verificación no pudo ejecutarse: {v.error}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function PanelDescarga({ d, onCerrar }: { d: Tarea & { modelo: string }; onCerrar: () => void }) {
  const enCurso = d.estado === "PENDIENTE" || d.estado === "EN_CURSO";
  const p = d.progreso || {};
  return (
    <div className={"alert " + (d.estado === "ERROR" ? "alert--err" : "alert--ok")} style={{ marginBottom: 0 }}>
      <Icon name={d.estado === "ERROR" ? "alert-circle" : enCurso ? "download" : "check-circle"} />
      <span style={{ flex: 1 }}>
        {enCurso && (
          <>
            Descargando <span className="mono">{d.modelo}</span> en el servidor Ollama
            {p.estado ? ` — ${p.estado}` : "…"}
            {p.pct != null && ` (${p.pct}% · ${p.descargado_mb} de ${p.total_mb} MB)`}
            <div className="progressbar" style={{ marginTop: 6 }}>
              <span style={{ width: `${p.pct || 0}%` }} />
            </div>
          </>
        )}
        {d.estado === "OK" && (
          <>
            <strong>{d.modelo}</strong> quedó descargado en el servidor y ya aparece en la lista de modelos.
          </>
        )}
        {d.estado === "ERROR" && <>No se pudo descargar {d.modelo}: {d.error}</>}
      </span>
      {!enCurso && (
        <button className="btn btn--ghost btn--sm" onClick={onCerrar} aria-label="Cerrar">
          <Icon name="x" />
        </button>
      )}
    </div>
  );
}
