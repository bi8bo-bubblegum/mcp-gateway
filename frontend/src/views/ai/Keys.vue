<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import {
  getKey,
  listKeys,
  listModels,
  listUsageEvents,
  revokeKey,
} from '@/api/ai'
import type { AiKey, AiModel, AiUsageEvent } from '@/api/ai-types'
import { AI_PERIOD_LABEL, AI_STATUS_LABEL, AI_STATUS_TONE } from '@/utils/labels'
import { fmtDuration, fmtTime, todayStartISO } from '@/utils/format'
import AiKeyDrawer from '@/components/ai/AiKeyDrawer.vue'

// 表格行：在 AiKey 基础上补充「今日用量」（列表接口不直接给，单独聚合）
interface KeyRow extends AiKey {
  todayUsage: number
}

const keys = ref<KeyRow[]>([])
const models = ref<AiModel[]>([])
const loading = ref(true)

const drawerVisible = ref(false)
const drawerMode = ref<'create' | 'policy'>('create')
const editingKey = ref<AiKey | null>(null)

const plaintext = ref('')
const plaintextVisible = ref(false)

// 用量抽屉
const usageVisible = ref(false)
const usageKey = ref<AiKey | null>(null)
const usageItems = ref<AiUsageEvent[]>([])
const usageLoading = ref(false)

const modelCount = (k: AiKey) => k.model_ids?.length ?? 0

async function load() {
  loading.value = true
  try {
    const [k, m] = await Promise.all([listKeys(), listModels()])
    models.value = m
    // 逐 Key 聚合今日用量（列表缺失时静默跳过，避免阻塞主表）
    const rows = await Promise.all(
      k.map(async (item) => {
        let todayUsage = 0
        try {
          const usage = await listUsageEvents({
            key_id: item.id,
            started_after: todayStartISO(),
            limit: 1,
          })
          todayUsage = usage.total
        } catch {
          // 忽略单条聚合失败
        }
        return { ...item, todayUsage }
      }),
    )
    keys.value = rows
  } catch {
    // 列表错误提示由拦截器弹出
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openCreate() {
  drawerMode.value = 'create'
  editingKey.value = null
  drawerVisible.value = true
}

async function openPolicy(row: AiKey) {
  // 列表不一定带 model_ids，打开前拉一次详情保证白名单完整
  try {
    editingKey.value = await getKey(row.id)
    drawerMode.value = 'policy'
    drawerVisible.value = true
  } catch {
    // 错误提示由拦截器弹出
  }
}

function showPlaintext(plainKey: string) {
  plaintext.value = plainKey
  plaintextVisible.value = true
}

function copyPlaintext() {
  navigator.clipboard
    .writeText(plaintext.value)
    .then(() => MessagePlugin.success('已复制到剪贴板'))
    .catch(() => MessagePlugin.warning('复制失败，请手动选择复制'))
}

function revoke(row: AiKey) {
  const dialog = DialogPlugin.confirm({
    header: '撤销密钥',
    body: `确定撤销密钥「${row.name}」吗？撤销后该密钥立即失效，操作不可恢复。`,
    confirmBtn: { content: '撤销', theme: 'danger' },
    onConfirm: async () => {
      await revokeKey(row.id)
      dialog.destroy()
      MessagePlugin.success('密钥已撤销')
      load()
    },
  })
}

async function openUsage(row: AiKey) {
  usageKey.value = row
  usageVisible.value = true
  usageLoading.value = true
  try {
    const result = await listUsageEvents({ key_id: row.id, limit: 50, offset: 0 })
    usageItems.value = result.items
  } catch {
    // 错误提示由拦截器弹出
  } finally {
    usageLoading.value = false
  }
}

const columns = [
  { colKey: 'name', title: '名称', width: 180 },
  { colKey: 'key_prefix', title: '前缀', width: 130 },
  { colKey: 'owner', title: '归属', width: 120 },
  { colKey: 'modelCount', title: '授权模型', width: 90 },
  { colKey: 'quota', title: '配额', width: 180, ellipsis: true },
  { colKey: 'todayUsage', title: '今日用量', width: 100 },
  { colKey: 'status', title: '状态', width: 100 },
  { colKey: 'op', title: '操作', width: 230 },
]
</script>

<template>
  <div class="page">
    <div class="page-title">AI Key</div>
    <div class="page-sub">分发对外 AI 调用密钥，配置模型白名单、token 配额与限流</div>

    <div class="toolbar">
      <div class="spacer" />
      <t-button theme="primary" @click="openCreate">新建密钥</t-button>
    </div>

    <div class="card" style="margin-top: 16px">
      <div style="display: flex; align-items: center; margin-bottom: 8px">
        <span class="card-title">密钥列表</span>
        <span class="sub-text" style="margin-left: 12px">共 {{ keys.length }} 个密钥</span>
      </div>
      <t-table
        row-key="id"
        :data="keys"
        :columns="columns"
        :loading="loading"
        :hover="true"
        :bordered="false"
        :pagination="{ defaultPageSize: 10 }"
      >
        <template #name="{ row }">
          <span class="text-strong">{{ row.name }}</span>
        </template>
        <template #key_prefix="{ row }">
          <code class="prefix">{{ row.key_prefix }}…</code>
        </template>
        <template #owner="{ row }">
          <span :class="{ muted: !row.owner }">{{ row.owner ?? '—' }}</span>
        </template>
        <template #modelCount="{ row }">{{ modelCount(row) }}</template>
        <template #quota="{ row }">
          <span v-if="row.period === 'none'">不限</span>
          <span v-else>
            {{ AI_PERIOD_LABEL[row.period as keyof typeof AI_PERIOD_LABEL] }}
            {{ row.period_token_limit != null ? row.period_token_limit.toLocaleString() : '—' }}
          </span>
        </template>
        <template #todayUsage="{ row }">{{ row.todayUsage.toLocaleString() }}</template>
        <template #status="{ row }">
          <t-tag :theme="row.revoked_at ? 'default' : row.enabled ? 'success' : 'warning'" variant="light">
            {{ row.revoked_at ? '已撤销' : row.enabled ? '启用' : '已停用' }}
          </t-tag>
        </template>
        <template #op="{ row }">
          <t-button variant="text" theme="primary" size="small" :disabled="row.revoked_at != null" @click="openPolicy(row)">策略</t-button>
          <t-button variant="text" theme="primary" size="small" @click="openUsage(row)">用量</t-button>
          <t-button variant="text" theme="danger" size="small" :disabled="row.revoked_at != null" @click="revoke(row)">撤销</t-button>
        </template>
      </t-table>
    </div>

    <AiKeyDrawer
      v-model:visible="drawerVisible"
      :key="editingKey?.id ?? 'create'"
      :ai-key="editingKey"
      :models="models"
      @saved="load"
      @created="showPlaintext"
    />

    <!-- 明文 key 只在创建时返回一次，受控弹窗显式关闭 -->
    <t-dialog
      v-model:visible="plaintextVisible"
      header="请立即保存密钥"
      :confirm-btn="{ content: '我已保存', theme: 'primary' }"
      @confirm="plaintextVisible = false"
    >
      <t-alert theme="warning" message="明文的 AI Key 仅此一次展示，关闭后无法再次查看，请立即复制保存。" />
      <div class="token-box">
        <code>{{ plaintext }}</code>
      </div>
      <t-button variant="outline" theme="default" block @click="copyPlaintext">复制密钥</t-button>
    </t-dialog>

    <!-- 用量抽屉：查看该密钥的调用明细 -->
    <t-drawer
      :visible="usageVisible"
      :header="`用量明细 · ${usageKey?.name ?? ''}`"
      size="640px"
      @close="usageVisible = false"
    >
      <t-table
        row-key="id"
        :data="usageItems"
        :loading="usageLoading"
        :columns="[
          { colKey: 'started_at', title: '时间', width: 110 },
          { colKey: 'model_alias', title: '模型', ellipsis: true },
          { colKey: 'status', title: '状态', width: 90 },
          { colKey: 'total_tokens', title: 'Tokens', width: 100 },
          { colKey: 'latency_ms', title: '耗时', width: 90 },
        ]"
        :hover="true"
        :bordered="false"
        :pagination="{ defaultPageSize: 10 }"
      >
        <template #started_at="{ row }">{{ fmtTime(row.started_at) }}</template>
        <template #status="{ row }">
          <t-tag :theme="AI_STATUS_TONE[row.status as keyof typeof AI_STATUS_TONE]" variant="light">
            {{ AI_STATUS_LABEL[row.status as keyof typeof AI_STATUS_LABEL] }}
          </t-tag>
        </template>
        <template #total_tokens="{ row }">{{ (row.total_tokens ?? 0).toLocaleString() }}</template>
        <template #latency_ms="{ row }">{{ fmtDuration(row.latency_ms) }}</template>
      </t-table>
    </t-drawer>
  </div>
</template>

<style scoped>
.prefix {
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.muted { color: var(--color-text-muted); }
.token-box {
  margin: 16px 0;
  padding: 12px;
  background: var(--color-bg-page);
  border-radius: var(--radius-control);
  word-break: break-all;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: 13px;
}
</style>
