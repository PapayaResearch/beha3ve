import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocsBody, DocsPage, DocsTitle } from "fumadocs-ui/page";
import { MarkdownCopyButton } from "fumadocs-ui/layouts/docs/page";
import defaultMdxComponents, { createRelativeLink } from "fumadocs-ui/mdx";
import { source } from "@/lib/source";
import { repository } from "@/lib/site";
import { Mermaid } from "@/components/mermaid";

type PageProps = { params: Promise<{ slug?: string[] }> };

export default async function Page({ params }: PageProps) {
  const { slug } = await params;
  const page = source.getPage(slug);
  if (!page) notFound();
  const MDX = page.data.body;

  return (
    <DocsPage
      id="main-content"
      className="research-page"
      toc={page.data.toc}
      footer={{ className: "docs-pagination" }}
      editOnGithub={{ owner: "PapayaResearch", repo: "wab", sha: "main", path: `website/content/docs/${page.path}` }}
    >
      <DocsTitle className="docs-title">{page.data.title}</DocsTitle>
      <div className="docs-page-actions">
        <MarkdownCopyButton markdownUrl={`/api/markdown/${page.slugs.join("/")}`} />
      </div>
      <DocsBody className="docs-body"><MDX components={{ ...defaultMdxComponents, Mermaid, a: createRelativeLink(source, page) }} /></DocsBody>
      <details className="source-files">
        <summary>Source files for this page</summary>
        <ul>
          {page.data.sources.map((path) => (
            <li key={path}><a href={`${repository}/blob/main/${path}`} target="_blank" rel="noreferrer">{path}</a></li>
          ))}
        </ul>
      </details>
    </DocsPage>
  );
}

export function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const page = source.getPage(slug);
  if (!page) notFound();
  return {
    title: page.data.title,
    description: page.data.description,
    alternates: { canonical: page.url },
    openGraph: { title: page.data.title, description: page.data.description, url: page.url },
  };
}
