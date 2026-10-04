import { DocsLayout } from "fumadocs-ui/layouts/docs";
import { homepage } from "@/.source";
import { Logo } from "@/components/logo";
import { source } from "@/lib/source";
import { repository } from "@/lib/site";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <DocsLayout
      tree={source.pageTree}
      nav={{ title: <span className="brand"><Logo label={homepage[0].brand} /></span> }}
      links={[{ text: "Examples", url: "/docs/reference/example-catalog" }, { text: "Home", url: "/" }]}
      githubUrl={repository}
      themeSwitch={{ mode: "light-dark-system" }}
      sidebar={{ collapsible: true }}
    >
      {children}
    </DocsLayout>
  );
}
