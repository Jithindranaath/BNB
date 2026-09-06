/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_ORCHESTRATOR_URL:
      process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "http://localhost:8080",
  },
};

export default nextConfig;
