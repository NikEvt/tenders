import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Один self-contained артефакт для docker-образа: см. docker/Dockerfile.web.
  output: "standalone",
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },
  experimental: {
    // Recharts тянет весь lodash-подобный набор; берём только использованное.
    optimizePackageImports: ["lucide-react", "recharts", "date-fns"],
  },
};

export default config;
