// Componentes y helpers compartidos: semántica de clasificación, estados de
// briefing y tipos de inconsistencia. Centralizan el código de color para que
// sea consistente en toda la app (RNF-006).

const NIVEL: Record<string, { cls: string; ico: string; label: string }> = {
  PUBLICO: { cls: "pub", ico: "●", label: "Público" },
  RESERVADO: { cls: "res", ico: "▲", label: "Reservado" },
  SECRETO: { cls: "sec", ico: "■", label: "Secreto" },
};

const RIBBON_LEYENDA: Record<string, string> = {
  PUBLICO: "PÚBLICO — Difusión autorizada",
  RESERVADO: "RESERVADO — Documento de circulación restringida",
  SECRETO: "SECRETO — Acceso limitado a personal habilitado",
};

export function nivelMeta(nivel?: string) {
  return NIVEL[(nivel || "").toUpperCase()] || NIVEL.RESERVADO;
}
export function ribbonLeyenda(nivel?: string) {
  return RIBBON_LEYENDA[(nivel || "").toUpperCase()] || RIBBON_LEYENDA.RESERVADO;
}

export function Badge({ nivel, lg }: { nivel?: string; lg?: boolean }) {
  const n = nivelMeta(nivel);
  return (
    <span className={`badge badge--${n.cls}${lg ? " badge--lg" : ""}`}>
      {n.ico} {n.label}
    </span>
  );
}

const ESTADO: Record<string, { cls: string; label: string }> = {
  BORRADOR: { cls: "borrador", label: "Borrador" },
  GENERANDO: { cls: "generando", label: "Generando" },
  LISTO: { cls: "listo", label: "Listo" },
  APROBADO: { cls: "aprobado", label: "Aprobado" },
};

export function Pill({ estado }: { estado?: string }) {
  const e = ESTADO[(estado || "").toUpperCase()] || ESTADO.BORRADOR;
  return (
    <span className={`pill pill--${e.cls}`}>
      <span className="pill__dot" />
      {e.label}
    </span>
  );
}

const INC_MAP: Record<string, string> = {
  DUPLICADO: "dup",
  CONTRADICCION: "con",
  DESACTUALIZADO: "des",
  INCOMPLETO: "inc",
};

export function Tag({ tipo }: { tipo?: string }) {
  const t = (tipo || "").toUpperCase();
  return <span className={`tag tag--${INC_MAP[t] || "inc"}`}>{t || "INCOMPLETO"}</span>;
}

// ---------- formato ----------
// El backend entrega los timestamps en UTC (isoformat con offset). Aquí se
// convierten a hora oficial de Chile (America/Santiago) para mostrarlos, en el
// mismo formato "YYYY-MM-DD HH:mm" que usa toda la app.
export function fmtFecha(iso?: string | null): string {
  if (!iso) return "—";
  // Si el string no trae designador de zona, se asume UTC.
  let s = iso;
  if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s = s.replace(" ", "T") + "Z";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 16).replace("T", " ");
  const p = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Santiago",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .formatToParts(d)
    .reduce((acc, x) => ((acc[x.type] = x.value), acc), {} as Record<string, string>);
  const hora = p.hour === "24" ? "00" : p.hour; // algunos motores devuelven 24 para medianoche
  return `${p.year}-${p.month}-${p.day} ${hora}:${p.minute}`;
}

export function fmtTamano(bytes: number): string {
  if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1).replace(".", ",") + " MB";
  if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
  return bytes + " B";
}

export function iniciales(nombre?: string): string {
  if (!nombre) return "··";
  const p = nombre.trim().split(/\s+/);
  return ((p[0]?.[0] || "") + (p[1]?.[0] || p[0]?.[1] || "")).toUpperCase();
}

// Tipo de archivo -> chip (color + etiqueta corta) según extensión.
export function tipoArchivo(nombre: string): { cls: string; label: string } {
  const ext = nombre.split(".").pop()?.toLowerCase() || "";
  if (ext === "pdf") return { cls: "ft-pdf", label: "PDF" };
  if (["doc", "docx", "rtf", "odt"].includes(ext)) return { cls: "ft-doc", label: "DOC" };
  if (["xls", "xlsx", "csv", "ods"].includes(ext)) return { cls: "ft-xls", label: "XLS" };
  if (["msg", "eml"].includes(ext)) return { cls: "ft-mail", label: "EML" };
  return { cls: "ft-txt", label: ext ? ext.slice(0, 3).toUpperCase() : "TXT" };
}
