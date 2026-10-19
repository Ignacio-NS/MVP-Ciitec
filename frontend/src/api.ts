// Cliente de API. Maneja el token JWT y la renovación por sesión sliding
// (cabecera X-Session-Token que emite el backend en cada respuesta).

const API_BASE = (import.meta as any).env.VITE_API_URL || "/api";

export function wsUrl(taskId: string): string {
  // El JWT viaja como query param: la API WebSocket del navegador no permite
  // cabeceras personalizadas. El backend lo valida antes de aceptar (RNF-001).
  const token = getToken();
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  const env = (import.meta as any).env.VITE_WS_URL;
  if (env) return `${env}/task/${taskId}${qs}`;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/task/${taskId}${qs}`;
}

export function getToken(): string | null {
  return localStorage.getItem("token");
}
export function setToken(t: string | null) {
  if (t) localStorage.setItem("token", t);
  else localStorage.removeItem("token");
}

async function request(path: string, opts: RequestInit = {}, isForm = false): Promise<any> {
  const headers: Record<string, string> = { ...(opts.headers as any) };
  if (!isForm) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(API_BASE + path, { ...opts, headers });

  const refreshed = res.headers.get("X-Session-Token");
  if (refreshed) setToken(refreshed);

  if (res.status === 401) {
    setToken(null);
    if (location.pathname !== "/login") location.href = "/login";
    throw new Error("Sesión expirada");
  }
  if (!res.ok) throw new Error((await res.text()) || res.statusText);

  const ct = res.headers.get("Content-Type") || "";
  return ct.includes("application/json") ? res.json() : res.blob();
}

export const api = {
  login: (username: string, password: string) =>
    request("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  me: () => request("/auth/me"),

  listFuentes: () => request("/fuentes"),
  getFuenteTexto: (id: string) => request(`/fuentes/${id}/texto`),
  upload: (files: File[], nivel = "RESERVADO") => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("nivel_clasificacion", nivel);
    return request("/fuentes", { method: "POST", body: fd }, true);
  },

  createBriefing: (titulo: string, fuente_ids?: string[]) =>
    request("/briefings", { method: "POST", body: JSON.stringify({ titulo, fuente_ids }) }),
  listBriefings: () => request("/briefings"),
  getBriefing: (id: string) => request(`/briefings/${id}`),
  getVersiones: (id: string) => request(`/briefings/${id}/versiones`),
  getVersion: (id: string, numero: number) => request(`/briefings/${id}/versiones/${numero}`),
  editarVersion: (id: string, contenido: any, base_version?: number | null, comentario?: string) =>
    request(`/briefings/${id}/versiones`, {
      method: "POST",
      body: JSON.stringify({ contenido, base_version, comentario }),
    }),
  getDiff: (id: string, a: number, b: number) => request(`/briefings/${id}/diff/${a}/${b}`),
  reconstruir: (id: string, at: string) => request(`/briefings/${id}/versiones?at=${encodeURIComponent(at)}`),
  getInconsistencias: (id: string) => request(`/briefings/${id}/inconsistencias`),
  getTrazabilidad: (id: string) => request(`/briefings/${id}/trazabilidad`),
  aprobar: (versionId: string) => request(`/briefings/versiones/${versionId}/aprobar`, { method: "POST" }),
  exportar: (id: string, formato: string, version_id?: string | null): Promise<Blob> =>
    request(`/briefings/${id}/exportar`, {
      method: "POST",
      body: JSON.stringify({ formato, version_id }),
    }) as Promise<Blob>,

  // Hojas adicionales del reporte
  subirImagenHoja: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request(`/briefings/${id}/hojas/imagen`, { method: "POST", body: fd }, true);
  },
  subirDocumentoHoja: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request(`/briefings/${id}/hojas/documento`, { method: "POST", body: fd }, true);
  },
  imagenHoja: (id: string, objeto: string): Promise<Blob> =>
    request(`/briefings/${id}/hojas/imagen?objeto=${encodeURIComponent(objeto)}`) as Promise<Blob>,
  completarHoja: (id: string, hoja: any) =>
    request(`/briefings/${id}/hojas/completar`, { method: "POST", body: JSON.stringify(hoja) }),

  getAudit: () => request("/audit"),
  verificarAudit: () => request("/audit/verificar"),

  // Motor de IA (Administrador del Sistema; Auditor/Seguridad solo lectura)
  llmProveedores: () => request("/llm/proveedores"),
  llmConfig: () => request("/llm/config"),
  llmHistorial: () => request("/llm/historial"),
  llmProbar: (cfg?: any) =>
    request("/llm/probar", { method: "POST", body: cfg ? JSON.stringify(cfg) : undefined }),
  llmActivar: (cfg: any) => request("/llm/config", { method: "PUT", body: JSON.stringify(cfg) }),
  llmVolverEnv: () => request("/llm/config", { method: "DELETE" }),
  llmModelos: (cfg: any) => request("/llm/modelos", { method: "POST", body: JSON.stringify(cfg) }),
  llmDisponibilidad: (cfg: any) => request("/llm/disponibilidad", { method: "POST", body: JSON.stringify(cfg) }),
  llmVerificar: (cfg?: any) =>
    request("/llm/verificar", { method: "POST", body: cfg ? JSON.stringify(cfg) : undefined }),
  llmDescargar: (cfg: any) => request("/llm/descargar", { method: "POST", body: JSON.stringify(cfg) }),
  llmTarea: (id: string) => request(`/llm/tareas/${encodeURIComponent(id)}`),
  info: () => request("/info"),
};

/** Mensaje legible de un error de la API ({"detail": "..."} de FastAPI). */
export function mensajeError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  try {
    const d = JSON.parse(raw).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x: any) => x.msg).join("; ");
  } catch {
    /* no era JSON */
  }
  return raw;
}
