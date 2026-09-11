/** Small formatting helpers shared by the panels. */

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/** 1530 -> "1.5 s", 12 -> "12 ms", null -> "—". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "—";
  if (ms < 1000) return String(Math.round(ms)) + " ms";
  if (ms < 60_000) return (ms / 1000).toFixed(ms < 10_000 ? 1 : 0) + " s";
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return minutes + "m " + seconds + "s";
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Local wall-clock time, "—" when the value is unusable. */
export function formatTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return date.toLocaleTimeString(undefined, { hour12: false });
}

export function formatDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return date.toLocaleString(undefined, { hour12: false });
}

export function formatRelative(value: string | null | undefined, now = Date.now()): string {
  const date = parseDate(value);
  if (!date) return "—";
  const seconds = Math.round((now - date.getTime()) / 1000);
  if (seconds < 60) return seconds <= 0 ? "just now" : seconds + "s ago";
  if (seconds < 3600) return Math.round(seconds / 60) + "m ago";
  if (seconds < 86_400) return Math.round(seconds / 3600) + "h ago";
  return Math.round(seconds / 86_400) + "d ago";
}

export function truncate(text: string, limit = 120): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length <= limit ? flat : flat.slice(0, Math.max(0, limit - 1)) + "…";
}

export function basename(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : path;
}

export function formatJson(value: unknown): string {
  if (value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "[unserialisable value]";
  }
}

export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : String(value);
}

export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Math.round(value * 100) + "%";
}

export function asText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "[unreadable value]";
  }
}

/** Risk levels come from the backend as plain strings. */
export function riskTone(risk: string): string {
  switch (risk.toLowerCase()) {
    case "high":
    case "critical":
      return "border-rose-800 bg-rose-950/40 text-rose-300";
    case "medium":
      return "border-amber-800 bg-amber-950/40 text-amber-300";
    case "low":
      return "border-emerald-900 bg-emerald-950/30 text-emerald-300";
    default:
      return "border-edge bg-panelAlt text-slate-400";
  }
}

export function statusTone(status: string): string {
  switch (status) {
    case "ok":
    case "ready":
    case "completed":
    case "done":
      return "border-emerald-900 bg-emerald-950/30 text-emerald-300";
    case "running":
    case "loading":
    case "started":
      return "border-sky-900 bg-sky-950/30 text-sky-300";
    case "failed":
    case "error":
    case "blocked":
      return "border-rose-900 bg-rose-950/40 text-rose-300";
    default:
      return "border-edge bg-panelAlt text-slate-400";
  }
}
