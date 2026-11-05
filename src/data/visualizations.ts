import {
  type Chunk,
  type ChunkStatus,
  type ProcessingDay,
  mockSnapshotDate,
} from "./days";

export interface VisualizationFilters {
  day: string;
  chunk: string;
  status: "all" | ChunkStatus;
  stage: number;
}
export interface ChartSelection {
  chunks: number[];
  range: [number, number] | null;
  status: ChunkStatus | null;
  stage: number | null;
}
export const defaultFilters = (
  day = mockSnapshotDate,
): VisualizationFilters => ({ day, chunk: "all", status: "all", stage: 0 });
export const emptySelection = (): ChartSelection => ({
  chunks: [],
  range: null,
  status: null,
  stage: null,
});
export const statusOrder: ChunkStatus[] = [
  "complete",
  "running",
  "failed",
  "pending",
];
export const statusColors: Record<ChunkStatus, string> = {
  complete: "var(--chart-green)",
  running: "var(--chart-blue)",
  failed: "var(--chart-amber)",
  pending: "var(--chart-muted)",
};

export function filterChunks(
  day: ProcessingDay | undefined,
  filters: VisualizationFilters,
) {
  return (day?.chunks ?? []).filter(
    (chunk) =>
      (filters.chunk === "all" || chunk.index === Number(filters.chunk)) &&
      (filters.status === "all" || chunk.status === filters.status) &&
      chunk.completedStages >= filters.stage,
  );
}

export function selectChunks(
  chunks: Chunk[],
  selection: ChartSelection,
  omit?: "chunk" | "status" | "stage",
) {
  return chunks.filter(
    (chunk) =>
      (omit === "chunk" ||
        ((!selection.chunks.length || selection.chunks.includes(chunk.index)) &&
          (!selection.range ||
            (chunk.index >= selection.range[0] &&
              chunk.index <= selection.range[1])))) &&
      (omit === "status" ||
        !selection.status ||
        chunk.status === selection.status) &&
      (omit === "stage" ||
        !selection.stage ||
        chunk.completedStages >= selection.stage),
  );
}

export function hasChartSelection(selection: ChartSelection) {
  return !!(
    selection.chunks.length ||
    selection.range ||
    selection.status ||
    selection.stage
  );
}

// Export a self-contained SVG: resolve theme colors/fonts before serializing.
export function downloadChart(
  svg: SVGSVGElement,
  filename: string,
  metadata: object,
) {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const originals = [svg, ...svg.querySelectorAll("*")];
  const copies = [clone, ...clone.querySelectorAll("*")];
  originals.forEach((node, index) => {
    const style = getComputedStyle(node);
    for (const property of [
      "fill",
      "stroke",
      "color",
      "font-family",
      "font-size",
      "font-weight",
      "opacity",
    ]) {
      (copies[index] as SVGElement).style.setProperty(
        property,
        style.getPropertyValue(property),
      );
    }
    copies[index].removeAttribute("tabindex");
  });
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const background = document.createElementNS(
    "http://www.w3.org/2000/svg",
    "rect",
  );
  background.setAttribute("width", "100%");
  background.setAttribute("height", "100%");
  background.setAttribute(
    "fill",
    getComputedStyle(document.documentElement)
      .getPropertyValue("--surface")
      .trim(),
  );
  clone.insertBefore(background, clone.firstChild);
  const info = document.createElementNS(
    "http://www.w3.org/2000/svg",
    "metadata",
  );
  info.textContent = JSON.stringify({
    ...metadata,
    theme: document.documentElement.dataset.theme,
  });
  clone.appendChild(info);
  const url = URL.createObjectURL(
    new Blob([new XMLSerializer().serializeToString(clone)], {
      type: "image/svg+xml;charset=utf-8",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
