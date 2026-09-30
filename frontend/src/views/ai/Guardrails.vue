<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import {
  bulkGuardrails,
  deleteGuardrail,
  listGuardrails,
  updateGuardrail,
} from '@/api/ai'
import type { AiAction, AiScope, GuardrailRule } from '@/api/ai-types'
import { AI_ACTION_LABEL, AI_SCOPE_LABEL } from '@/utils/labels'
import GuardrailDrawer from '@/components/ai/GuardrailDrawer.vue'

const rules = ref<GuardrailRule[]>([])
const loading = ref(true)

const drawerVisible = ref(false)
const editingRule = ref<GuardrailRule | null>(null)

// 批量粘贴导入
const bulkVisible = ref(false)
const bulkText = ref('')
const bulkScope = ref<AiScope>('both')
const bulkAction = ref<AiAction>('block')
const bulkEnabled = ref(true)
const bulkNamePrefix = ref('')
const bulkSubmitting = ref(false)
const bulkCount = computed(() =>
  bulkText.value.split('\n').map((s) => s.trim()).filter(Boolean).length,
)

async function load() {
  loading.value = true
  try {
    rules.value = await listGuardrails()
  } catch {
    // 错误提示由拦截器弹出
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openCreate() {
  editingRule.value = null
  drawerVisible.value = true
}
function openEdit(row: GuardrailRule) {
  editingRule.value = row
  drawerVisible.value = true
}
function onSaved() {
  load()
}

function toggleEnabled(row: GuardrailRule) {
  updateGuardrail(row.id, { enabled: !row.enabled }).then(load)
}

function remove(row: GuardrailRule) {
  const dialog = DialogPlugin.confirm({
    header: '删除规则',
    body: `确定删除规则「${row.name}」吗？操作不可恢复。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    onConfirm: async () => {
      await deleteGuardrail(row.id)
      dialog.destroy()
      MessagePlugin.success('规则已删除')
      load()
    },
  })
}

function openBulk() {
  bulkText.value = ''
  bulkScope.value = 'both'
  bulkAction.value = 'block'
  bulkEnabled.value = true
  bulkNamePrefix.value = ''
  bulkVisible.value = true
}

async function doBulk() {
  if (bulkCount.value === 0) {
    MessagePlugin.warning('请至少粘贴一行关键词')
    return
  }
  bulkSubmitting.value = true
  try {
    const result = await bulkGuardrails({
      text: bulkText.value,
      scope: bulkScope.value,
      action: bulkAction.value,
      name_prefix: bulkNamePrefix.value.trim() || undefined,
      enabled: bulkEnabled.value,
    })
    MessagePlugin.success(`批量导入完成：新建 ${result.created}，跳过 ${result.skipped}`)
    bulkVisible.value = false
    load()
  } catch {
    // 错误提示由拦截器统一弹出
  } finally {
    bulkSubmitting.value = false
  }
}

const columns = [
  { colKey: 'name', title: '规则名', width: 200 },
  { colKey: 'pattern', title: '关键词', ellipsis: true },
  { colKey: 'scope', title: '作用域', width: 120 },
  { colKey: 'action', title: '动作', width: 90 },
  { colKey: 'enabled', title: '启用', width: 90 },
  { colKey: 'op', title: '操作', width: 180 },
]
</script>

<template>
  <div class="page">
    <div class="page-title">护栏规则</div>
    <div class="page-sub">敏感词 / 关键词护栏：命中即拦截调用，支持批量粘贴导入</div>

    <div class="toolbar">
      <div class="spacer" />
      <t-button variant="outline" theme="primary" @click="openBulk">批量粘贴导入</t-button>
      <t-button theme="primary" @click="openCreate">新建规则</t-button>
    </div>

    <div class="card" style="margin-top: 16px">
      <div style="display: flex; align-items: center; margin-bottom: 8px">
        <span class="card-title">规则列表</span>
        <span class="sub-text" style="margin-left: 12px">共 {{ rules.length }} 条规则</span>
      </div>
      <t-table
        row-key="id"
        :data="rules"
        :columns="columns"
        :loading="loading"
        :hover="true"
        :bordered="false"
        :pagination="{ defaultPageSize: 10 }"
      >
        <template #name="{ row }">
          <span class="text-strong">{{ row.name }}</span>
        </template>
        <template #pattern="{ row }">
          <code class="pattern">{{ row.pattern }}</code>
        </template>
        <template #scope="{ row }">
          {{ AI_SCOPE_LABEL[row.scope as keyof typeof AI_SCOPE_LABEL] }}
        </template>
        <template #action="{ row }">
          {{ AI_ACTION_LABEL[row.action as keyof typeof AI_ACTION_LABEL] }}
        </template>
        <template #enabled="{ row }">
          <t-tag :theme="row.enabled ? 'success' : 'default'" variant="light">
            {{ row.enabled ? '已启用' : '已停用' }}
          </t-tag>
        </template>
        <template #op="{ row }">
          <t-button variant="text" theme="primary" size="small" @click="openEdit(row)">编辑</t-button>
          <t-button variant="text" theme="primary" size="small" @click="toggleEnabled(row)">
            {{ row.enabled ? '停用' : '启用' }}
          </t-button>
          <t-button variant="text" theme="danger" size="small" @click="remove(row)">删除</t-button>
        </template>
      </t-table>
    </div>

    <GuardrailDrawer
      v-model:visible="drawerVisible"
      :rule="editingRule"
      @saved="onSaved"
    />

    <!-- 批量粘贴：每行一个关键词，后端按换行拆分 -->
    <t-dialog
      v-model:visible="bulkVisible"
      header="批量粘贴导入"
      :confirm-btn="{ content: `导入（${bulkCount}）`, loading: bulkSubmitting, disabled: bulkCount === 0 }"
      width="600px"
      @confirm="doBulk"
    >
      <t-alert theme="info" message="每行一个关键词，空行自动忽略；相同关键词会被跳过（skipped）。" style="margin-bottom: 16px" />
      <t-form label-align="top">
        <t-form-item label="关键词文本（每行一个）">
          <t-textarea
            v-model="bulkText"
            placeholder="敏感词一&#10;敏感词二&#10;敏感词三"
            :autosize="{ minRows: 6, maxRows: 12 }"
          />
        </t-form-item>
        <div style="display: flex; gap: 12px">
          <t-form-item label="作用域" style="flex: 1">
            <t-select v-model="bulkScope">
              <t-option value="request" :label="AI_SCOPE_LABEL.request" />
              <t-option value="response" :label="AI_SCOPE_LABEL.response" />
              <t-option value="both" :label="AI_SCOPE_LABEL.both" />
            </t-select>
          </t-form-item>
          <t-form-item label="动作" style="flex: 1">
            <t-select v-model="bulkAction">
              <t-option value="block" :label="AI_ACTION_LABEL.block" />
            </t-select>
          </t-form-item>
        </div>
        <t-form-item label="规则名前缀（可选）">
          <t-input
            v-model="bulkNamePrefix"
            placeholder="留空则用关键词本身作为规则名"
            tips="规则名 = 前缀 + 序号；便于在列表中归类"
          />
        </t-form-item>
        <t-form-item label="导入后启用">
          <t-switch v-model="bulkEnabled" />
        </t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<style scoped>
.pattern {
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: 13px;
  color: var(--color-text-secondary);
}
</style>
