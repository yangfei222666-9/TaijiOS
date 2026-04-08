import type { NextConfig } from "next";

const apiUrl = process.env.API_URL || "http://localhost:9200";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
