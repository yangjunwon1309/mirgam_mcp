export type CsvColumn = { key: string; label: string };
function cell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\r\n]/.test(text) ? "\"" + text.replace(/"/g, "\"\"") + "\"" : text;
}
export function toCsv(columns: CsvColumn[], rows: object[]): string {
  const header = columns.map((column) => cell(column.label)).join(",");
  const body = rows.map((row) => {
    const values = row as Record<string, unknown>;
    return columns.map((column) => cell(values[column.key])).join(",");
  }).join("\r\n");
  return "\uFEFF" + header + (rows.length ? "\r\n" + body : "");
}
export function downloadCsv(name: string, text: string): void {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = name; anchor.style.display = "none";
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  URL.revokeObjectURL(url);
}
