import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": "/src",
    },
  },
  build: {
    outDir: "dist/static",
    emptyOutDir: true,
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    proxy: {
      "/contracts": process.env.CG_STUDIO_API || "http://127.0.0.1:8787",
      "/gallery": process.env.CG_STUDIO_API || "http://127.0.0.1:8787",
      "/health": process.env.CG_STUDIO_API || "http://127.0.0.1:8787",
      "/outputs": process.env.CG_STUDIO_API || "http://127.0.0.1:8787",
      "/runs": process.env.CG_STUDIO_API || "http://127.0.0.1:8787",
      "/studio-session": process.env.CG_STUDIO_API || "http://127.0.0.1:8787",
      "/uploads": process.env.CG_STUDIO_API || "http://127.0.0.1:8787",
    },
  },
});
