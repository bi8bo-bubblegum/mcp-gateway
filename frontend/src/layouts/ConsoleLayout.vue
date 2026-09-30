<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DialogPlugin } from 'tdesign-vue-next'
import { auth, clearAuth } from '@/stores/auth'

const route = useRoute()
const router = useRouter()

const menus = [
  { path: '/', label: '概览', name: 'overview' },
  { path: '/services', label: '上游服务', name: 'services' },
  { path: '/tools', label: '工具管理', name: 'tools' },
  { path: '/tokens', label: '访问凭证', name: 'tokens' },
  { path: '/audit', label: '审计日志', name: 'audit' },
]

const activeName = computed(() => (route.name as string) ?? 'overview')

function logout() {
  const dialog = DialogPlugin.confirm({
    header: '退出登录',
    body: '确定要退出当前管理员会话吗？',
    confirmBtn: '退出',
    onConfirm: () => {
      clearAuth()
      dialog.destroy()
      router.push('/login')
    },
  })
}
</script>

<template>
  <header class="topbar">
    <div class="logo-box">M</div>
    <div class="app-title">MCP 网关控制台</div>
    <div class="topbar-right">
      <span class="admin-name">{{ auth.data?.username ?? 'Admin' }}</span>
      <t-button variant="text" theme="default" size="small" @click="logout">退出</t-button>
      <div class="avatar">A</div>
    </div>
  </header>

  <aside class="sidebar">
    <div class="side-title">控制台导航</div>
    <nav class="menu">
      <router-link
        v-for="m in menus"
        :key="m.name"
        :to="m.path"
        class="menu-item"
        :class="{ active: activeName === m.name }"
      >
        {{ m.label }}
      </router-link>
    </nav>
  </aside>

  <main class="main-area">
    <router-view />
  </main>
</template>
