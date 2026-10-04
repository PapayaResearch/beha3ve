"use client";

import { useLayoutEffect, useRef } from "react";

export function AnimatedLogo({ label, markup, animate }: { label: string; markup: string; animate: boolean }) {
  const container = useRef<HTMLSpanElement>(null);
  const drawing = useRef(false);

  useLayoutEffect(() => {
    const element = container.current!;
    const svg = element.querySelector<SVGSVGElement>("svg")!;
    const paths = Array.from(svg.querySelectorAll<SVGPathElement>(":scope > path[stroke]"));
    const restore: (() => void)[] = [];
    const updates: ((progress: number) => void)[] = [];
    let frame = 0;
    const shouldAnimate = animate && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!shouldAnimate) {
      if (animate) element.dataset.logoComplete = "true";
      return;
    }
    element.dataset.logoComplete = "false";
    drawing.current = true;

    function temporaryAttribute(node: SVGElement, name: string, value: number | string) {
      const previous = node.getAttribute(name);
      node.setAttribute(name, String(value));
      restore.push(() => {
        if (previous === null) node.removeAttribute(name);
        else node.setAttribute(name, previous);
      });
    }

    function reset() {
      cancelAnimationFrame(frame);
      restore.forEach((undo) => undo());
      restore.length = 0;
      drawing.current = false;
    }

    paths.forEach((path) => {
      const length = path.getTotalLength();
      temporaryAttribute(path, "stroke-dasharray", length + " " + length);
      temporaryAttribute(path, "stroke-dashoffset", length);
      updates.push((progress) => path.setAttribute("stroke-dashoffset", String(length * (1 - progress))));
    });

    Array.from(svg.querySelectorAll<SVGPathElement>(":scope > path:not([stroke])")).forEach((path) => {
      const bounds = path.getBBox();
      if (bounds.x < 30) return;
      temporaryAttribute(path, "opacity", 0);
      const arrival = bounds.x > 1300 ? 0.96 : 0.55;
      updates.push((progress) => path.setAttribute("opacity", String(Math.max(0, Math.min(1, (progress - arrival) / 0.04)))));
    });

    updates.forEach((update) => update(0));
    const start = performance.now();

    function tick(now: number) {
      const t = Math.max(0, Math.min(1, (now - start) / 3600));
      const progress = t * t * (3 - 2 * t);
      updates.forEach((update) => update(progress));
      if (progress < 1) frame = requestAnimationFrame(tick);
      else {
        reset();
        element.dataset.logoComplete = "true";
      }
    }

    frame = requestAnimationFrame(tick);
    return () => {
      reset();
      element.dataset.logoComplete = "false";
    };
  }, [markup, animate]);

  useLayoutEffect(() => {
    if (!animate) return;
    const element = container.current!;
    const svg = element.querySelector<SVGSVGElement>("svg")!;
    const paths = Array.from(svg.querySelectorAll<SVGPathElement>(":scope > path[stroke]"));
    let lines: { path: SVGPathElement; opacity: string; points: DOMPoint[] }[] = [];
    let selected = -1;
    let pending = -1;
    let selectionTimer = 0;

    function select(index: number) {
      if (index === selected) return;
      selected = index;
      const firstFill = svg.querySelector(":scope > path:not([stroke])");
      paths.forEach((path) => svg.insertBefore(path, firstFill));
      if (index >= 0) svg.insertBefore(paths[index], firstFill);
      lines.forEach((line, i) => {
        line.path.style.opacity = index < 0 ? line.opacity : i === index ? "1" : "0.07";
      });
    }

    function move(event: PointerEvent) {
      if (event.pointerType === "touch" || drawing.current) return;
      if (lines.length === 0) {
        lines = paths.map((path) => {
          const length = path.getTotalLength();
          const count = Math.min(512, Math.ceil(length / 8));
          return {
            path,
            opacity: path.style.opacity,
            points: Array.from({ length: count + 1 }, (_, index) => path.getPointAtLength(length * index / count)),
          };
        });
      }
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM()!.inverse());
      let nearest = 0;
      let distance = Infinity;
      lines.forEach((line, index) => {
        for (let i = 1; i < line.points.length; i++) {
          const a = line.points[i - 1];
          const b = line.points[i];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const squaredLength = dx * dx + dy * dy;
          const t = squaredLength === 0 ? 0 : Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / squaredLength));
          const squaredDistance = (point.x - a.x - t * dx) ** 2 + (point.y - a.y - t * dy) ** 2;
          if (squaredDistance < distance) {
            distance = squaredDistance;
            nearest = index;
          }
        }
      });
      if (nearest === pending) return;
      window.clearTimeout(selectionTimer);
      pending = nearest;
      if (nearest !== selected) {
        selectionTimer = window.setTimeout(() => select(nearest), 60);
      }
    }

    function leave() {
      window.clearTimeout(selectionTimer);
      pending = -1;
      select(-1);
    }

    element.addEventListener("pointermove", move);
    element.addEventListener("pointerleave", leave);
    return () => {
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerleave", leave);
      leave();
    };
  }, [markup, animate]);

  return <span ref={container} className="brand-logo" role="img" aria-label={label} data-logo-complete={animate ? "false" : undefined} dangerouslySetInnerHTML={{ __html: markup }} />;
}
