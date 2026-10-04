"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { ThemeSwitch } from "fumadocs-ui/layouts/shared/slots/theme-switch";
import { Menu, X } from "lucide-react";

export function SiteHeader({ brand, navigation }: {
  brand: string;
  navigation: { label: string; href: string }[];
}) {
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);

  return (
    <header className="site-header" onKeyDown={(event) => {
      if (event.key === "Escape" && open) {
        setOpen(false);
        toggle.current?.focus();
      }
    }}>
      <div className="site-container header-inner">
        <Link className="landing-brand" href="/" aria-label={`${brand} home`}>{brand}</Link>
        <button
          ref={toggle}
          className="site-menu-toggle"
          type="button"
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          aria-controls="site-navigation"
          onClick={() => setOpen(!open)}
        >
          {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        </button>
        <nav id="site-navigation" aria-label="Main navigation" data-open={open}>
          {navigation.map(({ label, href }) => (
            <Link key={href} href={href} onClick={() => setOpen(false)}>
              {label}
            </Link>
          ))}
          <ThemeSwitch className="site-theme-switch" mode="light-dark-system" role="group" aria-label="Color theme" />
        </nav>
      </div>
    </header>
  );
}
