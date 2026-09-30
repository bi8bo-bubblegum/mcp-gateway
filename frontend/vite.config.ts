import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 开发期把 /admin、/mcp、/health 代理到本机网关，避免跨域问题；
// 后端 FastAPI 未配置 CORS 中间件，走代理是零侵入方案。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/admin': { target: 'http://127.0.0.1:8800', changeOrigin: true },
      '/mcp': { target: 'http://127.0.0.1:8800', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8800', changeOrigin: true },
    },
  },
})
