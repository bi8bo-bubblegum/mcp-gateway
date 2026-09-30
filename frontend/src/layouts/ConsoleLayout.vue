<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DialogPlugin } from 'tdesign-vue-next'
import { auth, clearAuth } from '@/stores/auth'
import {
  GATEWAYS,
  GATEWAY_STORAGE_KEY,
  gatewayOfPath,
  type GatewayDef,
  type GatewayKind,
} from '@/config/gateways'

const route = useRoute()
const router = useRouter()

// 当前网关由路由前缀决定，与 localStorage 记忆保持一致
const currentKind = computed<GatewayKind>(() => gatewayOfPath(route.path).kind)
const currentGateway = computed<GatewayDef>(() => gatewayOfPath(route.path))

// 侧栏菜单随当前网关切换
const menus = computed(() => currentGateway.value.menus)
const activePath = computed(() => route.path)

function initStoredKind() {
  // 进入页面时把当前网关写回记忆，保证刷新后切换器状态正确
  try {
    localStorage.setItem(GATEWAY_STORAGE_KEY, currentKind.value)
  } catch {
    // 隐私模式等场景忽略
  }
}
onMounted(initStoredKind)

const gwVisible = ref(false)

function selectGateway(g: GatewayDef) {
  // 选中后记住并跳到该网关入口；同网关内点击不重复跳转
  gwVisible.value = false
  try {
    localStorage.setItem(GATEWAY_STORAGE_KEY, g.kind)
  } catch {
    // 忽略写入失败
  }
  if (g.kind !== currentKind.value) router.push(g.entry)
}

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

    <!-- 网关切换器：图标 + 当前网关名 + ▾，下拉两项含副标题，当前项打勾 -->
    <!-- 说明：本版本 TDesign 的 t-dropdown 不支持自定义内容插槽（slots.dropdown 不存在，
         具名 slot 会被静默丢弃导致弹层空白），因此这里用受控自定义浮层实现，视觉与交互一致 -->
    <div class="gateway-switch-wrap">
      <div class="gateway-switch" :class="{ active: gwVisible }" @click="gwVisible = !gwVisible">
        <span class="gateway-name">{{ currentGateway.label }}</span>
        <svg class="gateway-caret" :class="{ open: gwVisible }" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 4.5 6 7.5 9 4.5" />
        </svg>
      </div>
      <div v-if="gwVisible" class="gateway-backdrop" @click="gwVisible = false" />
      <div v-if="gwVisible" class="gateway-pop">
        <div
          v-for="g in GATEWAYS"
          :key="g.kind"
          class="gateway-item"
          :class="{ active: g.kind === currentKind }"
          @click="selectGateway(g)"
        >
          <div class="gateway-item-head">
            <span class="gateway-check" v-if="g.kind === currentKind">✓</span>
            <span class="gateway-item-name">{{ g.label }}</span>
          </div>
          <div class="gateway-item-sub">{{ g.desc }}</div>
        </div>
      </div>
    </div>

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
        :class="{ active: activePath === m.path }"
      >
        {{ m.label }}
      </router-link>
    </nav>
  </aside>

  <main class="main-area">
    <router-view />
  </main>
</template>

<style scoped>
/* 网关切换器：胶囊按钮样式，与顶栏其它元素对齐 */
.gateway-switch-wrap { position: relative; margin-left: 12px; }
.gateway-switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 12px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--color-divider-strong);
  background: var(--color-bg-card);
  cursor: pointer;
  user-select: none;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.gateway-switch:hover { border-color: rgba(0, 82, 217, .45); }
.gateway-switch.active { border-color: var(--color-primary); box-shadow: 0 2px 8px -2px rgba(0, 82, 217, .25); }
.gateway-name { font: 500 14px/18px var(--font-family); color: var(--color-text-primary); }
.gateway-caret { width: 12px; height: 12px; color: var(--color-text-muted); transition: transform .18s ease; }
.gateway-caret.open { transform: rotate(180deg); }

/* 自定义浮层（覆盖整页的透明背景用于点击关闭，浮层在其上方） */
.gateway-backdrop { position: fixed; inset: 0; z-index: 200; }
.gateway-pop {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  z-index: 201;
  min-width: 240px;
  padding: 6px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-divider-strong);
  border-radius: var(--radius-control);
  box-shadow: var(--shadow-float);
}
.gateway-item {
  padding: 10px 12px;
  border-radius: var(--radius-control);
  cursor: pointer;
  transition: background-color .15s ease;
}
.gateway-item + .gateway-item { margin-top: 2px; }
.gateway-item:hover { background: var(--color-bg-group); }
.gateway-item.active { background: var(--color-primary-light); }
.gateway-item-head { display: flex; align-items: center; gap: 6px; }
.gateway-check { color: var(--color-primary); font-size: 13px; font-weight: 700; }
.gateway-item-name { font: 500 14px/18px var(--font-family); color: var(--color-text-primary); }
.gateway-item-sub { margin-top: 3px; font: var(--font-caption); color: var(--color-text-muted); }
</style>
