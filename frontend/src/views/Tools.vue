<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { listServices, listTools, updateTool } from '@/api'
import type { RiskLevel, Tool } from '@/api/types'
import { RISK_LABEL, RISK_TONE } from '@/utils/labels'
import { fmtTime } from '@/utils/format'
import ToolDrawer from '@/components/ToolDrawer.vue'

const tools = ref<Tool[]>([])
const loading = ref(true)

const svcOptions = ref<{ value: number; label: string }[]>([])
const svcFilter = ref<number | null>(null)
const riskFilter = ref<'all' | RiskLevel>('all')
const keyword = ref('')

const drawerVisible = ref(false)
const editingTool = ref<Tool | null>(null)

async function load() {
  loading.value = true
  try {
    tools.value = await listTools()
  } finally {
    loading.value = false
  }
}
onMounted(async () => {
  await load()
  try {
    const services = await listServices()
    svcOptions.value = services.map((s) => ({ value: s.id, label: s.slug }))
  } catch {
    // 服务列表失败不阻塞工具页
  }
})

const filtered = computed(() =>
  tools.value.filter((t) => {
    if (svcFilter.value != null && t.service_id !== svcFilter.value) return false
    if (riskFilter.value !== 'all' && t.risk !== riskFilter.value) return false
    const kw = keyword.value.trim().toLowerCase()
    if (!kw) return true
    return (
      t.effective_name.toLowerCase().includes(kw) ||
      t.upstream_name.toLowerCase().includes(kw)
    )
  }),
)

function openEdit(row: Tool) {
  editingTool.value = row
  drawerVisible.value = true
}

async function toggleEnabled(row: Tool, value: boolean) {
  try {
    await updateTool(row.id, { enabled: value })
    row.enabled = value
  } catch {
    // 失败时保持原值；错误提示由拦截器弹出
  }
}

const columns = [
  { colKey: 'effective_name', title: '有效名称', ellipsis: true }, // 弹性列
  { colKey: 'upstream_name', title: '上游名称', width: 160 },
  { colKey: 'service_slug', title: '所属服务', width: 120 },
  { colKey: 'risk', title: '风险等级', width: 90 },
  { colKey: 'enabled', title: '启用', width: 70 },
  { colKey: 'available', title: '可用', width: 70 },
  { colKey: 'discovered_at', title: '发现时间', width: 120 },
  { colKey: 'op', title: '操作', width: 60 },
]
</script>

<template>
  <div class="page">
    <div class="page-title">工具管理</div>
    <div class="page-sub">浏览上游服务发现的所有工具，并按风险等级管控调用权限</div>

    <div class="toolbar">
      <t-select
        v-model="svcFilter"
        placeholder="全部服务"
        clearable
        style="width: 150px"
        :options="svcOptions"
      />
      <t-select v-model="riskFilter" style="width: 150px">
        <t-option value="all" label="全部风险" />
        <t-option value="low" label="低风险" />
        <t-option value="medium" label="中风险" />
        <t-option value="high" label="高风险" />
      </t-select>
      <t-input v-model="keyword" placeholder="搜索工具名称…" style="width: 260px" clearable />
      <div class="spacer" />
      <t-button variant="outline" theme="default" @click="load">刷新</t-button>
    </div>

    <div class="card" style="margin-top: 16px">
      <div style="display: flex; align-items: center; margin-bottom: 8px">
        <span class="card-title">工具列表</span>
        <span class="sub-text" style="margin-left: 12px">共 {{ filtered.length }} 个工具</span>
      </div>
      <t-table
        row-key="id"
        :data="filtered"
        :columns="columns"
        :loading="loading"
        :hover="true"
        :bordered="false"
        :pagination="{ defaultPageSize: 10 }"
      >
        <template #effective_name="{ row }">
          <span class="text-strong">{{ row.effective_name }}</span>
        </template>
        <template #risk="{ row }">
          <t-tag :theme="RISK_TONE[row.risk as keyof typeof RISK_TONE]" variant="light">
            {{ RISK_LABEL[row.risk as keyof typeof RISK_LABEL] }}
          </t-tag>
        </template>
        <template #enabled="{ row }">
          <t-switch :value="row.enabled" @change="(v: unknown) => toggleEnabled(row, Boolean(v))" />
        </template>
        <template #available="{ row }">
          <t-tag :theme="row.available ? 'success' : 'default'" variant="light">
            {{ row.available ? '可用' : '不可用' }}
          </t-tag>
        </template>
        <template #discovered_at="{ row }">{{ fmtTime(row.discovered_at) }}</template>
        <template #op="{ row }">
          <t-button variant="text" theme="primary" size="small" @click="openEdit(row)">编辑</t-button>
        </template>
      </t-table>
    </div>

    <ToolDrawer v-model:visible="drawerVisible" :tool="editingTool" @saved="load" />
  </div>
</template>
