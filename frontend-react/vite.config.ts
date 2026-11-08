import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const rootDir = import.meta.dirname

// Porta 5174, distinta da quella del frontend Vue esistente (5173) — le due
// app convivono durante la migrazione, non si sostituiscono a vicenda.
// Stesso proxy dev di frontend/vite.config.js: senza, ogni fetch verso
// '/api'/'/token' finirebbe sul dev server di Vite invece che su FastAPI.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(rootDir, './src'),
    },
  },
  // epubjs's CJS dependency chain references the Node global `global` —
  // Vite/browsers only have `globalThis`. Paired with src/nodePolyfills.ts
  // (Buffer/process shims), same as frontend/vite.config.js.
  define: {
    global: 'globalThis',
  },
  build: {
    rollupOptions: {
      input: {
        main: path.resolve(rootDir, 'index.html'),
        // The web reader opens in its own real browser window (not a modal
        // in the main SPA) — a separate HTML entry point gives it its own
        // document/URL/history, same reasoning (and same pattern) as
        // frontend/vite.config.js's reader/pdfReader entries.
        reader: path.resolve(rootDir, 'reader.html'),
        pdfReader: path.resolve(rootDir, 'pdf-reader.html'),
      },
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:8081',
      '/token': 'http://localhost:8081',
    },
  },
})
