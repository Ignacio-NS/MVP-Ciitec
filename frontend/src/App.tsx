import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { useTheme } from "./theme";
import { Icon } from "./components/icons";
import { iniciales, ribbonLeyenda } from "./components/ui";
import Login from "./views/Login";
import Cargar from "./views/Cargar";
import Briefings from "./views/Briefings";
import Briefing from "./views/Briefing";
import Fuente from "./views/Fuente";
import Auditoria from "./views/Auditoria";

const ROLES_AUDITORIA = ["Auditor", "Oficial de Seguridad", "Administrador del Sistema"];

function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const { tema, alternar } = useTheme();
  const esAuditor = user?.roles.some((r) => ROLES_AUDITORIA.includes(r));
  const nivel = (user?.nivel_habilitacion || "RESERVADO").toUpperCase();
  const navCls = ({ isActive }: { isActive: boolean }) => "topnav__item" + (isActive ? " is-active" : "");

  return (
    <div>
      <div className="ribbon" data-nivel={nivel}>
        <span className="ribbon__dot" />
        <span>{ribbonLeyenda(nivel)}</span>
        <span className="ribbon__dot" />
      </div>

      <header className="topbar">
        <div className="brand">
          <div className="brand__mark" aria-hidden="true">
            <Icon name="shield" />
          </div>
          <div>
            <div className="brand__name">★ Síntesis de SITREP</div>
            <div className="brand__sub">CIITEC</div>
          </div>
        </div>

        <nav className="topnav">
          <NavLink to="/cargar" className={navCls}>
            <Icon name="upload" />
            Cargar
          </NavLink>
          <NavLink to="/briefings" className={navCls}>
            <Icon name="list" />
            Historial de SITREPS
          </NavLink>
          {esAuditor && (
            <NavLink to="/auditoria" className={navCls}>
              <Icon name="shield-check" />
              Auditoría
            </NavLink>
          )}
        </nav>

        <div className="topbar__spacer" />

        <div className="themeswitch" title="Modo claro/oscuro">
          <Icon name="sun" className={"themeswitch__ico" + (tema === "light" ? " is-on" : "")} />
          <div
            className={"toggle" + (tema === "dark" ? " is-on" : "")}
            role="switch"
            aria-checked={tema === "dark"}
            aria-label="Modo oscuro"
            tabIndex={0}
            onClick={alternar}
            onKeyDown={(e) => {
              if (e.key === " " || e.key === "Enter") {
                e.preventDefault();
                alternar();
              }
            }}
          />
          <Icon name="moon" className={"themeswitch__ico" + (tema === "dark" ? " is-on" : "")} />
        </div>

        <div className="user">
          <div className="user__id">
            <div className="user__name">{user?.nombre}</div>
            <div className="user__role">
              {user?.roles?.[0] || "Usuario"} · habilitación <strong>{nivel}</strong>
            </div>
          </div>
          <div className="user__av">{iniciales(user?.nombre)}</div>
          <button className="btn btn--ghost btn--sm" onClick={logout} title="Salir">
            <Icon name="logout" />
            Salir
          </button>
        </div>
      </header>

      <main className="app">{children}</main>
    </div>
  );
}

function Protected({ children }: { children: React.ReactNode }) {
  const { user, cargando } = useAuth();
  const loc = useLocation();
  if (cargando) return <div className="page">Cargando…</div>;
  if (!user) return <Navigate to="/login" state={{ from: loc }} replace />;
  return <Layout>{children}</Layout>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/cargar" element={<Protected><Cargar /></Protected>} />
      <Route path="/briefings" element={<Protected><Briefings /></Protected>} />
      <Route path="/briefings/:id" element={<Protected><Briefing /></Protected>} />
      <Route path="/fuentes/:id" element={<Protected><Fuente /></Protected>} />
      <Route path="/auditoria" element={<Protected><Auditoria /></Protected>} />
      <Route path="*" element={<Navigate to="/briefings" replace />} />
    </Routes>
  );
}
