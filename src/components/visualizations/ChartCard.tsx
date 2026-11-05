import { useRef, useState, type ReactNode, type RefObject } from "react";
import { Download, MousePointer2 } from "lucide-react";
import { downloadChart } from "../../data/visualizations";

export function ChartCard({
  id,
  number,
  title,
  description,
  children,
  metadata,
  footer,
  wide = false,
}: {
  id: string;
  number: string;
  title: string;
  description: string;
  children: (ref: RefObject<SVGSVGElement | null>) => ReactNode;
  metadata: object;
  footer: string;
  wide?: boolean;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [downloaded, setDownloaded] = useState(false);
  return (
    <section
      className={`viz-card chart-card${wide ? " chart-wide" : ""}`}
      aria-labelledby={`${id}-title`}
    >
      <div className="chart-card-heading">
        <div>
          <span className="chart-index" aria-hidden="true">
            {number}
          </span>
          <div>
            <h2 id={`${id}-title`}>{title}</h2>
            <p>{description}</p>
          </div>
        </div>
        <button
          className="chart-download icon-button"
          aria-label={`دانلود SVG ${title}`}
          onClick={() => {
            if (svg.current) {
              downloadChart(svg.current, `mock-${id}.svg`, metadata);
              setDownloaded(true);
            }
          }}
          title="دانلود SVG ماک"
        >
          <Download size={17} />
        </button>
      </div>
      <div className="chart-content">{children(svg)}</div>
      <div className="chart-card-footer">
        <span>
          <MousePointer2 size={12} />
          {footer}
        </span>
        <span role="status">
          {downloaded ? "SVG ماک دانلود شد" : "دادهٔ نمایشی"}
        </span>
      </div>
    </section>
  );
}
