import type { Metadata } from "next";
import { Copy } from "lucide-react";
import defaultMdxComponents from "fumadocs-ui/mdx";
import { homepage } from "@/.source";
import { Logo } from "@/components/logo";
import { SiteHeader } from "@/components/site-header";
import { BackToTop } from "@/components/back-to-top";

const home = homepage[0];

export const metadata: Metadata = {
  title: { absolute: home.title },
  description: home.description,
  alternates: { canonical: "/" },
};

export default function Home() {
  const MDX = home.body;

  return (
    <div className="landing">
      <SiteHeader brand={home.brand} navigation={home.navigation} />

      <main id="main-content" className="landing-content" tabIndex={-1}>
        <MDX components={{ ...defaultMdxComponents, h2: "h2", h3: "h3", Logo, Copy, BackToTop }} />
      </main>
    </div>
  );
}
