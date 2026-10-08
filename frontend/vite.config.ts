import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: {
      deny: [
        ".env",
        ".env.*",
        "*.{crt,pem}",
        "**/.git/**",
        "**/.data/**",
        "**/.venv/**",
      ],
    },
    watch: {
      ignored: [
        "**/.local_node_modules_backup/**",
        "**/test-results/**",
        "**/dist/**",
        "**/*.tsbuildinfo",
      ],
    },
  },
});
