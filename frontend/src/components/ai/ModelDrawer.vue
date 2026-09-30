<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { createModel, updateModel } from '@/api/ai'
import type { AiKind, AiModel, AiProvider } from '@/api/ai-types'
import { AI_KIND_LABEL } from '@/utils/labels'

const props = defineProps<{
  visible: boolean
  model: AiModel | null // null = 新建
  providers: AiProvider[] // 用于「所属厂商」下拉
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved', model: AiModel): void
}>()

const isEdit = computed(() => props.model != null)
const submitting = ref(false)

const form = reactive({
  provider_id: undefined as number | undefined,
  provider_model_name: '',
  alias: '',
  kind: 'chat' as AiKind,
  input_price: undefined as number | undefined,
  output_price: undefined as number | undefined,
  enabled: true,
})

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    const m = props.model
    form.provider_id = m?.provider_id ?? props.providers[0]?.id
    form.provider_model_name = m?.provider_model_name ?? ''
    form.alias = m?.alias ?? ''
    form.kind = m?.kind ?? 'chat'
    form.input_price = m?.input_price ?? undefined
    form.output_price = m?.output_price ?? undefined
    form.enabled = m?.enabled ?? true
  },
)

const providerOptions = computed(() =>
  props.providers.map((p) => ({ value: p.id, label: `${p.name} · ${p.slug}` })),
)

async function submit() {
  if (form.provider_id == null) {
    MessagePlugin.warning('请选择所属厂商')
    return
  }
  if (!form.provider_model_name.trim()) {
    MessagePlugin.warning('请填写上游模型名')
    return
  }
  if (!form.alias.trim()) {
    MessagePlugin.warning('请填写对外暴露名（alias）')
    return
  }

  submitting.value = true
  try {
    // 单价传 null（非 0）表示未配置；编辑时未改动也照原值提交
    const payload = {
      provider_id: form.provider_id,
      provider_model_name: form.provider_model_name.trim(),
      alias: form.alias.trim(),
      kind: form.kind,
      input_price: form.input_price ?? null,
      output_price: form.output_price ?? null,
      enabled: form.enabled,
    }
    const saved = isEdit.value
      ? await updateModel(props.model!.id, payload)
      : await createModel(payload)
    MessagePlugin.success(isEdit.value ? '模型已更新' : '模型已创建')
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
    :header="isEdit ? '编辑模型' : '新建模型'"
    :footer="true"
    :confirm-btn="{ content: isEdit ? '保存' : '创建', loading: submitting }"
    size="480px"
    @close="emit('update:visible', false)"
    @confirm="submit"
  >
    <t-form label-align="top">
      <t-form-item label="所属厂商">
        <!-- Select 的 tips 渲染层级不随抽屉滚动，改用同级提示行 -->
        <t-select
          v-model="form.provider_id"
          :options="providerOptions"
          :disabled="isEdit"
          placeholder="选择上游厂商"
        />
        <div class="select-hint">模型归属的上游厂商，创建后不可修改</div>
      </t-form-item>
      <t-form-item label="上游模型名（provider_model_name）">
        <t-input
          v-model="form.provider_model_name"
          placeholder="gpt-4o-mini"
          tips="上游真实模型名，网关转发时会把 alias 替换成它"
        />
      </t-form-item>
      <t-form-item label="对外暴露名（alias）">
        <t-input
          v-model="form.alias"
          placeholder="gpt-4o-mini"
          tips="客户端调用时填在 model 字段里的名字，全网唯一"
        />
      </t-form-item>
      <t-form-item label="类型">
        <t-select v-model="form.kind" style="width: 200px">
          <t-option value="chat" :label="AI_KIND_LABEL.chat" />
          <t-option value="embedding" :label="AI_KIND_LABEL.embedding" />
        </t-select>
        <div class="select-hint">chat 走 /chat/completions，embedding 走 /embeddings</div>
      </t-form-item>
      <t-form-item label="输入单价（每千 token）">
        <t-input
          v-model="form.input_price"
          type="number"
          placeholder="留空表示不配置"
          tips="仅用于成本展示统计，不参与计费"
        />
      </t-form-item>
      <t-form-item label="输出单价（每千 token）">
        <t-input
          v-model="form.output_price"
          type="number"
          placeholder="留空表示不配置"
          tips="仅用于成本展示统计，不参与计费"
        />
      </t-form-item>
      <t-form-item label="启用状态">
        <div style="display: flex; align-items: center; gap: 12px">
          <t-switch v-model="form.enabled" />
          <span class="muted" style="font: var(--font-body)">停用后该模型不被解析、不可调用</span>
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
