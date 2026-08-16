/*
  Formatting.

  Every date in the interface is dd/mm/yyyy and every number carries an explicit sign
  when it represents a change. Precision follows magnitude, because an index at 6740 and
  a rate at 0.9312 need very different decimals to stay readable.
*/

export function decimalsFor(value) {
  const size = Math.abs(Number(value) || 0);
  if (size >= 10) return 2;
  if (size >= 1) return 3;
  return 4;
}

export function price(value, decimals) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "\u2013";
  const places = decimals === undefined ? decimalsFor(value) : decimals;
  return Number(value).toLocaleString("en-GB", {
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  });
}

export function signed(value, decimals) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "\u2013";
  const places = decimals === undefined ? decimalsFor(value) : decimals;
  const sign = Number(value) > 0 ? "+" : "";
  return sign + Number(value).toLocaleString("en-GB", {
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  });
}

export function percent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "\u2013";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

export function ratioAsPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "\u2013";
  return `${Math.round(Number(value) * 100)}%`;
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/**
 * The day of the week for an ISO date.
 *
 * Parsed as UTC on purpose. Reading it on the local clock would shift the day by one for
 * anyone west of Greenwich, and a date that names the wrong weekday is worse than a date
 * that names none.
 */
export function weekday(iso) {
  if (!iso) return "";
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? "" : WEEKDAYS[d.getUTCDay()];
}

/** ISO yyyy-mm-dd from the API into dd/mm/yyyy. */
export function date(iso) {
  if (!iso) return "\u2013";
  const [y, m, d] = String(iso).slice(0, 10).split("-");
  if (!y || !m || !d) return String(iso);
  return `${d}/${m}/${y}`;
}

/** Short axis form, dd/mm, so ten labels fit without crowding. */
export function dateShort(iso) {
  if (!iso) return "";
  const [, m, d] = String(iso).slice(0, 10).split("-");
  return m && d ? `${d}/${m}` : "";
}

export const direction = (value) => (Number(value) > 0 ? "up" : Number(value) < 0 ? "down" : "");
