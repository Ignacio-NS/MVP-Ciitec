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

  getAudit: () => request("/audit"),
  verificarAudit: () => request("/audit/verificar"),
};
