import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development, /api is proxied to the local backend (regulation-analyst api).
// In production, VITE_API_URL points at the deployed backend instead.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.API_PROXY ?? "http://127.0.0.1:8000" },
  },
});
