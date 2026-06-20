import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// base: './' so built assets use relative paths when served from backend root.
export default defineConfig({
  base: './',
  plugins: [vue()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'http://localhost:8000', ws: true, changeOrigin: true }
    }
  }
})
