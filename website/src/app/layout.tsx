import type { Metadata } from "next";
import { RootProvider } from "fumadocs-ui/provider/next";
import { siteUrl } from "@/lib/site";
import "@fontsource/libre-franklin/latin-400.css";
import "@fontsource/libre-franklin/latin-500.css";
import "@fontsource/libre-franklin/latin-600.css";
import "@fontsource/libre-franklin/latin-700.css";
import "@fontsource/libre-franklin/latin-800.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: siteUrl,
  title: { default: "BEHA³VE | Agent behavior experiments", template: "%s | BEHA³VE" },
  description: "BEHA³VE is a Python package for controlled experiments on AI agent behavior. Configure conditions and compare recorded observations, actions, and outcomes.",
  alternates: { canonical: "/" },
  openGraph: { type: "website", siteName: "BEHA³VE", images: ["/opengraph-image"] },
  twitter: { card: "summary_large_image", images: ["/opengraph-image"] },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <a className="skip-link" href="#main-content">Skip to content</a>
        <RootProvider theme={{ defaultTheme: "system", enableSystem: true, storageKey: "beha3ve-theme", hotKey: false }}>{children}</RootProvider>
      </body>
    </html>
  );
}
