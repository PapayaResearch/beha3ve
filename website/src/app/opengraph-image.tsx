import { readFile } from "node:fs/promises";
import { ImageResponse } from "next/og";

export const alt = "BEHA³VE. Behavioral Evaluation of How AI Agents Act in Variable Environments.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  const font = await readFile(new URL("../../node_modules/@fontsource/libre-franklin/files/libre-franklin-latin-800-normal.woff", import.meta.url));
  return new ImageResponse(
    <div style={{ display: "flex", flexDirection: "column", background: "#101010", width: "100%", height: "100%", padding: 64, color: "#f3f3f1", fontFamily: "Libre Franklin", fontWeight: 800 }}>
      <div style={{ display: "flex", fontSize: 112, letterSpacing: -6, marginBottom: 40 }}>BEHA³VE</div>
      <div style={{ display: "flex", fontSize: 38, lineHeight: 1.4 }}>Behavioral Evaluation of How</div>
      <div style={{ display: "flex", fontSize: 38, lineHeight: 1.4 }}>AI Agents Act in Variable Environments</div>
      <div style={{ display: "flex", fontSize: 24, marginTop: 58, color: "#a6a6a6" }}>A Python package for controlled experiments on AI agent behavior.</div>
    </div>,
    { ...size, fonts: [{ name: "Libre Franklin", data: font, weight: 800, style: "normal" }] },
  );
}
