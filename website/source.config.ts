import { defineCollections, defineConfig, defineDocs } from "fumadocs-mdx/config";
import { remarkMdxMermaid } from "fumadocs-core/mdx-plugins";
import { z } from "zod";

const link = z.object({ label: z.string(), href: z.string() });

export const homepage = defineCollections({
  type: "doc",
  dir: "content",
  files: ["index.mdx"],
  schema: z.object({
    title: z.string(),
    description: z.string(),
    brand: z.string(),
    navigation: z.array(link),
  }),
});

export const docs = defineDocs({
  dir: "content/docs",
  docs: {
    postprocess: {
      includeProcessedMarkdown: true,
    },
    schema: z.object({
      title: z.string(),
      description: z.string(),
      sources: z.array(z.string()).min(1),
    }),
  },
});

export default defineConfig({
  mdxOptions: {
    remarkPlugins: [remarkMdxMermaid],
  },
});
