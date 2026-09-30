import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/Login.vue') },
    // 根路径统一落到 MCP 网关概览；AI 网关通过顶栏切换器进入
    { path: '/', redirect: '/mcp' },
    {
      path: '/mcp',
      component: () => import('@/layouts/ConsoleLayout.vue'),
      children: [
        { path: '', name: 'mcp-overview', component: () => import('@/views/Overview.vue') },
        { path: 'services', name: 'mcp-services', component: () => import('@/views/Services.vue') },
        { path: 'tools', name: 'mcp-tools', component: () => import('@/views/Tools.vue') },
        { path: 'tokens', name: 'mcp-tokens', component: () => import('@/views/Tokens.vue') },
        { path: 'audit', name: 'mcp-audit', component: () => import('@/views/Audit.vue') },
      ],
    },
    {
      path: '/ai',
      component: () => import('@/layouts/ConsoleLayout.vue'),
      children: [
        { path: '', name: 'ai-overview', component: () => import('@/views/ai/Overview.vue') },
        { path: 'providers', name: 'ai-providers', component: () => import('@/views/ai/Providers.vue') },
        { path: 'models', name: 'ai-models', component: () => import('@/views/ai/Models.vue') },
        { path: 'keys', name: 'ai-keys', component: () => import('@/views/ai/Keys.vue') },
        { path: 'usage', name: 'ai-usage', component: () => import('@/views/ai/Usage.vue') },
        { path: 'guardrails', name: 'ai-guardrails', component: () => import('@/views/ai/Guardrails.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  if (to.path !== '/login' && !isLoggedIn()) return '/login'
  if (to.path === '/login' && isLoggedIn()) return '/'
  return true
})

export default router
