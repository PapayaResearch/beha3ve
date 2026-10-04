import { docs } from "@/.source";
import type { DocsCollectionEntry } from "fumadocs-mdx/runtime/server";
import { loader } from "fumadocs-core/source";

const collection: DocsCollectionEntry<"docs", { title: string; description: string; sources: string[] }> = docs;

export const source = loader({
  baseUrl: "/docs",
  source: collection.toFumadocsSource(),
});
