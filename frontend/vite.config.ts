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
      // /mcp 同时承载两件事：后端 MCP 协议端点和前端控制台路由 /mcp。
      // Vite 6 的代理只支持 bypass（filter 字段已被移除、会被静默忽略），故用
      // bypass 区分：浏览器对控制台页面的 HTML 导航（Accept 含 text/html）返回
      // '/' 交回 Vite 的 history 回退渲染 SPA；其余（MCP 协议的 JSON / SSE 调用）
      // 返回 undefined 继续转发到后端，避免硬刷新 /mcp 时打到后端。
      '/mcp': {
        target: 'http://127.0.0.1:8800',
        changeOrigin: true,
        bypass: (req) => {
          const accept = (req.headers && req.headers.accept) || ''
          if (String(accept).includes('text/html')) {
            return '/' // 交给 Vite 渲染 SPA 入口
          }
          return undefined // 继续代理到后端（MCP 协议调用）
        },
      },
      '/health': { target: 'http://127.0.0.1:8800', changeOrigin: true },
    },
  },
})
