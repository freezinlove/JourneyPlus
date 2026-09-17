import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Keep browser traffic same-origin. Only the development proxy talks to FastAPI.
const target = process.env.JOURNEYPLUS_API_URL || "http://127.0.0.1:8000";
const proxy = Object.fromEntries(
  ["/auth", "/v1", "/v2", "/v3"].map((path) => [
    path,
    {
      target,
      changeOrigin: true,
      configure(server: any) {
        server.on("proxyReq", (req: any) => {
          req.setHeader("Origin", target);
        });
      },
    },
  ]),
);
export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
  build: {
    sourcemap: true,
    assetsDir: "assets/web",
    rollupOptions: {
      output: {
        manualChunks: {
          markdown: ["react-markdown", "remark-gfm"],
          ui: ["@radix-ui/react-dialog"],
        },
      },
    },
  },
});
