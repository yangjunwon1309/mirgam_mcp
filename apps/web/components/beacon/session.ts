const KEY = "mirgam.beacon.ui";
export function readUi(): Record<string, unknown> {
  try { const value: unknown = JSON.parse(sessionStorage.getItem(KEY) ?? "{}"); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; } catch { return {}; }
}
export function writeUi(values: Record<string, unknown>): void {
  try { sessionStorage.setItem(KEY, JSON.stringify({ ...readUi(), ...values })); } catch { /* Storage may be unavailable. */ }
}
