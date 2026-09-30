<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { updateTool } from '@/api'
import type { RiskLevel, Tool } from '@/api/types'

const props = defineProps<{
  visible: boolean
  tool: Tool | null
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved'): void
}>()

const submitting = ref(false)
const form = reactive({
  risk: 'high' as RiskLevel,
  enabled: true,
})

watch(
  () => props.visible,
  (open) => {
    if (!open || !props.tool) return
    form.risk = props.tool.risk
    form.enabled = props.tool.enabled
  },
)

const schemaText = computed(() => {
  if (!props.tool) return ''
  try {
    return JSON.stringify(props.tool.input_schema, null, 2)
  } catch {
    return String(props.tool.input_schema ?? '')
  }
})

async function submit() {
  if (!props.tool) return
  submitting.value = true
  try {
    await updateTool(props.tool.id, { risk: form.risk, enabled: form.enabled })
    MessagePlugin.success('工具已更新')
    emit('saved')
    emit('update:visible', false)
  } catch {
    // 错误提示由拦截器统一弹出
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <t-drawer
    :visible="visible"
    header="编辑工具"
    size="480px"
    :footer="true"
    @close="emit('update:visible', false)"
    @confirm="submit"
  >
    <div class="kv"><span class="label">有效名称（唯一）</span><div class="value strong">{{ tool?.effective_name }}</div></div>
    <div class="kv"><span class="label">上游名称</span><div class="value">{{ tool?.upstream_name }}</div></div>
    <div class="kv"><span class="label">所属服务</span><div class="value">{{ tool?.service_slug }}</div></div>

    <div class="kv" style="margin-top: 16px">
      <span class="label">风险等级</span>
      <!-- 同 TokenDrawer：Select 的 tips 渲染层级不随抽屉滚动，改用同级提示行 -->
      <t-select v-model="form.risk" style="width: 200px">
        <t-option value="low" label="低风险" />
        <t-option value="medium" label="中风险" />
        <t-option value="high" label="高风险" />
      </t-select>
      <div class="select-hint">高风险工具仅 allow_high_risk 的令牌可调用</div>
    </div>

    <div class="kv" style="margin-top: 16px">
      <span class="label">启用状态</span>
      <div style="display: flex; align-items: center; gap: 12px">
        <t-switch v-model="form.enabled" />
        <span class="muted" style="font: var(--font-body)">启用后令牌方可调用此工具</span>
      </div>
    </div>

    <div class="kv" style="margin-top: 16px">
      <span class="label">描述</span>
      <div class="desc">{{ tool?.description ?? '（无描述）' }}</div>
    </div>

    <div class="kv" style="margin-top: 16px">
      <span class="label">输入参数 Schema（input_schema · JSON）</span>
      <pre class="code-box">{{ schemaText }}</pre>
    </div>

    <template #footer>
      <t-button theme="default" variant="outline" @click="emit('update:visible', false)">取消</t-button>
      <t-button theme="primary" :loading="submitting" @click="submit">保存</t-button>
    </template>
  </t-drawer>
</template>

<style scoped>
.kv { margin-bottom: 14px; }
.label { display: block; font: var(--font-body); color: var(--color-text-secondary); margin-bottom: 6px; }
.value { font: 400 14px/20px var(--font-family); color: var(--color-text-primary); }
.value.strong { font-weight: 500; }
.desc {
  font: var(--font-body); color: var(--color-text-secondary);
  background: var(--color-bg-page); border-radius: var(--radius-control); padding: 10px 12px;
}
.code-box {
  font: 400 12px/20px var(--font-family); color: var(--color-text-secondary);
  background: var(--color-bg-page); border-radius: var(--radius-control); padding: 12px;
  white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow: auto;
}
/* Select 的 tips 渲染层级不随抽屉滚动，提示改用同级 hint 行 */
.select-hint { margin-top: 6px; font: var(--font-caption); color: var(--color-text-muted); }
</style>
