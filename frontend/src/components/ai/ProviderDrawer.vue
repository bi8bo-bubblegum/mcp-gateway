<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { createProvider, updateProvider } from '@/api/ai'
import type { AiProvider } from '@/api/ai-types'

const props = defineProps<{
  visible: boolean
  provider: AiProvider | null // null = 新建
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved', provider: AiProvider): void
}>()

const isEdit = computed(() => props.provider != null)
const submitting = ref(false)

const form = reactive({
  slug: '',
  name: '',
  base_url: '',
  api_key: '',
  enabled: false,
})

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    const p = props.provider
    form.slug = p?.slug ?? ''
    form.name = p?.name ?? ''
    form.base_url = p?.base_url ?? ''
    form.api_key = '' // 密码框始终留空，避免明文回显上游密钥
    form.enabled = p?.enabled ?? false
  },
)

const SLUG_RE = /^[a-z][a-z0-9-]{1,31}$/

async function submit() {
  if (!isEdit.value && !SLUG_RE.test(form.slug)) {
    MessagePlugin.warning('Slug 需以小写字母开头，2-32 位小写字母/数字/短横线')
    return
  }
  if (!form.name.trim()) {
    MessagePlugin.warning('请填写名称')
    return
  }
  if (!/^https?:\/\//.test(form.base_url)) {
    MessagePlugin.warning('Base URL 必须以 http:// 或 https:// 开头')
    return
  }

  // 仅在填写了 api_key 时才提交，编辑时不传表示不修改上游密钥
  const apiKey = form.api_key.trim() || null

  submitting.value = true
  try {
    const saved = isEdit.value
      ? await updateProvider(props.provider!.id, {
          name: form.name.trim(),
          base_url: form.base_url.trim(),
          api_key: apiKey,
        })
      : await createProvider({
          slug: form.slug.trim(),
          name: form.name.trim(),
          base_url: form.base_url.trim(),
          api_key: apiKey,
          enabled: form.enabled,
        })
    MessagePlugin.success(isEdit.value ? '厂商已更新' : '厂商已创建')
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
    :header="isEdit ? '编辑厂商' : '新建厂商'"
    :footer="true"
    :confirm-btn="{ content: isEdit ? '保存' : '创建', loading: submitting }"
    size="480px"
    @close="emit('update:visible', false)"
    @confirm="submit"
  >
    <t-form label-align="top">
      <t-form-item label="Slug（唯一标识）">
        <t-input
          v-model="form.slug"
          placeholder="openai"
          :disabled="isEdit"
          tips="仅小写字母、数字和短横线，2-32 位；创建后不可修改"
        />
      </t-form-item>
      <t-form-item label="名称">
        <t-input
          v-model="form.name"
          placeholder="OpenAI"
          tips="厂商显示名称，便于在列表中识别"
        />
      </t-form-item>
      <t-form-item label="Base URL（OpenAI 兼容根地址）">
        <t-input
          v-model="form.base_url"
          placeholder="https://api.openai.com/v1"
          tips="上游 OpenAI 兼容端点根地址，以 http:// 或 https:// 开头"
        />
      </t-form-item>
      <t-form-item label="上游 API Key（可选）">
        <t-input
          v-model="form.api_key"
          type="password"
          placeholder="留空则不修改（编辑时）"
          tips="上游鉴权密钥，加密存储；创建时必填，编辑时留空表示保持原值"
        />
      </t-form-item>
    </t-form>

    <div v-if="!isEdit" class="section" style="margin-top: 16px">启用状态</div>
    <div v-if="!isEdit" style="display: flex; align-items: center; gap: 12px; margin-top: 8px">
      <t-switch v-model="form.enabled" />
      <span class="muted" style="font: var(--font-body)">
        创建后健康检查通过才会真正启用；不通过时保持停用
      </span>
    </div>

    <template #footer>
      <t-button theme="default" variant="outline" @click="emit('update:visible', false)">
        取消
      </t-button>
      <t-button theme="primary" :loading="submitting" @click="submit">
        {{ isEdit ? '保存' : '创建' }}
      </t-button>
    </template>
  </t-drawer>
</template>

<style scoped>
.section {
  font: 500 13px/18px var(--font-family);
  color: var(--color-text-primary);
}
.muted { font: var(--font-body); color: var(--color-text-muted); }
</style>
