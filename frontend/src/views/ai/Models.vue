<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import {
  deleteModel,
  importModels,
  listModels,
  listProviders,
  pullModels,
} from '@/api/ai'
import type { AiKind, AiModel, AiModelPullCandidate, AiProvider } from '@/api/ai-types'
import { AI_KIND_LABEL } from '@/utils/labels'

const models = ref<AiModel[]>([])
const providers = ref<AiProvider[]>([])
const loading = ref(true)

const keyword = ref('')
const providerFilter = ref<number | undefined>(undefined)
const kindFilter = ref<'all' | AiKind>('all')

const drawerVisible = ref(false)
const editingModel = ref<AiModel | null>(null)

const providerName = computed(() => {
  const map = new Map(providers.value.map((p) => [p.id, p]))
  return (id: number) => map.get(id)?.name ?? `厂商#${id}`
})

const filtered = computed(() =>
  models.value
    .filter((m) => {
      if (providerFilter.value != null && m.provider_id !== providerFilter.value) return false
      if (kindFilter.value !== 'all' && m.kind !== kindFilter.value) return false
      const kw = keyword.value.trim().toLowerCase()
      if (!kw) return true
      return (
        m.alias.toLowerCase().includes(kw) ||
        m.provider_model_name.toLowerCase().includes(kw)
      )
    })
    .sort((a, b) => a.alias.localeCompare(b.alias)),
)

async function load() {
  loading.value = true
  try {
    const [m, p] = await Promise.all([listModels(), listProviders()])
    models.value = m
    providers.value = p
  } catch {
    // 错误提示由拦截器弹出
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openCreate() {
  editingModel.value = null
  drawerVisible.value = true
}
function openEdit(row: AiModel) {
  editingModel.value = row
  drawerVisible.value = true
}
function onSaved() {
  load()
}

function remove(row: AiModel) {
  const dialog = DialogPlugin.confirm({
    header: '删除模型',
    body: `确定删除模型「${row.alias}」吗？操作不可恢复。`,
    confirmBtn: { content: '删除', theme: 'danger' },
    onConfirm: async () => {
      await deleteModel(row.id)
      dialog.destroy()
      MessagePlugin.success('模型已删除')
      load()
    },
  })
}

// ---------------- 从上游拉取 ----------------
const pullVisible = ref(false)
const pullProviderId = ref<number | undefined>(undefined)
const candidates = ref<AiModelPullCandidate[]>([])
const selected = reactive<Record<string, boolean>>({}) // 以 provider_model_name 为 key
const kindOf = reactive<Record<string, AiKind>>({})
const pulling = ref(false)
const importing = ref(false)

const providerOptions = computed(() =>
  providers.value.map((p) => ({ value: p.id, label: `${p.name} · ${p.slug}` })),
)

function openPull() {
  pullProviderId.value = providers.value[0]?.id
  candidates.value = []
  Object.keys(selected).forEach((k) => delete selected[k])
  Object.keys(kindOf).forEach((k) => delete kindOf[k])
  pullVisible.value = true
}

async function fetchCandidates() {
  if (pullProviderId.value == null) {
    MessagePlugin.warning('请先选择厂商')
    return
  }
  pulling.value = true
  try {
    const list = await pullModels(pullProviderId.value)
    candidates.value = list
    // 默认全选，类型默认 chat
    for (const c of list) {
      selected[c.id] = true
      if (kindOf[c.id] == null) kindOf[c.id] = 'chat'
    }
  } catch {
    // 错误提示由拦截器弹出
  } finally {
    pulling.value = false
  }
}

const selectedCount = computed(() => candidates.value.filter((c) => selected[c.id]).length)

async function doImport() {
  if (pullProviderId.value == null) return
  const items = candidates.value
    .filter((c) => selected[c.id])
    .map((c) => ({
      provider_model_name: c.id,
      alias: c.id, // 缺省用上游名作为对外名，创建后可在模型管理里改名
      kind: kindOf[c.id] ?? ('chat' as AiKind),
    }))
  if (!items.length) {
    MessagePlugin.warning('请至少勾选一个模型')
    return
  }
  importing.value = true
  try {
    const result = await importModels(pullProviderId.value, items)
    MessagePlugin.success(`导入完成：新建 ${result.created}，跳过 ${result.skipped}`)
    pullVisible.value = false
    load()
  } catch {
    // 错误提示由拦截器弹出
  } finally {
    importing.value = false
  }
}

const columns = [
  { colKey: 'alias', title: '对外名', width: 200 },
  { colKey: 'provider_model_name', title: '上游名', ellipsis: true },
  { colKey: 'provider_id', title: '厂商', width: 160 },
  { colKey: 'kind', title: '类型', width: 90 },
  { colKey: 'price', title: '单价(千tok)', width: 150, ellipsis: true },
  { colKey: 'enabled', title: '启用', width: 90 },
  { colKey: 'op', title: '操作', width: 140 },
]
</script>

<template>
  <div class="page">
    <div class="page-title">模型管理</div>
    <div class="page-sub">维护对外暴露的模型别名与上游映射；支持从上游一键拉取批量导入</div>

    <div class="toolbar">
      <t-input v-model="keyword" placeholder="搜索别名、上游名…" style="width: 240px" clearable />
      <t-select
        v-model="providerFilter"
        :options="providerOptions"
        placeholder="全部厂商"
        clearable
        filterable
        style="width: 180px"
      />
      <t-select v-model="kindFilter" style="width: 130px">
        <t-option value="all" label="全部类型" />
        <t-option value="chat" :label="AI_KIND_LABEL.chat" />
        <t-option value="embedding" :label="AI_KIND_LABEL.embedding" />
      </t-select>
      <div class="spacer" />
      <t-button variant="outline" theme="primary" @click="openPull">从上游拉取</t-button>
      <t-button theme="primary" @click="openCreate">新建模型</t-button>
    </div>

    <div class="card" style="margin-top: 16px">
      <div style="display: flex; align-items: center; margin-bottom: 8px">
        <span class="card-title">模型列表</span>
        <span class="sub-text" style="margin-left: 12px">共 {{ filtered.length }} 个模型</span>
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
        <template #alias="{ row }">
          <span class="text-strong">{{ row.alias }}</span>
        </template>
        <template #provider_id="{ row }">{{ providerName(row.provider_id) }}</template>
        <template #kind="{ row }">
          <t-tag :theme="row.kind === 'chat' ? 'primary' : 'success'" variant="light">
            {{ AI_KIND_LABEL[row.kind as keyof typeof AI_KIND_LABEL] }}
          </t-tag>
        </template>
        <template #price="{ row }">
          <span class="muted" v-if="row.input_price == null && row.output_price == null">未配置</span>
          <span v-else>{{ row.input_price ?? '—' }} / {{ row.output_price ?? '—' }}</span>
        </template>
        <template #enabled="{ row }">
          <t-tag :theme="row.enabled ? 'success' : 'default'" variant="light">
            {{ row.enabled ? '已启用' : '已停用' }}
          </t-tag>
        </template>
        <template #op="{ row }">
          <t-button variant="text" theme="primary" size="small" @click="openEdit(row)">编辑</t-button>
          <t-button variant="text" theme="danger" size="small" @click="remove(row)">删除</t-button>
        </template>
      </t-table>
    </div>

    <ModelDrawer
      v-model:visible="drawerVisible"
      :model="editingModel"
      :providers="providers"
      @saved="onSaved"
    />

    <!-- 从上游拉取：选厂商 → 取候选 → 勾选 + 定类型 → 批量导入 -->
    <t-dialog
      v-model:visible="pullVisible"
      header="从上游拉取模型"
      :confirm-btn="{ content: `导入选中（${selectedCount}）`, loading: importing, disabled: selectedCount === 0 }"
      :close-on-overlay-click="false"
      width="640px"
      @confirm="doImport"
    >
      <t-alert theme="info" message="从上游 /v1/models 读取候选，勾选后按所选类型批量导入；导入后可单独编辑别名与单价。" style="margin-bottom: 16px" />
      <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 12px">
        <t-select
          v-model="pullProviderId"
          :options="providerOptions"
          placeholder="选择厂商"
          filterable
          style="width: 280px"
        />
        <t-button variant="outline" theme="primary" :loading="pulling" @click="fetchCandidates">
          获取模型列表
        </t-button>
      </div>

      <div v-if="candidates.length" class="candidate-list">
        <label v-for="c in candidates" :key="c.id" class="candidate-row">
          <t-checkbox v-model="selected[c.id]" />
          <span class="candidate-name">{{ c.id }}</span>
          <span class="candidate-owner">by {{ c.owned_by }}</span>
          <t-select v-model="kindOf[c.id]" style="width: 110px; margin-left: auto">
            <t-option value="chat" :label="AI_KIND_LABEL.chat" />
            <t-option value="embedding" :label="AI_KIND_LABEL.embedding" />
          </t-select>
        </label>
      </div>
      <t-empty v-else-if="!pulling" description="选择厂商后点击「获取模型列表」" />
    </t-dialog>
  </div>
</template>

<style scoped>
.candidate-list {
  max-height: 320px;
  overflow: auto;
  border: 1px solid var(--color-divider-weak);
  border-radius: var(--radius-control);
  padding: 4px 8px;
}
.candidate-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 6px;
}
.candidate-row + .candidate-row { border-top: 1px solid var(--color-divider-weak); }
.candidate-name { font: 500 13px/18px var(--font-family); color: var(--color-text-primary); }
.candidate-owner { font: var(--font-caption); color: var(--color-text-muted); }
.muted { font: var(--font-body); color: var(--color-text-muted); }
</style>
