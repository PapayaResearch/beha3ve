import { renderMermaidSVG } from "beautiful-mermaid";
import { useId } from "react";

function curveEdge(points: string): string {
  const vertices = points.trim().split(/\s+/).map((point) => point.split(",").map(Number));
  let path = `M ${vertices[0].join(" ")}`;
  for (let i = 1; i < vertices.length - 1; i++) {
    const [x, y] = vertices[i];
    const [px, py] = vertices[i - 1];
    const [nx, ny] = vertices[i + 1];
    const incoming = Math.hypot(x - px, y - py);
    const outgoing = Math.hypot(nx - x, ny - y);
    if (incoming === 0 || outgoing === 0) continue;
    const radius = Math.min(12, incoming / 2, outgoing / 2);
    path += ` L ${x + (px - x) * radius / incoming} ${y + (py - y) * radius / incoming}`;
    path += ` Q ${x} ${y} ${x + (nx - x) * radius / outgoing} ${y + (ny - y) * radius / outgoing}`;
  }
  return `${path} L ${vertices[vertices.length - 1].join(" ")}`;
}

function renderDiagram(chart: string, id: string): string {
  return renderMermaidSVG(chart, {
    bg: "var(--paper)",
    fg: "var(--ink)",
    line: "var(--diagram-line)",
    accent: "var(--diagram-accent)",
    muted: "var(--diagram-text)",
    surface: "var(--paper)",
    border: "var(--diagram-border)",
    font: "Libre Franklin",
    transparent: true,
    padding: 12,
    nodeSpacing: 16,
    layerSpacing: 28,
  })
    .replace(/@import url\([^;]+;/g, "")
    .replace(/\btext \{/g, ".docs-diagram text {")
    .replace(/\bsvg \{/g, ".docs-diagram svg {")
    .replace(/<polyline ([^>]*class="edge"[^>]*) points="([^"]+)"/g,
      (_, attributes: string, points: string) => `<path ${attributes} d="${/^flowchart TD/m.test(chart) ? `M ${points.trim().split(/\s+/)[0]} L ${points.trim().split(/\s+/).at(-1)}` : curveEdge(points)}"`)
    .replace(/(<marker\b[^>]*>\s*)<polygon([^>]+)\/>/g,
      (_, marker: string, attributes: string) => `${marker}<polyline${attributes.replace(/fill="[^"]*"/, 'fill="none"')} />`)
    .replace(/ id="([^"]+)"/g, ` id="${id}-$1"`)
    .replace(/url\(#([^)]+)\)/g, `url(#${id}-$1)`);

}

export function Mermaid({ chart }: { chart: string }) {
  const id = useId().replaceAll(":", "");
  const svg = renderDiagram(chart, id);
  const verticalChart = chart.replace(/flowchart LR/, "flowchart TD");
  const mobileSvg = verticalChart !== chart ? renderDiagram(verticalChart, `${id}-mobile`) : null;

  return (
    <div
      className="docs-diagram"
      role="region"
      aria-label="Diagram"
      tabIndex={0}
    >
      <div className={mobileSvg ? "diagram-desktop" : undefined} dangerouslySetInnerHTML={{ __html: svg }} />
      {mobileSvg && <div className="diagram-mobile" dangerouslySetInnerHTML={{ __html: mobileSvg }} />}
    </div>
  );
}
