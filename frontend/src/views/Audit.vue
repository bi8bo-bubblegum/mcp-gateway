<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { listAuditEvents, listServices, listTokens } from '@/api'
import type { AuditEvent, AuditStatus, Service, TokenItem } from '@/api/types'
import { AUDIT_STATUS_LABEL, AUDIT_STATUS_TONE, DENIAL_REASON_LABEL } from '@/utils/labels'
import { fmtDuration, fmtTime } from '@/utils/format'

const PAGE_SIZE = 20

const items = ref<AuditEvent[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)

const services = ref<Service[]>([])
const tokenOptions = ref<{ value: number; label: string }[]>([])

const filters = reactive({
  token_id: undefined as number | undefined,
  service_slug: undefined as string | undefined,
  tool_name: '',
  status: undefined as AuditStatus | undefined,
  timeRange: [] as string[],
})

async function load() {
  loading.value = true
  try {
    const offset = (page.value - 1) * PAGE_SIZE
    const result = await listAuditEvents({
      token_id: filters.token_id,
      service_slug: filters.service_slug,
      tool_name: filters.tool_name.trim() || undefined,
      status: filters.status,
      started_after: filters.timeRange[0] || undefined,
      started_before: filters.timeRange[1] || undefined,
      limit: PAGE_SIZE,
      offset,
    })
    items.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function reset() {
  filters.token_id = undefined
  filters.service_slug = undefined
  filters.tool_name = ''
  filters.status = undefined
  filters.timeRange = []
  search()
}

function onPageChange(info: { current: number }) {
  page.value = info.current
  load()
}

onMounted(async () => {
  load()
  try {
    const [svc, token] = await Promise.all([listServices(), listTokens()])
    services.value = svc
    tokenOptions.value = token.map((t) => ({ value: t.id, label: t.name }))
  } catch {
    // 过滤项加载失败不阻塞主表
  }
})

const columns = [
  { colKey: 'request_id', title: '请求ID', width: 160 },
  { colKey: 'token_name', title: '凭证', width: 100 },
  { colKey: 'service_slug', title: '服务', width: 90 },
  { colKey: 'tool_name', title: '工具', ellipsis: true }, // 弹性列
  { colKey: 'status', title: '状态', width: 90 },
  { colKey: 'denial_reason', title: '拒绝原因', width: 130, ellipsis: true },
  { colKey: 'duration_ms', title: '耗时', width: 70 },
  { colKey: 'started_at', title: '开始时间', width: 110 },
]
</script>

<template>
  <div class="page">
    <div class="page-title">审计日志</div>
    <div class="page-sub">记录每一次令牌调用、放行与拒绝（不保存入参原文）</div>

    <div class="toolbar" style="flex-wrap: wrap">
      <t-select
        v-model="filters.token_id"
        placeholder="全部凭证"
        clearable
        filterable
        style="width: 140px"
        :options="tokenOptions"
      />
      <t-select
        v-model="filters.service_slug"
        placeholder="全部服务"
        clearable
        filterable
        style="width: 140px"
      >
        <t-option v-for="s in services" :key="s.id" :value="s.slug" :label="s.slug" />
      </t-select>
      <t-input v-model="filters.tool_name" placeholder="工具名称" style="width: 160px" clearable />
      <t-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px">
        <t-option value="started" label="进行中" />
        <t-option value="succeeded" label="成功" />
        <t-option value="failed" label="失败" />
        <t-option value="denied" label="拒绝" />
      </t-select>
      <t-date-range-picker
        v-model="filters.timeRange"
        enable-time-picker
        allow-input
        style="width: 340px"
        placeholder="开始时间 ~ 结束时间"
      />
      <t-button theme="primary" @click="search">查询</t-button>
      <t-button variant="outline" theme="default" @click="reset">重置</t-button>
    </div>

    <div class="card" style="margin-top: 16px">
      <div style="display: flex; align-items: center; margin-bottom: 8px">
        <span class="card-title">审计事件</span>
        <span class="sub-text" style="margin-left: 12px">共 {{ total }} 条</span>
      </div>
      <t-table
        row-key="id"
        :data="items"
        :columns="columns"
        :loading="loading"
        :hover="true"
        :bordered="false"
        :pagination="{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showJumper: true,
        }"
        @page-change="onPageChange"
      >
        <template #request_id="{ row }">
          <code class="req-id">{{ row.request_id }}</code>
        </template>
        <template #token_name="{ row }">{{ row.token_name ?? '—' }}</template>
        <template #service_slug="{ row }">{{ row.service_slug ?? '—' }}</template>
        <template #status="{ row }">
          <t-tag :theme="AUDIT_STATUS_TONE[row.status as keyof typeof AUDIT_STATUS_TONE]" variant="light">
            {{ AUDIT_STATUS_LABEL[row.status as keyof typeof AUDIT_STATUS_LABEL] }}
          </t-tag>
        </template>
        <template #denial_reason="{ row }">
          <span :style="{ color: row.denial_reason ? 'var(--color-warning)' : undefined }">
            {{ row.denial_reason ? (DENIAL_REASON_LABEL[row.denial_reason] ?? row.denial_reason) : '—' }}
          </span>
        </template>
        <template #duration_ms="{ row }">
          {{ fmtDuration(row.duration_ms) }}
        </template>
        <template #started_at="{ row }">{{ fmtTime(row.started_at) }}</template>
      </t-table>
    </div>
  </div>
</template>

<style scoped>
.req-id {
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: 13px;
  color: var(--color-text-primary);
}
</style>
