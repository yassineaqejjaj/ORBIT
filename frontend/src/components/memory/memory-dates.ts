/** Conversions between API ISO datetimes and `<input type="date">` values (local calendar day). */
import { toDate } from "@/lib/format";

const pad = (n: number) => String(n).padStart(2, "0");

/** ISO datetime → "YYYY-MM-DD" (local day), "" when empty/invalid. */
export function isoToDateInput(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return "";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** "YYYY-MM-DD" → ISO datetime at the start (00:00) or end (23:59:59) of that local day. */
export function dateInputToIso(value: string, edge: "start" | "end" = "start"): string {
  const [y, m, d] = value.split("-").map((part) => Number.parseInt(part, 10));
  const date =
    edge === "start"
      ? new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1, 0, 0, 0, 0)
      : new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1, 23, 59, 59, 0);
  return date.toISOString();
}

/** Today as "YYYY-MM-DD" (local). */
export function todayInput(): string {
  return isoToDateInput(new Date().toISOString());
}
