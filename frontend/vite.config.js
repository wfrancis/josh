import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Live co-editing breaks if two copies of these end up in the bundle.
    dedupe: ['yjs', 'lib0', 'y-protocols']
  },
  server: {
    proxy: {
      // ws: also forward websocket connections (live co-editing) to the API server.
      '/api': { target: 'http://localhost:8000', ws: true }
    }
  },
  build: {
    outDir: 'dist'
  }
})
