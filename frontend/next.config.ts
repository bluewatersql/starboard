import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === 'development';

const nextConfig: NextConfig = {
  // ============================================================================
  // Databricks Apps Deployment - Static Export
  // ============================================================================
  // Static export generates HTML files to `frontend/out/` for FastAPI to serve.
  // 
  // Conversation routing uses query params (/chat?id=xyz) which is compatible
  // with static export. Old path-based URLs (/chat/[id]) are no longer supported.
  
  ...(isDev ? {} : { output: 'export' }),
  
  // ============================================================================
  // Image Optimization
  // ============================================================================
  // Disable Next.js Image Optimization (incompatible with static export)
  images: {
    unoptimized: true,
  },
  
  // ============================================================================
  // Routing
  // ============================================================================
  // Add trailing slashes for static export compatibility (production only)
  // In development, trailing slashes can cause routing issues
  trailingSlash: !isDev,
  
  // ============================================================================
  // Development API Proxy
  // ============================================================================
  // In development, proxy API requests to FastAPI backend on port 8000
  ...(isDev ? {
    async rewrites() {
      return [
        {
          source: '/api/:path*',
          destination: 'http://localhost:8000/api/:path*',
        },
      ];
    },
  } : {}),
  
  // ============================================================================
  // Environment Variables
  // ============================================================================
  // These are embedded at build time (not runtime)
  env: {
    // API URL defaults to relative path when served by same FastAPI server
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || '/api',
  },
  
  // ============================================================================
  // Development
  // ============================================================================
  typescript: {
    // Warning: This allows production builds to successfully complete even if
    // your project has type errors. Only use if you want to bypass type checking.
    // Better to fix errors before deploying!
    ignoreBuildErrors: false,
  },
};

export default nextConfig;
