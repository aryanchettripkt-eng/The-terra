import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_INTERNAL_URL || "https://the-terra-391294275080.asia-southeast1.run.app";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
