import { useEffect, useState, type RefObject } from "react";

// Keep labels readable rather than shrinking a desktop-sized chart on phones.
export function useSvgWidth(
  ref: RefObject<SVGSVGElement | null>,
  initial: number,
) {
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    const svg = ref.current;
    if (!svg) return;
    const measure = () =>
      setWidth(Math.max(300, Math.round(svg.getBoundingClientRect().width)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(svg);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}
