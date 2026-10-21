/** @type {import('next').NextConfig} */
const nextConfig = {
  // node:sqlite is a Node builtin (node: scheme) and is externalized automatically
  // on the server. Every DB-touching route/action forces the Node.js runtime.
  reactStrictMode: true,
};

export default nextConfig;
