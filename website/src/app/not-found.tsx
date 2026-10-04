import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main-content" className="not-found">
      <span className="brand">BEHA<sup>3</sup>VE</span>
      <h1>Page not found</h1>
      <p>The address does not match a documentation page.</p>
      <Link className="button button-primary" href="/docs">Open documentation</Link>
    </main>
  );
}
