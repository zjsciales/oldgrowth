import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets are served by the existing Flask process (canopy/app.py) --
// one local process, no CORS, matches the project's local-first setup.
// `npm run dev` proxies /api to a separately-running `flask run` (port
// 5000) for active frontend iteration; `npm run build` + `flask run`
// alone is the normal way to use the app.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  // only the built output needs the /static/dist/ prefix (that's where
  // Flask serves it from); the dev server should stay at a plain root or
  // its URLs get the same prefix baked in, which is just awkward to work
  // against locally
  base: command === "build" ? "/static/dist/" : "/",
  build: {
    outDir: "../canopy/static/dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // explicit IPv4 -- "localhost" resolves to ::1 first in Node, and
      // macOS AirPlay Receiver squats on the IPv6 listener for port 5000
      // (the same conflict `canopy/app.py` sidesteps locally with
      // PORT=5050); Flask only binds IPv4, so plain "localhost" here
      // silently proxied to AirPlay instead of Flask
      "/api": "http://127.0.0.1:5000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./vitest.setup.js",
  },
}));
