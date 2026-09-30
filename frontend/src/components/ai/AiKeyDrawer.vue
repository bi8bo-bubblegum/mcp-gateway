<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { createKey, updateKey } from '@/api/ai'
import type { AiKey, AiModel, AiPeriod } from '@/api/ai-types'
import { AI_KIND_LABEL, AI_PERIOD_LABEL } from '@/utils/labels'

const props = defineProps<{
  visible: boolean
  aiKey: AiKey | null // null = 新建（注意：不能用 `key`，Vue 模板中 key 为保留属性）
  models: AiModel[] // 用于「授权模型」多选
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved'): void
  (e: 'created', plainKey: string): void
}>()

const isEdit = computed(() => props.aiKey != null)
const submitting = ref(false)

const form = reactive({
  name: '',
  owner: '',
  model_ids: [] as number[],
  period: 'none' as AiPeriod,
  period_token_limit: undefined as number | undefined,
  rate_limit_rpm: undefined as number | undefined,
  enabled: true,
})

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    const k = props.aiKey
    form.name = k?.name ?? ''
    form.owner = k?.owner ?? ''
    form.model_ids = [...(k?.model_ids ?? [])]
    form.period = k?.period ?? 'none'
    form.period_token_limit = k?.period_token_limit ?? undefined
    form.rate_limit_rpm = k?.rate_limit_rpm ?? undefined
    form.enabled = k?.enabled ?? true
  },
)

const modelOptions = computed(() =>
  props.models
    .filter((m) => m.enabled)
    .map((m) => ({
      value: m.id,
      label: `${m.alias} · ${AI_KIND_LABEL[m.kind as keyof typeof AI_KIND_LABEL]}`,
    })),
)

async function submit() {
  if (!form.name.trim()) {
    MessagePlugin.warning('请填写名称')
    return
  }
  // 配额仅在选择周期额度时生效：none 时清空上限
  const periodTokenLimit = form.period === 'none' ? null : form.period_token_limit ?? null

  submitting.value = true
  try {
    if (isEdit.value) {
      await updateKey(props.aiKey!.id, {
        name: form.name.trim(),
        enabled: form.enabled,
        period: form.period,
        period_token_limit: periodTokenLimit,
        rate_limit_rpm: form.rate_limit_rpm ?? null,
        model_ids: form.model_ids,
      })
      MessagePlugin.success('密钥已更新')
      emit('saved')
      emit('update:visible', false)
    } else {
      const created = await createKey({
        name: form.name.trim(),
        owner: form.owner.trim() || null,
        period: form.period,
        period_token_limit: periodTokenLimit,
        rate_limit_rpm: form.rate_limit_rpm ?? null,
        model_ids: form.model_ids,
      })
      MessagePlugin.success('密钥已创建')
      emit('created', created.key)
      emit('saved')
      emit('update:visible', false)
    }
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
    :header="isEdit ? '编辑密钥' : '新建密钥'"
    :footer="true"
    :confirm-btn="{ content: isEdit ? '保存' : '创建', loading: submitting }"
    size="560px"
    @close="emit('update:visible', false)"
    @confirm="submit"
  >
    <t-form label-align="top">
      <t-form-item label="名称">
        <t-input
          v-model="form.name"
          placeholder="ci-bot"
          tips="密钥显示名称，便于识别调用方，如 ci-bot、data-analyst"
        />
      </t-form-item>
      <t-form-item label="归属（可选）">
        <t-input
          v-model="form.owner"
          placeholder="团队或个人标识"
          tips="owner 仅作归属展示，不参与鉴权"
        />
      </t-form-item>
      <t-form-item label="授权模型（白名单）">
        <!-- Select 的 tips 渲染层级不随抽屉滚动，改用同级提示行 -->
        <t-select
          v-model="form.model_ids"
          :options="modelOptions"
          multiple
          filterable
          :min-collapsed-tag-count="3"
          placeholder="搜索并选择可调用的模型…"
        />
        <div class="select-hint">deny-by-default：只有被勾选的模型才可被该密钥调用；未启用模型不会出现在列表</div>
      </t-form-item>
      <t-form-item label="额度周期">
        <t-select v-model="form.period" style="width: 200px">
          <t-option value="none" :label="AI_PERIOD_LABEL.none" />
          <t-option value="day" :label="AI_PERIOD_LABEL.day" />
          <t-option value="month" :label="AI_PERIOD_LABEL.month" />
        </t-select>
        <div class="select-hint">不限 / 每日 / 每月 token 配额；选择「每日」或「每月」后填写上限</div>
      </t-form-item>
      <t-form-item v-if="form.period !== 'none'" label="周期 token 上限">
        <t-input
          v-model="form.period_token_limit"
          type="number"
          placeholder="如 1000000"
          tips="超过该周期内累计 token 即拒绝（429 insufficient_quota）"
        />
      </t-form-item>
      <t-form-item label="每分钟请求上限（RPM）">
        <t-input
          v-model="form.rate_limit_rpm"
          type="number"
          placeholder="留空表示不限制"
          tips="进程内滑动窗口限流，超限返回 429 rate_limit_exceeded"
        />
      </t-form-item>
      <t-form-item label="启用状态">
        <div style="display: flex; align-items: center; gap: 12px">
          <t-switch v-model="form.enabled" />
          <span class="muted" style="font: var(--font-body)">停用后该密钥立即拒绝调用</span>
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
