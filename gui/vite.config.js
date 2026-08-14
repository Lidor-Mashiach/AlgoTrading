import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to the REST API. The page and the data then share one
// origin, so the browser never treats an API call as cross origin and no CORS headers
// are needed on the backend. serve.py does exactly the same for the built output.
//
// Port 5173 is not a preference. main.py waits on that port before opening the window,
// so it must match GUI_PORT in main.py. strictPort makes a clash fail loudly instead of
// silently moving to 5174 and leaving main.py waiting out its timeout.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    host: "localhost",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
