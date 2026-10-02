import type { NextConfig } from "next";

/**
 * Backend (FastAPI) base URL used by the same-origin proxy.
 *
 * IMPORTANT: Next.js evaluates `rewrites()` at BUILD time and bakes the result into
 * `.next/routes-manifest.json`. Changing `ORBIT_API_URL` on an already-built image has
 * no effect on the proxy destination — rebuild with `--build-arg ORBIT_API_URL=...`
 * (the Dockerfile defaults it to `http://api:8000`, the docker compose service name).
 * For `npm run dev`, the default `http://localhost:8000` targets a locally running API.
 */
const apiUrl = (process.env.ORBIT_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    // Long-running proxied calls (multipart uploads, NDJSON exports, MCP streams).
    proxyTimeout: 120_000,
  },
  async rewrites() {
    return [
      // Public landing page (static bundle exported from the design tool).
      { source: "/", destination: "/landing.html" },
      { source: "/api/:path*", destination: `${apiUrl}/api/:path*` },
      { source: "/mcp", destination: `${apiUrl}/mcp` },
      { source: "/mcp/:path*", destination: `${apiUrl}/mcp/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
