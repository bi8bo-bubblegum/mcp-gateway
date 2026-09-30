<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import {
  checkServiceHealth,
  deleteService,
  disableService,
  enableService,
  listServices,
  refreshService,
} from '@/api'
import type { Service } from '@/api/types'
import { HEALTH_LABEL, HEALTH_TONE } from '@/utils/labels'
import { fromNow } from '@/utils/format'
import ServiceDrawer from '@/components/ServiceDrawer.vue'

const services = ref<Service[]>([])
const loading = ref(true)
const keyword = ref('')
const statusFilter = ref<'all' | 'enabled' | 'disabled'>('all')

const drawerVisible = ref(false)
const editingService = ref<Service | null>(null)

const filtered = computed(() =>
  services.value
    .filter((s) => {
      if (statusFilter.value === 'enabled' && !s.enabled) return false
      if (statusFilter.value === 'disabled' && s.enabled) return false
      const kw = keyword.value.trim().toLowerCase()
      if (!kw) return true
      return s.name.toLowerCase().includes(kw) || s.slug.toLowerCase().includes(kw)
    })
    .sort((a, b) => a.slug.localeCompare(b.slug)),
)

async function load() {
  loading.value = true
  try {
    services.value = await listServices()
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openCreate() {
  editingService.value = null
  drawerVisible.value = true
}
function openEdit(row: Service) {
  editingService.value = row
  drawerVisible.value = true
}

function onSaved() {
  load()
}

function refresh(row: Service) {
  refreshService(row.id).then((result) => {
    MessagePlugin.success(
      `刷新完成：发现 ${result.discovered}，新增 ${result.created}，更新 ${result.updated}，移除 ${result.removed}`,
    )
    load()
  })
}

function checkHealth(row: Service) {
  checkServiceHealth(row.id).then(() => {
    MessagePlugin.success(`健康检查完成：${row.slug} 当前为「${HEALTH_LABEL[row.health]}」状态`)
    load()
  })
}

function toggleEnabled(row: Service) {
  const call = row.enabled ? disableService : enableService
  call(row.id).then(load)
}

function remove(row: Service) {
  const dialog = DialogPlugin.confirm({
    header: '删除服务',
    body: `确定删除服务「${row.slug}」吗？该服务的工具与策略关联会一并删除，操作不可恢复。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    onConfirm: async () => {
      await deleteService(row.id)
      dialog.destroy()
      MessagePlugin.success('服务已删除')
      load()
    },
  })
}

const columns = [
  { colKey: 'name', title: '服务名称', width: 220 },
  { colKey: 'url', title: 'URL', ellipsis: true }, // 弹性列：随容器伸缩
  { colKey: 'enabled', title: '启用状态', width: 90 },
  { colKey: 'health', title: '健康', width: 90 },
  { colKey: 'consecutive_failures', title: '失败次数', width: 90 },
  { colKey: 'last_checked_at', title: '最后检查', width: 100 },
  { colKey: 'op', title: '操作', width: 175 },
]
</script>

<template>
  <div class="page">
    <div class="page-title">上游服务</div>
    <div class="page-sub">管理接入网关的 MCP 上游服务（Streamable HTTP）</div>

    <div class="toolbar">
      <t-input v-model="keyword" placeholder="搜索服务名称、slug…" style="width: 280px" clearable />
      <t-select v-model="statusFilter" style="width: 140px">
        <t-option value="all" label="全部状态" />
        <t-option value="enabled" label="已启用" />
        <t-option value="disabled" label="已停用" />
      </t-select>
      <div class="spacer" />
      <t-button theme="primary" @click="openCreate">新建服务</t-button>
    </div>

    <div class="card" style="margin-top: 16px">
      <div style="display: flex; align-items: center; margin-bottom: 8px">
        <span class="card-title">服务列表</span>
        <span class="sub-text" style="margin-left: 12px">共 {{ filtered.length }} 个服务</span>
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
        <template #name="{ row }">
          <span class="text-strong">{{ row.name }}</span>
          <span class="muted"> · {{ row.slug }}</span>
        </template>
        <template #enabled="{ row }">
          <t-tag :theme="row.enabled ? 'success' : 'default'" variant="light">
            {{ row.enabled ? '已启用' : '已停用' }}
          </t-tag>
        </template>
        <template #health="{ row }">
          <t-tag :theme="HEALTH_TONE[row.health as keyof typeof HEALTH_TONE]" variant="light">
            ● {{ HEALTH_LABEL[row.health as keyof typeof HEALTH_LABEL] }}
          </t-tag>
        </template>
        <template #consecutive_failures="{ row }">
          <span :style="{ color: row.consecutive_failures > 0 ? 'var(--color-danger)' : undefined }">
            {{ row.consecutive_failures }}
          </span>
        </template>
        <template #last_checked_at="{ row }">{{ fromNow(row.last_checked_at) }}</template>
        <template #op="{ row }">
          <t-button variant="text" theme="primary" size="small" @click="openEdit(row)">编辑</t-button>
          <t-button variant="text" theme="primary" size="small" @click="refresh(row)">刷新</t-button>
          <t-button variant="text" theme="primary" size="small" @click="checkHealth(row)">健康</t-button>
          <t-button variant="text" theme="primary" size="small" @click="toggleEnabled(row)">
            {{ row.enabled ? '停用' : '启用' }}
          </t-button>
          <t-button variant="text" theme="danger" size="small" @click="remove(row)">删除</t-button>
        </template>
      </t-table>
    </div>

    <ServiceDrawer
      v-model:visible="drawerVisible"
      :service="editingService"
      @saved="onSaved"
    />
  </div>
</template>
