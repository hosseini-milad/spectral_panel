export function isISODate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T12:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.getUTCFullYear() >= 1 &&
    parsed.toISOString().slice(0, 10) === value
  );
}

export const dayDetailsPath = (date: string) =>
  `/days?day=${encodeURIComponent(date)}`;

export function parseChunkIndex(value: string | null): number | undefined {
  if (value === null || !/^(0|[1-9]\d*)$/.test(value)) return undefined;
  const index = Number(value);
  return Number.isSafeInteger(index) && index <= 2147483647 ? index : undefined;
}
export const chunkDetailsPath = (date: string, chunk: number) =>
  `${dayDetailsPath(date)}&chunk=${chunk}`;
export const inspectionPath = (date: string, chunk?: number) =>
  `/visualizations?${new URLSearchParams({ day: date, ...(chunk !== undefined ? { chunk: String(chunk) } : {}) })}`;
