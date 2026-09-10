import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Without this, Vite only transforms each module (and pre-bundles its
    // dependencies) lazily, on the *first request* for it — so the very first
    // page load after a container start pays for the whole app's module graph
    // (MUI, react-router, react-markdown, every page/component file) serially,
    // which is what shows up as a long blank white page. Warming these up at
    // server boot moves that cost to container startup instead of page load.
    warmup: {
      clientFiles: [
        './src/main.tsx',
        './src/App.tsx',
        './src/layout/AppShell.tsx',
        './src/pages/*.tsx',
      ],
    },
  },
})
