import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
const vendor = path.resolve(__dirname, "../../vendor/nanobot/webui/src");
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": vendor },
    dedupe: Object.keys(pkg.dependencies),
  },
  server: { port: 5180, fs: { allow: [path.resolve(__dirname, "../..") ] },
    proxy: { "/api": "http://127.0.0.1:8810" } },
  build: { outDir: "dist", sourcemap: false },
  test: { environment: "happy-dom", setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.tsx"] },
});
