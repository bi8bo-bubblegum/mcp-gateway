<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  listKeys,
  listModels,
  listProviders,
  listUsageEvents,
} from '@/api/ai'
import type { AiKey, AiModel, AiProvider, AiUsageEvent } from '@/api/ai-types'
import { HEALTH_LABEL, HEALTH_TONE, AI_STATUS_LABEL, AI_STATUS_TONE } from '@/utils/labels'
import { fromNow, todayStartISO } from '@/utils/format'

const providers = ref<AiProvider[]>([])
const models = ref<AiModel[]>([])
const keys = ref<AiKey[]>([])
const todayEvents = ref<AiUsageEvent[]>([])
const loading = ref(true)

const providerEnabled = computed(() => providers.value.filter((p) => p.enabled).length)
const providerStopped = computed(() => providers.value.length - providerEnabled.value)
const modelEnabled = computed(() => models.value.filter((m) => m.enabled).length)
const keyActive = computed(
  () => keys.value.filter((k) => k.enabled && !k.revoked_at).length,
)
const keyRevoked = computed(() => keys.value.filter((k) => k.revoked_at != null).length)
const todayRequests = computed(() => todayEvents.value.length)
const todayTokens = computed(() =>
  todayEvents.value.reduce((sum, e) => sum + (e.total_tokens ?? 0), 0),
)
const recentEvents = computed(() => todayEvents.value.slice(0, 5))

const lastCheckAt = computed(() =>
  providers.value
    .map((p) => p.last_checked_at)
    .filter((v): v is string => v != null)
    .sort()
    .at(-1) ?? null,
)

onMounted(async () => {
  try {
    const [p, m, k, usage] = await Promise.all([
      listProviders(),
      listModels(),
      listKeys(),
      listUsageEvents({ started_after: todayStartISO(), limit: 500 }),
    ])
    providers.value = p
    models.value = m
    keys.value = k
    todayEvents.value = usage.items
  } catch {
    // 数据接口失败（如 MySQL 尚未迁移 AI 表）不阻塞页面渲染，留空即可
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-title">概览</div>
    <div class="page-sub">AI 网关运行总览与关键指标 · 实时状态</div>

    <div class="kpi-row" style="margin-top: 24px">
      <div class="kpi-card kpi-card--blue">
        <div class="kpi-chip kpi-chip--blue">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
            <rect x="2.5" y="3" width="15" height="5.5" rx="2" />
            <rect x="2.5" y="11.5" width="15" height="5.5" rx="2" />
            <circle cx="6" cy="5.75" r="0.4" fill="currentColor" />
            <circle cx="6" cy="14.25" r="0.4" fill="currentColor" />
          </svg>
        </div>
        <div class="kpi-label">厂商数</div>
        <div class="kpi-value">{{ providers.length }}</div>
        <div class="kpi-sub">启用 {{ providerEnabled }} · 停用 {{ providerStopped }}</div>
      </div>
      <div class="kpi-card kpi-card--green">
        <div class="kpi-chip kpi-chip--green">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
            <path d="M3 5.5h9M15.5 5.5H17M3 14.5h2M8.5 14.5H17" />
            <circle cx="14" cy="5.5" r="2" />
            <circle cx="6.5" cy="14.5" r="2" />
          </svg>
        </div>
        <div class="kpi-label">模型数</div>
        <div class="kpi-value">{{ models.length }}</div>
        <div class="kpi-sub">对外暴露 {{ modelEnabled }} · 停用 {{ models.length - modelEnabled }}</div>
      </div>
      <div class="kpi-card kpi-card--orange">
        <div class="kpi-chip kpi-chip--orange">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
            <circle cx="7" cy="7" r="3.6" />
            <path d="M9.7 9.7L16.5 16.5M14 14l1.8-1.8" />
          </svg>
        </div>
        <div class="kpi-label">有效 AI Key</div>
        <div class="kpi-value">{{ keyActive }}</div>
        <div class="kpi-sub">已撤销 {{ keyRevoked }}</div>
      </div>
      <div class="kpi-card kpi-card--red">
        <div class="kpi-chip kpi-chip--red">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2.5 10h3.2l2-4.5 3.4 9 2.2-4.5h4.2" />
          </svg>
        </div>
        <div class="kpi-label">今日请求 / Token</div>
        <div class="kpi-value">{{ todayRequests }}</div>
        <div class="kpi-sub">消耗 {{ todayTokens.toLocaleString() }} tokens</div>
      </div>
    </div>

    <div style="display: flex; gap: 16px; margin-top: 16px; align-items: flex-start">
      <div class="card" style="flex: 1.7">
        <div class="card-title">厂商健康状态</div>
        <div class="card-sub">{{ providers.length }} 个已注册的 AI 厂商 / 中转</div>
        <div style="margin-top: 8px">
          <div v-for="p in providers" :key="p.id" class="health-row">
            <div>
              <div class="health-name">{{ p.name }}</div>
              <div class="health-meta">{{ p.slug }} · {{ p.base_url }} · {{ p.enabled ? '已启用' : '已停用' }}</div>
            </div>
            <div class="health-state">
              <span :style="{ color: p.health === 'healthy' ? 'var(--color-success)' : p.health === 'unhealthy' ? 'var(--color-danger)' : 'var(--color-text-muted)' }">
                ● {{ HEALTH_LABEL[p.health] }}
              </span>
            </div>
          </div>
          <t-empty v-if="!providers.length" description="暂无厂商" />
        </div>
        <div class="sub-text" style="margin-top: 12px">
          最近健康检查 {{ fromNow(lastCheckAt) }}
        </div>
      </div>

      <div class="card" style="flex: 1">
        <div class="card-title">最近请求</div>
        <div class="card-sub">实时调用与拦截记录（今日）</div>
        <div style="margin-top: 8px">
          <div v-for="e in recentEvents" :key="e.id" class="health-row">
            <div>
              <div class="health-name" style="font-size: 14px">{{ e.model_alias ?? '—' }}</div>
              <div class="health-meta">{{ e.key_name ?? '—' }} · {{ fromNow(e.started_at) }}</div>
            </div>
            <div class="health-state">
              <t-tag :theme="AI_STATUS_TONE[e.status]" variant="light">
                {{ AI_STATUS_LABEL[e.status] }}
              </t-tag>
            </div>
          </div>
          <t-empty v-if="!recentEvents.length" description="今天还没有调用记录" />
        </div>
      </div>
    </div>
  </div>
</template>
