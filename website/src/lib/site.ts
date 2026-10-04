export const repository = "https://github.com/PapayaResearch/wab";

export const siteUrl = process.env.SITE_URL
  ? new URL(process.env.SITE_URL)
  : new URL(process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "http://localhost:3000");
