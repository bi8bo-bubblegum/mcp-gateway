<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import {
  checkProviderHealth,
  deleteProvider,
  disableProvider,
  enableProvider,
  listProviders,
} from '@/api/ai'
import type { AiProvider } from '@/api/ai-types'
import { HEALTH_LABEL, HEALTH_TONE } from '@/utils/labels'
import { fromNow } from '@/utils/format'
import ProviderDrawer from '@/components/ai/ProviderDrawer.vue'

const providers = ref<AiProvider[]>([])
const loading = ref(true)
const keyword = ref('')
const statusFilter = ref<'all' | 'enabled' | 'disabled'>('all')

const drawerVisible = ref(false)
const editingProvider = ref<AiProvider | null>(null)

const filtered = computed(() =>
  providers.value
    .filter((p) => {
      if (statusFilter.value === 'enabled' && !p.enabled) return false
      if (statusFilter.value === 'disabled' && p.enabled) return false
      const kw = keyword.value.trim().toLowerCase()
      if (!kw) return true
      return p.name.toLowerCase().includes(kw) || p.slug.toLowerCase().includes(kw)
    })
    .sort((a, b) => a.slug.localeCompare(b.slug)),
)

async function load() {
  loading.value = true
  try {
    providers.value = await listProviders()
  } catch {
    // 错误提示由拦截器弹出
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openCreate() {
  editingProvider.value = null
  drawerVisible.value = true
}
function openEdit(row: AiProvider) {
  editingProvider.value = row
  drawerVisible.value = true
}
function onSaved() {
  load()
}

function checkHealth(row: AiProvider) {
  checkProviderHealth(row.id).then(() => {
    MessagePlugin.success(`健康检查完成：${row.slug} 当前为「${HEALTH_LABEL[row.health]}」状态`)
    load()
  })
}

function toggleEnabled(row: AiProvider) {
  const call = row.enabled ? disableProvider : enableProvider
  call(row.id).then(load)
}

function remove(row: AiProvider) {
  const dialog = DialogPlugin.confirm({
    header: '删除厂商',
    body: `确定删除厂商「${row.slug}」吗？该厂商下的模型与关联会一并删除，操作不可恢复。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    onConfirm: async () => {
      await deleteProvider(row.id)
      dialog.destroy()
      MessagePlugin.success('厂商已删除')
      load()
    },
  })
}

const columns = [
  { colKey: 'name', title: '厂商名称', width: 220 },
  { colKey: 'base_url', title: 'Base URL', ellipsis: true },
  { colKey: 'enabled', title: '启用', width: 90 },
  { colKey: 'health', title: '健康', width: 90 },
  { colKey: 'consecutive_failures', title: '失败次数', width: 90 },
  { colKey: 'last_checked_at', title: '最后检查', width: 110 },
  { colKey: 'op', title: '操作', width: 195 },
]
</script>

<template>
  <div class="page">
    <div class="page-title">厂商管理</div>
    <div class="page-sub">管理接入 AI 网关的上游厂商 / 中转（OpenAI 兼容端点）</div>

    <div class="toolbar">
      <t-input v-model="keyword" placeholder="搜索厂商名称、slug…" style="width: 280px" clearable />
      <t-select v-model="statusFilter" style="width: 140px">
        <t-option value="all" label="全部状态" />
        <t-option value="enabled" label="已启用" />
        <t-option value="disabled" label="已停用" />
      </t-select>
      <div class="spacer" />
      <t-button theme="primary" @click="openCreate">新建厂商</t-button>
    </div>

    <div class="card" style="margin-top: 16px">
      <div style="display: flex; align-items: center; margin-bottom: 8px">
        <span class="card-title">厂商列表</span>
        <span class="sub-text" style="margin-left: 12px">共 {{ filtered.length }} 个厂商</span>
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
          <t-button variant="text" theme="primary" size="small" @click="checkHealth(row)">健康</t-button>
          <t-button variant="text" theme="primary" size="small" @click="toggleEnabled(row)">
            {{ row.enabled ? '停用' : '启用' }}
          </t-button>
          <t-button variant="text" theme="danger" size="small" @click="remove(row)">删除</t-button>
        </template>
      </t-table>
    </div>

    <ProviderDrawer
      v-model:visible="drawerVisible"
      :provider="editingProvider"
      @saved="onSaved"
    />
  </div>
</template>
