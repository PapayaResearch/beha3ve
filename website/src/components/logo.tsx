import { readFileSync } from "node:fs";
import { join } from "node:path";
import { useId } from "react";
import { AnimatedLogo } from "@/components/animated-logo";

export function Logo({ label, animate = false }: { label: string; animate?: boolean }) {
  const svg = readFileSync(join(process.cwd(), "assets", "logo.svg"), "utf8");
  const prefix = useId().replaceAll(":", "");
  const markup = svg
    .replace("<svg ", '<svg aria-hidden="true" focusable="false" ')
    .replace(/id="([^"]+)"/g, `id="${prefix}-$1"`)
    .replace(/url\(#([^)]+)\)/g, `url(#${prefix}-$1)`);

  return <AnimatedLogo label={label} markup={markup} animate={animate} />;
}
