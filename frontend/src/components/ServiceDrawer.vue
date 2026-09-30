<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { createService, updateService } from '@/api'
import type { Service } from '@/api/types'

const props = defineProps<{
  visible: boolean
  service: Service | null // null = 新建
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved', service: Service): void
}>()

const isEdit = computed(() => props.service != null)
const submitting = ref(false)

interface HeaderRow {
  key: string
  value: string
}

const form = reactive({
  slug: '',
  name: '',
  url: '',
  bearer: '',
  headers: [] as HeaderRow[],
  enabled: false,
})

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    const s = props.service
    form.slug = s?.slug ?? ''
    form.name = s?.name ?? ''
    form.url = s?.url ?? ''
    form.bearer = ''
    form.headers = []
    form.enabled = s?.enabled ?? false
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
  if (!/^https?:\/\//.test(form.url)) {
    MessagePlugin.warning('URL 必须以 http:// 或 https:// 开头')
    return
  }

  const headers: Record<string, string> = {}
  for (const row of form.headers) {
    if (row.key.trim()) headers[row.key.trim()] = row.value
  }
  const auth =
    form.bearer.trim() || Object.keys(headers).length
      ? { bearer_token: form.bearer.trim() || null, headers }
      : null

  submitting.value = true
  try {
    const saved = isEdit.value
      ? await updateService(props.service!.id, {
          name: form.name.trim(),
          url: form.url.trim(),
          auth,
        })
      : await createService({
          slug: form.slug.trim(),
          name: form.name.trim(),
          url: form.url.trim(),
          auth,
          enabled: form.enabled,
        })
    MessagePlugin.success(isEdit.value ? '服务已更新' : '服务已创建')
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
    :header="isEdit ? '编辑服务' : '新建服务'"
    :footer="true"
    :confirm-btn="{ content: isEdit ? '保存' : '创建', loading: submitting }"
    size="480px"
    @close="emit('update:visible', false)"
    @confirm="submit"
  >
    <div class="section">基础信息</div>
    <t-form label-align="top">
      <t-form-item label="Slug（唯一标识）">
        <t-input
          v-model="form.slug"
          placeholder="github"
          :disabled="isEdit"
          tips="仅小写字母、数字和短横线，2-32 位；创建后不可修改"
        />
      </t-form-item>
      <t-form-item label="名称">
        <t-input
          v-model="form.name"
          placeholder="GitHub MCP Server"
          tips="服务的显示名称，便于在列表中识别"
        />
      </t-form-item>
      <t-form-item label="MCP 地址（上游 URL）">
        <t-input
          v-model="form.url"
          placeholder="https://mcp.example.com/mcp"
          tips="上游 MCP 服务的 Streamable HTTP 端点，以 http:// 或 https:// 开头"
        />
      </t-form-item>
    </t-form>

    <div class="section" style="margin-top: 16px">认证配置</div>
    <t-form label-align="top">
      <t-form-item label="Bearer Token（可选）">
        <t-input
          v-model="form.bearer"
          type="password"
          placeholder="留空则上游服务不携带鉴权"
          tips="上游鉴权凭证，加密存储；编辑时留空表示不修改"
        />
      </t-form-item>
      <t-form-item label="自定义 Headers">
        <div class="header-rows">
          <div v-for="(row, i) in form.headers" :key="i" class="header-row">
            <t-input v-model="row.key" placeholder="X-Api-Key" />
            <t-input v-model="row.value" type="password" placeholder="••••••••" />
            <t-button
              variant="text"
              theme="danger"
              size="small"
              class="row-del"
              @click="form.headers.splice(i, 1)"
            >
              ✕
            </t-button>
          </div>
          <t-button
            variant="dashed"
            theme="primary"
            size="small"
            class="add-header-btn"
            @click="form.headers.push({ key: '', value: '' })"
          >
            + 添加 Header
          </t-button>
          <div class="field-hint">键值对会原样附加到网关发往上游的请求头中</div>
        </div>
      </t-form-item>
    </t-form>

    <div v-if="!isEdit" class="section" style="margin-top: 16px">启用状态</div>
    <div v-if="!isEdit" style="display: flex; align-items: center; gap: 12px; margin-top: 8px">
      <t-switch v-model="form.enabled" />
      <span class="muted" style="font: var(--font-body)">
        创建后健康检查通过才会真正启用；健康检查不通过时保持停用
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
.header-rows { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.header-row {
  display: grid;
  grid-template-columns: 1fr 1.25fr 28px;
  gap: 8px;
  align-items: center;
}
.row-del { padding: 0 4px; }
.field-hint { font: var(--font-caption); color: var(--color-text-muted); }
/* 添加按钮：内容宽度 + 虚线胶囊，不再撑满整行 */
.add-header-btn { align-self: flex-start; }
</style>
