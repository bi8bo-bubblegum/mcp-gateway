import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/Login.vue') },
    {
      path: '/',
      component: () => import('@/layouts/ConsoleLayout.vue'),
      children: [
        { path: '', name: 'overview', component: () => import('@/views/Overview.vue') },
        { path: 'services', name: 'services', component: () => import('@/views/Services.vue') },
        { path: 'tools', name: 'tools', component: () => import('@/views/Tools.vue') },
        { path: 'tokens', name: 'tokens', component: () => import('@/views/Tokens.vue') },
        { path: 'audit', name: 'audit', component: () => import('@/views/Audit.vue') },
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
