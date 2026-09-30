<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { createToken, updateTokenPolicy } from '@/api'
import type { InjectionInput, Service, TokenItem, Tool } from '@/api/types'
import { RISK_LABEL } from '@/utils/labels'
import { parseInjectionValue } from '@/utils/format'

const props = defineProps<{
  visible: boolean
  mode: 'create' | 'policy'
  token: TokenItem | null
  services: Service[]
  tools: Tool[]
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved'): void
  (e: 'created', token: string): void
}>()

const submitting = ref(false)

interface InjectionRow {
  tool_id: number | null
  argument: string
  value: string
}

const form = reactive({
  name: '',
  allowHighRisk: false,
  visibleIds: [] as number[],
  allowedIds: [] as number[],
  injections: [] as InjectionRow[],
})

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    if (props.mode === 'policy' && props.token) {
      form.name = props.token.name
      form.allowHighRisk = props.token.allow_high_risk
      form.visibleIds = [...props.token.visible_service_ids]
      form.allowedIds = [...props.token.allowed_tool_ids]
      form.injections = props.token.parameter_injections.map((inj) => ({
        tool_id: inj.tool_id,
        argument: inj.argument,
        value: typeof inj.value === 'string' ? inj.value : JSON.stringify(inj.value),
      }))
    } else {
      form.name = ''
      form.allowHighRisk = false
      form.visibleIds = []
      form.allowedIds = []
      form.injections = []
    }
  },
)

const serviceOptions = computed(() =>
  props.services.map((s) => ({ value: s.id, label: `${s.name} · ${s.slug}` })),
)

/** 已选可见服务对应的工具，按服务分组展示 */
const toolGroups = computed(() =>
  props.services
    .filter((s) => form.visibleIds.includes(s.id))
    .map((s) => ({
      serviceId: s.id,
      label: `${s.name} · ${s.slug}`,
      tools: props.tools.filter((t) => t.service_id === s.id),
    }))
    .filter((g) => g.tools.length > 0),
)

// 可见服务变化后，把不再可见的工具从 L2 与 L3 里清掉，避免提交前才发现非法
watch(
  () => form.visibleIds,
  () => {
    const visibleToolIds = new Set(props.tools.filter((t) => form.visibleIds.includes(t.service_id)).map((t) => t.id))
    form.allowedIds = form.allowedIds.filter((id) => visibleToolIds.has(id))
    form.injections = form.injections.filter(
      (row) => row.tool_id != null && visibleToolIds.has(row.tool_id),
    )
  },
  { deep: true },
)

/** L3 注入目标只能是「已允许」的工具：后端强约束 injection 必须指向 allowed tool */
const injectableToolOptions = computed(() =>
  props.tools
    .filter((t) => form.allowedIds.includes(t.id))
    .map((t) => ({ value: t.id, label: t.effective_name })),
)

const toolsById = computed(() => {
  const map = new Map<number, Tool>()
  for (const t of props.tools) map.set(t.id, t)
  return map
})

/** 从工具 input_schema 收集可选参数路径：顶层属性 + 一层嵌套（如 request.phones） */
function argumentOptions(toolId: number | null): { value: string; label: string }[] {
  if (toolId == null) return []
  const schema = toolsById.value.get(toolId)?.input_schema ?? {}
  return collectPaths(schema, 0).map((p) => ({ value: p, label: p }))
}

function collectPaths(schema: Record<string, unknown>, depth: number): string[] {
  const props = (schema?.['properties'] ?? {}) as Record<string, Record<string, unknown>>
  const paths: string[] = []
  for (const [name, def] of Object.entries(props)) {
    paths.push(name)
    if (depth < 1 && def && def['type'] === 'object' && def['properties']) {
      for (const sub of collectPaths(def, depth + 1)) paths.push(`${name}.${sub}`)
    }
  }
  return paths
}

function toggleTool(toolId: number) {
  const index = form.allowedIds.indexOf(toolId)
  if (index >= 0) form.allowedIds.splice(index, 1)
  else {
    form.allowedIds.push(toolId)
    // 保持与后端一致：allowed_tool_ids 升序存储
    form.allowedIds.sort((a, b) => a - b)
  }
}

function isGroupAllSelected(group: { tools: Tool[] }): boolean {
  return group.tools.every((t) => form.allowedIds.includes(t.id))
}

function toggleGroup(group: { tools: Tool[] }) {
  const groupIds = group.tools.map((t) => t.id)
  if (isGroupAllSelected(group)) {
    form.allowedIds = form.allowedIds.filter((id) => !groupIds.includes(id))
  } else {
    const merged = new Set([...form.allowedIds, ...groupIds])
    form.allowedIds = [...merged].sort((a, b) => a - b)
  }
}

function addInjection() {
  form.injections.push({ tool_id: null, argument: '', value: '' })
}

async function submit() {
  if (!form.name.trim()) {
    MessagePlugin.warning('请填写凭证名称')
    return
  }
  // 高风险工具需要显式开启 allow_high_risk（后端会拒绝保存），提交前先用中文提示
  const highRiskPicked = form.allowedIds.filter((id) => {
    const tool = props.tools.find((t) => t.id === id)
    return tool?.risk === 'high'
  })
  if (highRiskPicked.length > 0 && !form.allowHighRisk) {
    MessagePlugin.warning(
      `已选择 ${highRiskPicked.length} 个高风险工具，请先打开「允许调用高风险工具」开关`,
    )
    return
  }
  const injections: InjectionInput[] = []
  for (const row of form.injections) {
    if (row.tool_id == null || !row.argument.trim()) {
      MessagePlugin.warning('强制参数行需要选择工具并填写参数名')
      return
    }
    injections.push({
      tool_id: row.tool_id,
      argument: row.argument.trim(),
      value: parseInjectionValue(row.value),
    })
  }

  submitting.value = true
  try {
    if (props.mode === 'create') {
      const created = await createToken({
        name: form.name.trim(),
        allow_high_risk: form.allowHighRisk,
        visible_service_ids: form.visibleIds,
        allowed_tool_ids: form.allowedIds,
        parameter_injections: injections,
      })
      MessagePlugin.success('凭证已创建')
      emit('created', created.token)
    } else if (props.token) {
      await updateTokenPolicy(props.token.id, {
        name: form.name.trim(),
        allow_high_risk: form.allowHighRisk,
        visible_service_ids: form.visibleIds,
        allowed_tool_ids: form.allowedIds,
        parameter_injections: injections,
      })
      MessagePlugin.success('策略已更新')
    }
    emit('saved')
    emit('update:visible', false)
  } catch {
    // 校验失败的原因（如注入路径重叠）由拦截器弹出后端 detail
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <t-drawer
    :visible="visible"
    :header="mode === 'create' ? '新建凭证' : '编辑策略'"
    size="720px"
    :footer="true"
    @close="emit('update:visible', false)"
    @confirm="submit"
  >
    <t-form label-align="top">
      <t-form-item label="名称">
        <t-input
          v-model="form.name"
          placeholder="ci-bot"
          tips="凭证的显示名称，便于识别调用方，如 ci-bot、data-analyst"
        />
      </t-form-item>
      <t-form-item label="允许调用高风险工具（risk=high）">
        <div class="switch-row">
          <t-switch v-model="form.allowHighRisk" />
          <span class="switch-hint">默认关闭；开启后该令牌可越过工具风险拦截</span>
        </div>
      </t-form-item>
    </t-form>

    <!-- ① 可见服务：可搜索多选下拉，服务多也不占版面 -->
    <section class="level">
      <div class="level-head">
        <span class="level-badge">1</span>
        <div>
          <div class="level-title">可见服务 <span class="level-tag">Level 1</span></div>
          <div class="level-desc">决定令牌能看到哪些上游服务</div>
        </div>
      </div>
      <!-- 不用 t-select 的 tips 属性：其渲染层级不随抽屉滚动，改用同级提示行 -->
      <t-select
        v-model="form.visibleIds"
        multiple
        filterable
        clearable
        placeholder="搜索并选择可见服务…"
        :options="serviceOptions"
        :min-collapsed-tag-count="4"
      />
      <div class="select-hint">支持关键词搜索、可多选；取消某服务会同步清空其下的工具授权</div>
    </section>

    <!-- ② 允许工具：按服务分组的选择区 -->
    <section class="level">
      <div class="level-head">
        <span class="level-badge">2</span>
        <div>
          <div class="level-title">允许工具 <span class="level-tag">Level 2</span></div>
          <div class="level-desc">按服务分组勾选可调用的工具，点击胶囊切换</div>
        </div>
      </div>
      <div class="tool-panel">
        <div v-if="!toolGroups.length" class="panel-empty">请先在上方选择可见服务</div>
        <div
          v-for="(g, gi) in toolGroups"
          :key="g.serviceId"
          class="tool-group"
          :class="{ divided: gi > 0 }"
        >
          <div class="tool-group-head">
            <span class="tool-group-name">{{ g.label }}</span>
            <span class="tool-group-count">{{ g.tools.length }} 个工具</span>
            <t-button
              variant="text"
              theme="primary"
              size="small"
              class="group-toggle"
              @click="toggleGroup(g)"
            >
              {{ isGroupAllSelected(g) ? '清空本组' : '全选本组' }}
            </t-button>
          </div>
          <div class="tool-chips">
            <button
              v-for="t in g.tools"
              :key="t.id"
              type="button"
              class="tool-chip"
              :class="{ selected: form.allowedIds.includes(t.id), 'chip-high': t.risk === 'high' }"
              :title="`${t.effective_name} · ${RISK_LABEL[t.risk]}风险${t.risk === 'high' ? '（需开启 allow_high_risk）' : ''}`"
              @click="toggleTool(t.id)"
            >
              <svg v-if="form.allowedIds.includes(t.id)" class="chip-check" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M2 6.2 4.8 9 10 3.4" />
              </svg>
              <span class="risk-dot" :class="`risk-${t.risk}`" />
              {{ t.effective_name }}
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- ③ 强制参数 -->
    <section class="level">
      <div class="level-head">
        <span class="level-badge">3</span>
        <div>
          <div class="level-title">强制参数 <span class="level-tag">Level 3</span></div>
          <div class="level-desc">网关转发前注入的固定参数（ParameterInjection），目标工具须已在 Level 2 允许</div>
        </div>
      </div>
      <div class="injection-panel">
        <template v-if="form.injections.length">
          <div class="injection-head">
            <span>工具</span><span>参数名</span><span>参数值</span><span />
          </div>
          <div v-for="(row, i) in form.injections" :key="i" class="injection-row">
            <t-select
              v-model="row.tool_id"
              :options="injectableToolOptions"
              filterable
              clearable
              placeholder="选择已允许的工具"
              @change="row.argument = ''"
            />
            <t-select
              v-model="row.argument"
              :options="argumentOptions(row.tool_id)"
              filterable
              creatable
              clearable
              :disabled="row.tool_id == null"
              placeholder="选择参数名，或输入点号路径"
            />
            <t-input v-model="row.value" placeholder='参数值' />
            <t-button
              variant="text"
              theme="danger"
              size="small"
              class="row-del"
              @click="form.injections.splice(i, 1)"
            >
              ✕
            </t-button>
          </div>
        </template>
        <div v-else class="panel-empty">
          不注入时原样转发调用方参数；添加后注入值始终优先
        </div>
        <div v-if="form.injections.length" class="panel-note">
          参数值按 JSON 语义解析：数字填 5、字符串填 "dev"、对象/数组用 JSON 语法；注入值始终优先于调用方参数。
        </div>
        <t-button variant="dashed" theme="primary" size="small" @click="addInjection">
          + 添加一行
        </t-button>
      </div>
    </section>

    <template #footer>
      <t-button theme="default" variant="outline" @click="emit('update:visible', false)">取消</t-button>
      <t-button theme="primary" :loading="submitting" @click="submit">
        {{ mode === 'create' ? '创建' : '保存' }}
      </t-button>
    </template>
  </t-drawer>
</template>

<style scoped>
.switch-row { display: flex; align-items: center; gap: 12px; }
.switch-hint { font: var(--font-body); color: var(--color-text-muted); }

/* ---------- 分层区块 ---------- */
.level { margin-top: 22px; }
.level-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.level-badge {
  flex: none;
  width: 22px; height: 22px; border-radius: 50%;
  background: var(--grad-primary); color: #fff;
  font-size: 12px; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 6px -2px rgba(0, 82, 217, .5);
}
.level-title { font: 500 13px/18px var(--font-family); color: var(--color-text-primary); }
.level-tag {
  margin-left: 4px; padding: 1px 8px;
  font: 500 11px/14px var(--font-family);
  color: var(--color-primary);
  background: var(--color-primary-light);
  border-radius: var(--radius-pill);
  vertical-align: 1px;
}
.level-desc { margin-top: 2px; font: var(--font-caption); color: var(--color-text-muted); }
.select-hint { margin-top: 6px; font: var(--font-caption); color: var(--color-text-muted); }

/* ---------- 工具分组面板（L2） ---------- */
.tool-panel {
  background: var(--color-bg-group);
  border: 1px solid var(--color-divider-weak);
  border-radius: 12px;
  padding: 4px 14px;
}
.panel-empty {
  padding: 18px 12px;
  font: var(--font-body);
  color: var(--color-text-muted);
  text-align: center;
}
.tool-group { padding: 12px 0; }
.tool-group.divided { border-top: 1px solid var(--color-divider-weak); }
.tool-group-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.tool-group-name { font: 500 13px/18px var(--font-family); color: var(--color-text-primary); }
.tool-group-count { font: var(--font-caption); color: var(--color-text-muted); }
.group-toggle { margin-left: auto; }
.tool-chips { display: flex; flex-wrap: wrap; gap: 8px; }

/* 工具胶囊：紧凑切换 */
.tool-chip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 5px 12px;
  font: 400 12px/16px var(--font-family);
  color: var(--color-text-secondary);
  background: var(--color-bg-card);
  border: 1px solid var(--color-divider-strong);
  border-radius: var(--radius-pill);
  cursor: pointer; user-select: none;
  transition: border-color .15s ease, background-color .15s ease, color .15s ease, box-shadow .15s ease;
}
.tool-chip:hover { border-color: rgba(0, 82, 217, .45); color: var(--color-text-primary); }
.tool-chip.selected {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: 500;
  box-shadow: 0 2px 6px -2px rgba(0, 82, 217, .25);
}
.chip-check { width: 11px; height: 11px; }
/* 风险标识：低=绿点 中=橙点 高=红点；未选中的高风险胶囊描边带红，选中前就能看到跨线警告 */
.risk-dot { flex: none; width: 6px; height: 6px; border-radius: 50%; }
.risk-low { background: var(--color-success); }
.risk-medium { background: var(--color-warning); }
.risk-high { background: var(--color-danger); box-shadow: 0 0 0 2px rgba(213, 73, 65, .18); }
.tool-chip.chip-high:not(.selected) { border-color: rgba(213, 73, 65, .4); }
.tool-chip.chip-high:not(.selected):hover { border-color: var(--color-danger); }

/* ---------- 注入参数表（L3） ---------- */
.injection-panel {
  background: var(--color-bg-group);
  border: 1px solid var(--color-divider-weak);
  border-radius: 12px;
  padding: 12px;
}
.injection-head,
.injection-row {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1.4fr 28px;
  gap: 10px;
  align-items: center;
}
.injection-head {
  font: var(--font-caption);
  color: var(--color-text-muted);
  margin-bottom: 8px;
}
.injection-row { margin-bottom: 8px; }
.injection-row .t-input,
.injection-row .t-select-input { background-color: var(--color-bg-card); }
.row-del { padding: 0 4px; }
.injection-panel .t-button { margin-top: 4px; }
.panel-note {
  margin: 8px 0 2px;
  font: var(--font-caption);
  color: var(--color-text-muted);
  line-height: 1.6;
}
</style>
