import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Dev proxy — only used when VITE_API_BASE is not set (local dev).
      // In production (Vercel), VITE_API_BASE points to the Railway backend URL
      // and api.js uses it directly — no proxy needed.
      '/api': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
})
