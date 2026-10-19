import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async rewrites() {
    return [
      // Brand Passport CRUD → FastAPI
      {
        source: "/api/brand-passport/:path*",
        destination: "http://localhost:8000/api/brand-passport/:path*",
      },
      // Health check → FastAPI
      {
        source: "/health",
        destination: "http://localhost:8000/health",
      },
      // /api/chat is handled by Next.js API route (app/api/chat/route.ts)
      // — no rewrite needed, it goes to OpenClaw via the translation proxy
    ];
  },
};

export default nextConfig;
