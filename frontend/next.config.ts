import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export — the app is fully client-side (no API routes, no server
  // components doing data fetching, no middleware), so it's served as plain
  // static files by nginx on the same EC2 instance as the backend.
  output: "export",
};

export default nextConfig;
