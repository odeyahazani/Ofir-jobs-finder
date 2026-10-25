import type { NextConfig } from "next";
const config: NextConfig = {
  poweredByHeader: false,
  devIndicators: process.env.OFIR_E2E === "1" ? false : undefined,
  outputFileTracingExcludes: {
    "/*": ["./.local/**", "./docs/**", "./tests/**", "./supabase/**"],
  },
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "same-origin" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Cache-Control", value: "private, no-store" },
    ] }];
  },
};
export default config;
