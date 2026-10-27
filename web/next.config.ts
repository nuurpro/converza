import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async rewrites() {
    return [
      // Health check → FastAPI
      {
        source: "/health",
        destination: `${process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'}/health`,
      },
    ];
  },
};

export default nextConfig;
