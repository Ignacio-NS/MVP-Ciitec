import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Icon } from "../components/icons";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [u, setU] = useState("operaciones");
  const [p, setP] = useState("");
  const [err, setErr] = useState(false);
  const [cargando, setCargando] = useState(false);
  const online = typeof navigator === "undefined" ? true : navigator.onLine;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(false);
    setCargando(true);
    try {
      await login(u, p);
      nav("/briefings");
    } catch {
      setErr(true);
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className="login">
      <aside className="login__aside">
        <div>
          <div className="login__crest">
            <Icon name="shield-mark" strokeWidth={1.6} />
          </div>
          <h1 className="login__headline">
            ★ Acceso
            <br />
            institucional
          </h1>
          <p className="login__tagline">
            Sistema de Síntesis Automática de SITREP — Centro de Investigación e Innovación
            Tecnológica del Ejército (CIITEC).
          </p>
        </div>
        <div className="login__legal">
          SISTEMA DE INFORMACIÓN CLASIFICADO. El acceso está restringido a personal autorizado. Toda
          actividad es registrada y auditada de forma inmutable. El uso no autorizado constituye una
          falta grave conforme a la reglamentación institucional vigente.
        </div>
      </aside>

      <div className="login__main">
        <form className="login__form" onSubmit={submit}>
          <div className="brand" style={{ marginBottom: "var(--sp-6)" }}>
            <div className="brand__mark">
              <Icon name="shield" />
            </div>
            <div>
              <div className="brand__name">Síntesis de SITREP</div>
              <div className="brand__sub">CIITEC</div>
            </div>
          </div>

          <h2 style={{ fontSize: "var(--tx-xl)", fontWeight: 700, marginBottom: 6 }}>
            Ingresar al sistema
          </h2>
          <p className="page-sub" style={{ marginBottom: "var(--sp-6)" }}>
            Use sus credenciales institucionales.
          </p>

          <div className="login__notice">
            <Icon name="shield" />
            <span>
              Conexión cifrada · estación habilitada. Estado de red:{" "}
              <strong>{online ? "en línea" : "sin conexión"}</strong>.
            </span>
          </div>

          {err && (
            <div className="alert alert--err">
              <Icon name="alert-circle" />
              Credenciales inválidas. Verifique usuario y contraseña.
            </div>
          )}

          <div className="field" style={{ marginBottom: "var(--sp-4)" }}>
            <label className="label" htmlFor="usr">
              Usuario <span className="req">*</span>
            </label>
            <input
              className="input"
              id="usr"
              value={u}
              onChange={(e) => setU(e.target.value)}
              autoComplete="username"
              autoFocus
            />
          </div>
          <div className="field" style={{ marginBottom: "var(--sp-6)" }}>
            <label className="label" htmlFor="pwd">
              Contraseña <span className="req">*</span>
            </label>
            <input
              className={"input" + (err ? " input--err" : "")}
              id="pwd"
              type="password"
              value={p}
              onChange={(e) => {
                setP(e.target.value);
                setErr(false);
              }}
              autoComplete="current-password"
            />
          </div>

          <button className="btn btn--primary btn--lg btn--block" disabled={cargando}>
            {cargando ? (
              <>
                <span className="spin" /> Validando…
              </>
            ) : (
              "Ingresar"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
