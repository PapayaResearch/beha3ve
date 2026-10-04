import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readdir } from "node:fs/promises";
import { once } from "node:events";
import { parseArgs } from "node:util";

const { values } = parseArgs({ options: { "base-url": { type: "string", default: "http://127.0.0.1:3000" }, start: { type: "boolean", default: false } } });
const base = new URL(values["base-url"]);
let server;
if (values.start) {
  server = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", base.hostname, "--port", base.port || "3000"], { stdio: ["ignore", "pipe", "inherit"] });
  process.on("exit", () => server.kill());
  await new Promise((resolve, reject) => {
    server.stdout.on("data", (data) => { if (data.toString().includes("Ready")) resolve(); });
    server.once("exit", (code) => reject(new Error(`Website startup exited with ${code}`)));
  });
}
const files = await readdir(new URL("../content/docs/", import.meta.url), { recursive: true });
const routes = ["/", ...files.filter((file) => file.endsWith(".mdx")).map((file) => `/docs/${file.replace(/\.mdx$/, "").replace(/(^|\/)index$/, "")}`.replace(/\/$/, ""))];
const pages = new Map(await Promise.all(routes.map(async (route) => {
  const response = await fetch(new URL(route, base));
  assert.equal(response.status, 200, route);
  const html = await response.text();
  assert.match(html, /<title>[^<]+<\/title>/, route);
  assert.match(html, /name="description" content="[^"]+"/, route);
  assert.match(html, /id="main-content"/, route);
  assert.match(html, /<h1[\s>]/, route);
  if (route.startsWith("/docs")) assert.match(html, /Edit on GitHub/, route);
  return [route, html];
})));

const links = new Map();
const images = new Set();
for (const [route, html] of pages) {
  for (const match of html.matchAll(/href="([^"]+)"/g)) {
    const url = new URL(match[1].replaceAll("&amp;", "&"), new URL(route, base));
    if (url.origin !== base.origin || url.pathname.startsWith("/_next/")) continue;
    assert(!url.pathname.endsWith(".mdx"), `Unresolved documentation link on ${route}: ${url.pathname}`);
    links.set(url.href, url);
  }
  for (const match of html.matchAll(/<img[^>]+src="([^"]+)"/g)) images.add(new URL(match[1].replaceAll("&amp;", "&"), base).href);
}
await Promise.all([...links.values()].map(async (url) => {
  const route = url.pathname.replace(/\/$/, "") || "/";
  const html = pages.get(route) ?? await (async () => {
    const response = await fetch(url);
    assert.equal(response.status, 200, url.href);
    return response.text();
  })();
  if (url.hash) assert(html.includes(`id="${decodeURIComponent(url.hash.slice(1))}"`), `Missing anchor: ${url.href}`);
}));
await Promise.all([...images].map(async (url) => {
  const response = await fetch(url);
  assert.equal(response.status, 200, url);
  assert.match(response.headers.get("content-type"), /^image\//, url);
}));
const search = await fetch(new URL("/api/search?query=snapshot", base));
assert.equal(search.status, 200);
assert((await search.json()).length > 0, "Search returned no snapshot results");
const sitemap = await fetch(new URL("/sitemap.xml", base));
assert.equal(sitemap.status, 200);
const sitemapText = await sitemap.text();
assert.equal((sitemapText.match(/<loc>/g) ?? []).length, routes.length);
assert.equal((await fetch(new URL("/robots.txt", base))).status, 200);
const socialImage = await fetch(new URL("/opengraph-image", base));
assert.equal(socialImage.status, 200);
assert.match(socialImage.headers.get("content-type"), /^image\//);
assert.equal((await fetch(new URL("/docs/this-page-does-not-exist", base))).status, 404);
assert(pages.get("/").includes("https://github.com/PapayaResearch/wab"));
console.log(`Checked ${pages.size} pages, ${links.size} internal links and anchors, ${images.size} images, search, sitemap, robots, social image, and 404 behavior.`);
if (server) {
  server.kill();
  await once(server, "exit");
}
