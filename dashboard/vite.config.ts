import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  base: '/dashboard/',
  plugins: [react()],
  server: {
    proxy: {
      // Proxy all API-related paths to the Python backend on port 8000.
      '/demo': { target: 'http://localhost:8000', changeOrigin: true },
      '/signals': { target: 'http://localhost:8000', changeOrigin: true },
      '/trades': { target: 'http://localhost:8000', changeOrigin: true },
      '/performance': { target: 'http://localhost:8000', changeOrigin: true },
      '/risk': { target: 'http://localhost:8000', changeOrigin: true },
      '/candles': { target: 'http://localhost:8000', changeOrigin: true },
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true },
      '/reset': { target: 'http://localhost:8000', changeOrigin: true },
      '/setup': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: path.resolve(__dirname, '..', 'api', 'static'),
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
