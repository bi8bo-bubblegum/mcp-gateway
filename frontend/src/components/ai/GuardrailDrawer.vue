<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { createGuardrail, updateGuardrail } from '@/api/ai'
import type { AiAction, AiScope, GuardrailRule } from '@/api/ai-types'
import { AI_ACTION_LABEL, AI_SCOPE_LABEL } from '@/utils/labels'

const props = defineProps<{
  visible: boolean
  rule: GuardrailRule | null // null = 新建
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved', rule: GuardrailRule): void
}>()

const isEdit = computed(() => props.rule != null)
const submitting = ref(false)

const form = reactive({
  name: '',
  pattern: '',
  scope: 'both' as AiScope,
  action: 'block' as AiAction,
  enabled: true,
})

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    const r = props.rule
    form.name = r?.name ?? ''
    form.pattern = r?.pattern ?? ''
    form.scope = r?.scope ?? 'both'
    form.action = r?.action ?? 'block'
    form.enabled = r?.enabled ?? true
  },
)

async function submit() {
  if (!form.name.trim()) {
    MessagePlugin.warning('请填写规则名')
    return
  }
  if (!form.pattern.trim()) {
    MessagePlugin.warning('请填写关键词（pattern）')
    return
  }

  submitting.value = true
  try {
    const saved = isEdit.value
      ? await updateGuardrail(props.rule!.id, {
          name: form.name.trim(),
          pattern: form.pattern.trim(),
          scope: form.scope,
          action: form.action,
          enabled: form.enabled,
        })
      : await createGuardrail({
          name: form.name.trim(),
          pattern: form.pattern.trim(),
          scope: form.scope,
          action: form.action,
          enabled: form.enabled,
        })
    MessagePlugin.success(isEdit.value ? '规则已更新' : '规则已创建')
    emit('saved', saved)
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
    :header="isEdit ? '编辑规则' : '新建规则'"
    :footer="true"
    :confirm-btn="{ content: isEdit ? '保存' : '创建', loading: submitting }"
    size="480px"
    @close="emit('update:visible', false)"
    @confirm="submit"
  >
    <t-form label-align="top">
      <t-form-item label="规则名">
        <t-input
          v-model="form.name"
          placeholder="屏蔽敏感词-政治"
          tips="规则显示名，便于在列表中识别"
        />
      </t-form-item>
      <t-form-item label="关键词（pattern）">
        <t-input
          v-model="form.pattern"
          placeholder="敏感词"
          tips="子串匹配，大小写不敏感；命中即触发动作"
        />
      </t-form-item>
      <t-form-item label="作用域">
        <!-- Select 的 tips 渲染层级不随抽屉滚动，改用同级提示行 -->
        <t-select v-model="form.scope" style="width: 220px">
          <t-option value="request" :label="AI_SCOPE_LABEL.request" />
          <t-option value="response" :label="AI_SCOPE_LABEL.response" />
          <t-option value="both" :label="AI_SCOPE_LABEL.both" />
        </t-select>
        <div class="select-hint">request=请求侧拦截；response=响应侧（流式不中断）；both=两侧都检查</div>
      </t-form-item>
      <t-form-item label="动作">
        <t-select v-model="form.action" style="width: 200px">
          <t-option value="block" :label="AI_ACTION_LABEL.block" />
        </t-select>
        <div class="select-hint">首版仅支持「拦截」（block）</div>
      </t-form-item>
      <t-form-item label="启用状态">
        <div style="display: flex; align-items: center; gap: 12px">
          <t-switch v-model="form.enabled" />
          <span class="muted" style="font: var(--font-body)">停用后该规则不生效</span>
        </div>
      </t-form-item>
    </t-form>

    <template #footer>
      <t-button theme="default" variant="outline" @click="emit('update:visible', false)">取消</t-button>
      <t-button theme="primary" :loading="submitting" @click="submit">
        {{ isEdit ? '保存' : '创建' }}
      </t-button>
    </template>
  </t-drawer>
</template>

<style scoped>
.select-hint { margin-top: 6px; font: var(--font-caption); color: var(--color-text-muted); }
.muted { font: var(--font-body); color: var(--color-text-muted); }
</style>
