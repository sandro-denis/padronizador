import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Build sempre com nome de arquivo FIXO (sem hash) em ../static/dist, pra
// o Flask (templates/index.html) poder referenciar um caminho estavel sem
// precisar ler manifest nenhum - so "python app.py" depois do build, sem
// mais nada.
// Porta do backend Flask: mesma variavel usada pelo app.py (padrao 5057).
const API_PORT = process.env.PADRONIZADOR_PORT || "5057";

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    assetsDir: "",
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "app.js",
        assetFileNames: "app.[ext]",
      },
    },
  },
  server: {
    proxy: {
      "/api": `http://127.0.0.1:${API_PORT}`,
    },
  },
});
