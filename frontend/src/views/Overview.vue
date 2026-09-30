<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  listAuditEvents,
  listServices,
  listTokens,
  listTools,
} from '@/api'
import type { AuditEvent, Service, TokenItem, Tool } from '@/api/types'
import { AUDIT_STATUS_LABEL, AUDIT_STATUS_TONE, HEALTH_LABEL } from '@/utils/labels'
import { fromNow, todayStartISO } from '@/utils/format'

const services = ref<Service[]>([])
const tools = ref<Tool[]>([])
const tokens = ref<TokenItem[]>([])
const todayEvents = ref<AuditEvent[]>([])
const loading = ref(true)

const svcEnabled = computed(() => services.value.filter((s) => s.enabled).length)
const svcStopped = computed(() => services.value.length - svcEnabled.value)
const toolAvailable = computed(() => tools.value.filter((t) => t.available && t.enabled).length)
const toolHighRisk = computed(() => tools.value.filter((t) => t.risk === 'high').length)
const tokenHighRisk = computed(() => tokens.value.filter((t) => t.allow_high_risk && !t.revoked_at).length)
const tokenRevoked = computed(() => tokens.value.filter((t) => t.revoked_at != null).length)
const evtSucceeded = computed(() => todayEvents.value.filter((e) => e.status === 'succeeded').length)
const evtDenied = computed(() => todayEvents.value.filter((e) => e.status === 'denied').length)
const recentEvents = computed(() => todayEvents.value.slice(0, 5))

const lastCheckAt = computed(() =>
  services.value
    .map((s) => s.last_checked_at)
    .filter((v): v is string => v != null)
    .sort()
    .at(-1) ?? null,
)

onMounted(async () => {
  try {
    const [svc, tool, token, audit] = await Promise.all([
      listServices(),
      listTools(),
      listTokens(),
      listAuditEvents({ started_after: todayStartISO(), limit: 500 }),
    ])
    services.value = svc
    tools.value = tool
    tokens.value = token
    todayEvents.value = audit.items
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-title">概览</div>
    <div class="page-sub">网关运行总览与关键指标 · 实时状态</div>

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
        <div class="kpi-label">上游服务</div>
        <div class="kpi-value">{{ services.length }}</div>
        <div class="kpi-sub">启用 {{ svcEnabled }} · 停用 {{ svcStopped }}</div>
      </div>
      <div class="kpi-card kpi-card--green">
        <div class="kpi-chip kpi-chip--green">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
            <path d="M3 5.5h9M15.5 5.5H17M3 14.5h2M8.5 14.5H17" />
            <circle cx="14" cy="5.5" r="2" />
            <circle cx="6.5" cy="14.5" r="2" />
          </svg>
        </div>
        <div class="kpi-label">工具总数</div>
        <div class="kpi-value">{{ tools.length }}</div>
        <div class="kpi-sub">可用 {{ toolAvailable }} · 高风险 {{ toolHighRisk }}</div>
      </div>
      <div class="kpi-card kpi-card--orange">
        <div class="kpi-chip kpi-chip--orange">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
            <circle cx="7" cy="7" r="3.6" />
            <path d="M9.7 9.7L16.5 16.5M14 14l1.8-1.8" />
          </svg>
        </div>
        <div class="kpi-label">访问凭证</div>
        <div class="kpi-value">{{ tokens.length }}</div>
        <div class="kpi-sub">高危放行 {{ tokenHighRisk }} · 已撤销 {{ tokenRevoked }}</div>
      </div>
      <div class="kpi-card kpi-card--red">
        <div class="kpi-chip kpi-chip--red">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2.5 10h3.2l2-4.5 3.4 9 2.2-4.5h4.2" />
          </svg>
        </div>
        <div class="kpi-label">今日审计事件</div>
        <div class="kpi-value">{{ todayEvents.length }}</div>
        <div class="kpi-sub">成功 {{ evtSucceeded }} · 拒绝 {{ evtDenied }}</div>
      </div>
    </div>

    <div style="display: flex; gap: 16px; margin-top: 16px; align-items: flex-start">
      <div class="card" style="flex: 1.7">
        <div class="card-title">服务健康状态</div>
        <div class="card-sub">{{ services.length }} 个已注册的上游服务</div>
        <div style="margin-top: 8px">
          <div v-for="s in services" :key="s.id" class="health-row">
            <div>
              <div class="health-name">{{ s.name }}</div>
              <div class="health-meta">{{ s.slug }} · {{ s.url }} · {{ s.enabled ? '已启用' : '已停用' }}</div>
            </div>
            <div class="health-state" :class="`health-${s.health}`">
              <span :style="{ color: s.health === 'healthy' ? 'var(--color-success)' : s.health === 'unhealthy' ? 'var(--color-danger)' : 'var(--color-text-muted)' }">
                ● {{ HEALTH_LABEL[s.health] }}
              </span>
            </div>
          </div>
          <t-empty v-if="!services.length" description="暂无上游服务" />
        </div>
        <div class="sub-text" style="margin-top: 12px">
          最近健康检查 {{ fromNow(lastCheckAt) }}
        </div>
      </div>

      <div class="card" style="flex: 1">
        <div class="card-title">最近审计事件</div>
        <div class="card-sub">实时调用与拦截记录（今日）</div>
        <div style="margin-top: 8px">
          <div v-for="e in recentEvents" :key="e.id" class="health-row">
            <div>
              <div class="health-name" style="font-size: 14px">{{ e.tool_name }}</div>
              <div class="health-meta">{{ e.token_name ?? '—' }} · {{ fromNow(e.started_at) }}</div>
            </div>
            <div class="health-state">
              <t-tag :theme="AUDIT_STATUS_TONE[e.status]" variant="light">
                {{ AUDIT_STATUS_LABEL[e.status] }}
              </t-tag>
            </div>
          </div>
          <t-empty v-if="!recentEvents.length" description="今天还没有调用记录" />
        </div>
      </div>
    </div>
  </div>
</template>
