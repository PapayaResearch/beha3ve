import { createMDX } from "fumadocs-mdx/next";

const withMDX = createMDX();

export default withMDX({
  reactStrictMode: true,
  agentRules: false,
  outputFileTracingIncludes: { "/*": ["./assets/logo.svg"] },
});
