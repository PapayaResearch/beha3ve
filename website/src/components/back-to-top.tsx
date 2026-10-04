"use client";

import type { ReactNode } from "react";
import { ArrowUp } from "lucide-react";

export function BackToTop({ children }: { children: ReactNode }) {
  return (
    <button
      type="button"
      className="back-to-top"
      onClick={() => {
        document.getElementById("main-content")?.focus({ preventScroll: true });
        window.scrollTo({
          top: 0,
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
        });
      }}
    >
      {children}<ArrowUp aria-hidden="true" size={16} />
    </button>
  );
}
