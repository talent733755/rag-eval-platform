import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  outputFileTracingRoot: path.join(__dirname, "../.."),
};

export default nextConfig;
