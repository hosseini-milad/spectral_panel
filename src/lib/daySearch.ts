import { normalizeSearch } from "../data/days";
import { isISODate } from "./dayNavigation";

// Intl supplies the same Persian calendar already used by the visible calendar.
function persianKey(timestamp: number) {
  const values = Object.fromEntries(
    new Intl.DateTimeFormat("en-US-u-ca-persian", {
      timeZone: "UTC",
      year: "numeric",
      month: "numeric",
      day: "numeric",
    })
      .formatToParts(new Date(timestamp))
      .map((part) => [part.type, Number(part.value)]),
  );
  return values.year * 10000 + values.month * 100 + values.day;
}
function persianDate(year: number, month: number, day: number) {
  const target = year * 10000 + month * 100 + day;
  let lower = Math.floor(Date.UTC(year + 621, 0, 1) / 86400000);
  let upper = Math.floor(Date.UTC(year + 622, 11, 31) / 86400000);
  while (lower < upper) {
    const middle = Math.floor((lower + upper) / 2);
    if (persianKey(middle * 86400000) < target) lower = middle + 1;
    else upper = middle;
  }
  if (persianKey(lower * 86400000) !== target)
    throw new Error("تاریخ شمسی معتبر نیست.");
  return new Date(lower * 86400000).toISOString().slice(0, 10);
}
export function daySearch(value: string): Record<string, string> {
  const normalized = normalizeSearch(value)
    .replaceAll("/", "-")
    .replaceAll(".", "-");
  if (!normalized) return {};
  const match = /^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?-?$/.exec(normalized);
  if (!match)
    throw new Error(
      "تاریخ شمسی یا میلادی را به صورت سال، سال/ماه یا سال/ماه/روز وارد کنید.",
    );
  const year = Number(match[1]),
    month = match[2] ? Number(match[2]) : undefined,
    day = match[3] ? Number(match[3]) : undefined;
  if (year >= 1200 && year <= 1699) {
    const from = persianDate(year, month ?? 1, day ?? 1);
    const after = day
      ? null
      : month
        ? persianDate(
            month === 12 ? year + 1 : year,
            month === 12 ? 1 : month + 1,
            1,
          )
        : persianDate(year + 1, 1, 1);
    return {
      date_from: from,
      date_to: after
        ? new Date(new Date(`${after}T12:00:00Z`).getTime() - 86400000)
            .toISOString()
            .slice(0, 10)
        : from,
    };
  }
  const prefix = `${year}${month === undefined ? "" : `-${String(month).padStart(2, "0")}`}${day === undefined ? "" : `-${String(day).padStart(2, "0")}`}`;
  if (
    !isISODate(
      `${year}-${String(month ?? 1).padStart(2, "0")}-${String(day ?? 1).padStart(2, "0")}`,
    )
  )
    throw new Error("تاریخ میلادی معتبر نیست.");
  return { q: prefix };
}
