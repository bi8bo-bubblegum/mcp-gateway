<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { listKeys, listModels, listUsageEvents } from '@/api/ai'
import type { AiKey, AiModel, AiUsageStatus } from '@/api/ai-types'
import { AI_DENIAL_LABEL, AI_STATUS_LABEL, AI_STATUS_TONE } from '@/utils/labels'
import { fmtDuration, fmtTime } from '@/utils/format'

const PAGE_SIZE = 20

const items = ref<import('@/api/ai-types').AiUsageEvent[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)

const keys = ref<AiKey[]>([])
const models = ref<AiModel[]>([])
const keyOptions = ref<{ value: number; label: string }[]>([])
const modelOptions = ref<{ value: number; label: string }[]>([])

const filters = reactive({
  key_id: undefined as number | undefined,
  model_id: undefined as number | undefined,
  status: undefined as AiUsageStatus | undefined,
  timeRange: [] as string[],
})

async function load() {
  loading.value = true
  try {
    const offset = (page.value - 1) * PAGE_SIZE
    const result = await listUsageEvents({
      key_id: filters.key_id,
      model_id: filters.model_id,
      status: filters.status,
      started_after: filters.timeRange[0] || undefined,
      started_before: filters.timeRange[1] || undefined,
      limit: PAGE_SIZE,
      offset,
    })
    items.value = result.items
    total.value = result.total
  } catch {
    // 错误提示由拦截器弹出
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}
function reset() {
  filters.key_id = undefined
  filters.model_id = undefined
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
    const [k, m] = await Promise.all([listKeys(), listModels()])
    keys.value = k
    models.value = m
    keyOptions.value = k.map((x) => ({ value: x.id, label: x.name }))
    modelOptions.value = m.map((x) => ({ value: x.id, label: x.alias }))
  } catch {
    // 过滤项加载失败不阻塞主表
  }
})

const columns = [
  { colKey: 'started_at', title: '时间', width: 110 },
  { colKey: 'key_name', title: '密钥', width: 110 },
  { colKey: 'model_alias', title: '模型', ellipsis: true },
  { colKey: 'provider_slug', title: '厂商', width: 100 },
  { colKey: 'endpoint', title: '端点', width: 120 },
  { colKey: 'stream', title: '流式', width: 70 },
  { colKey: 'status', title: '状态', width: 90 },
  { colKey: 'total_tokens', title: 'Tokens', width: 100 },
  { colKey: 'latency_ms', title: '耗时', width: 110 },
]
</script>

<template>
  <div class="page">
    <div class="page-title">用量审计</div>
    <div class="page-sub">记录每一次 AI Key 调用、放行与拒绝（不保存入参原文）</div>

    <div class="toolbar" style="flex-wrap: wrap">
      <t-select
        v-model="filters.key_id"
        placeholder="全部密钥"
        clearable
        filterable
        style="width: 150px"
        :options="keyOptions"
      />
      <t-select
        v-model="filters.model_id"
        placeholder="全部模型"
        clearable
        filterable
        style="width: 150px"
        :options="modelOptions"
      />
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
        <span class="card-title">调用事件</span>
        <span class="sub-text" style="margin-left: 12px">共 {{ total }} 条</span>
      </div>
      <t-table
        row-key="id"
        :data="items"
        :columns="columns"
        :loading="loading"
        :hover="true"
        :bordered="false"
        :pagination="{ current: page, pageSize: PAGE_SIZE, total, showJumper: true }"
        @page-change="onPageChange"
      >
        <template #started_at="{ row }">{{ fmtTime(row.started_at) }}</template>
        <template #key_name="{ row }">{{ row.key_name ?? '—' }}</template>
        <template #model_alias="{ row }">{{ row.model_alias ?? '—' }}</template>
        <template #provider_slug="{ row }">{{ row.provider_slug ?? '—' }}</template>
        <template #endpoint="{ row }">{{ row.endpoint ?? '—' }}</template>
        <template #stream="{ row }">
          <t-tag :theme="row.stream ? 'primary' : 'default'" variant="light">
            {{ row.stream ? '流式' : '非流式' }}
          </t-tag>
        </template>
        <template #status="{ row }">
          <t-tag :theme="AI_STATUS_TONE[row.status as keyof typeof AI_STATUS_TONE]" variant="light">
            {{ AI_STATUS_LABEL[row.status as keyof typeof AI_STATUS_LABEL] }}
          </t-tag>
        </template>
        <template #total_tokens="{ row }">
          <span :class="{ muted: !row.total_tokens }">{{ (row.total_tokens ?? 0).toLocaleString() }}</span>
        </template>
        <template #latency_ms="{ row }">{{ fmtDuration(row.latency_ms) }}</template>
      </t-table>
    </div>
  </div>
</template>

<style scoped>
.muted { color: var(--color-text-muted); }
</style>
