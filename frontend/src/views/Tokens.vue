<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { getToken, listServices, listTokens, listTools, revokeToken } from '@/api'
import type { Service, TokenItem, Tool } from '@/api/types'
import { fmtDateTime } from '@/utils/format'
import TokenDrawer from '@/components/TokenDrawer.vue'

const tokens = ref<TokenItem[]>([])
const services = ref<Service[]>([])
const tools = ref<Tool[]>([])
const loading = ref(true)

const drawerVisible = ref(false)
const drawerMode = ref<'create' | 'policy'>('create')
const editingToken = ref<TokenItem | null>(null)

const plaintext = ref('')
const plaintextVisible = ref(false)

async function load() {
  loading.value = true
  try {
    tokens.value = await listTokens()
  } finally {
    loading.value = false
  }
}
onMounted(async () => {
  await load()
  try {
    ;[services.value, tools.value] = await Promise.all([listServices(), listTools()])
  } catch {
    // 列表失败不阻塞凭证页
  }
})

function openCreate() {
  drawerMode.value = 'create'
  editingToken.value = null
  drawerVisible.value = true
}

async function openPolicy(row: TokenItem) {
  // 表格里的行不携带完整策略时再拉一次详情（当前接口会返回全量，稳妥起见仍刷新）
  try {
    editingToken.value = await getToken(row.id)
    drawerMode.value = 'policy'
    drawerVisible.value = true
  } catch {
    // 错误提示由拦截器弹出
  }
}

function showPlaintext(token: string) {
  plaintext.value = token
  plaintextVisible.value = true
}

function copyPlaintext() {
  navigator.clipboard
    .writeText(plaintext.value)
    .then(() => MessagePlugin.success('已复制到剪贴板'))
    .catch(() => MessagePlugin.warning('复制失败，请手动选择复制'))
}

function revoke(row: TokenItem) {
  const dialog = DialogPlugin.confirm({
    header: '撤销凭证',
    body: `确定撤销凭证「${row.name}」吗？撤销后该令牌立即失效，操作不可恢复。`,
    confirmBtn: { content: '撤销', theme: 'danger' },
    onConfirm: async () => {
      await revokeToken(row.id)
      dialog.destroy()
      MessagePlugin.success('凭证已撤销')
      load()
    },
  })
}

const columns = [
  { colKey: 'name', title: '名称', width: 200 },
  { colKey: 'token_prefix', title: '前缀', width: 140 },
  { colKey: 'status', title: '状态', width: 100 },
  { colKey: 'allow_high_risk', title: '允许高危', width: 100 },
  { colKey: 'created_at', title: '创建时间', width: 170 },
  { colKey: 'last_used_at', title: '最近使用', width: 170 },
  { colKey: 'op', title: '操作', width: 140 },
]
</script>

<template>
  <div class="page">
    <div class="page-title">访问凭证</div>
    <div class="page-sub">管理网关令牌（Token）与三级调用授权：可见服务 → 可用工具 → 强制参数</div>

    <div class="toolbar">
      <div class="spacer" />
      <t-button theme="primary" @click="openCreate">新建凭证</t-button>
    </div>

    <div class="card" style="margin-top: 16px">
      <div style="display: flex; align-items: center; margin-bottom: 8px">
        <span class="card-title">凭证列表</span>
        <span class="sub-text" style="margin-left: 12px">共 {{ tokens.length }} 个凭证</span>
      </div>
      <t-table
        row-key="id"
        :data="tokens"
        :columns="columns"
        :loading="loading"
        :hover="true"
        :bordered="false"
        :pagination="{ defaultPageSize: 10 }"
      >
        <template #name="{ row }">
          <span class="text-strong">{{ row.name }}</span>
        </template>
        <template #token_prefix="{ row }">
          <code class="prefix">{{ row.token_prefix }}…</code>
        </template>
        <template #status="{ row }">
          <t-tag :theme="row.revoked_at ? 'default' : row.enabled ? 'success' : 'warning'" variant="light">
            {{ row.revoked_at ? '已撤销' : row.enabled ? '启用' : '已停用' }}
          </t-tag>
        </template>
        <template #allow_high_risk="{ row }">
          <t-tag :theme="row.allow_high_risk ? 'danger' : 'default'" variant="light">
            {{ row.allow_high_risk ? '是' : '否' }}
          </t-tag>
        </template>
        <template #created_at="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        <template #last_used_at="{ row }">
          <span :class="{ muted: !row.last_used_at }">
            {{ row.last_used_at ? fmtDateTime(row.last_used_at) : '从未使用' }}
          </span>
        </template>
        <template #op="{ row }">
          <t-button
            variant="text"
            theme="primary"
            size="small"
            :disabled="row.revoked_at != null"
            @click="openPolicy(row)"
          >
            策略
          </t-button>
          <t-button
            variant="text"
            theme="danger"
            size="small"
            :disabled="row.revoked_at != null"
            @click="revoke(row)"
          >
            撤销
          </t-button>
        </template>
      </t-table>
    </div>

    <TokenDrawer
      v-model:visible="drawerVisible"
      :mode="drawerMode"
      :token="editingToken"
      :services="services"
      :tools="tools"
      @saved="load"
      @created="showPlaintext"
    />

    <!-- 明文 token 只在创建时返回一次，这里集中展示并提醒 -->
    <t-dialog
      v-model:visible="plaintextVisible"
      header="请立即保存令牌"
      :confirm-btn="{ content: '我已保存', theme: 'primary' }"
      @confirm="plaintextVisible = false"
    >
      <t-alert theme="warning" message="明文令牌仅此一次展示，关闭后无法再次查看，请立即复制保存。" />
      <div class="token-box">
        <code>{{ plaintext }}</code>
      </div>
      <t-button variant="outline" theme="default" block @click="copyPlaintext">复制令牌</t-button>
    </t-dialog>
  </div>
</template>

<style scoped>
.prefix {
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: 13px;
  color: var(--color-text-secondary);
}
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
