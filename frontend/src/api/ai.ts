// AI 网关管理台 API：五个资源 + 用量查询
// 复用 client.ts 的 axios 实例（baseURL=/admin/v1）、中文错误兜底与 401 处理
import { del, get, patch, post } from './client'
import type {
  AiKey,
  AiKeyCreated,
  AiKeyCreate,
  AiKeyUpdate,
  AiKind,
  AiModel,
  AiModelCreate,
  AiModelImportItem,
  AiModelImportResult,
  AiModelPullCandidate,
  AiModelUpdate,
  AiProvider,
  AiProviderCreate,
  AiProviderUpdate,
  AiUsageDaily,
  AiUsageEventPage,
  AiUsageQuery,
  AiUsageStatus,
  GuardrailBulk,
  GuardrailBulkResult,
  GuardrailRule,
  GuardrailRuleCreate,
  GuardrailRuleUpdate,
} from './ai-types'

// ---------------- 厂商 ----------------
export const listProviders = () => get<AiProvider[]>('/ai/providers')
export const createProvider = (payload: AiProviderCreate) => post<AiProvider>('/ai/providers', payload)
export const updateProvider = (id: number, payload: AiProviderUpdate) =>
  patch<AiProvider>(`/ai/providers/${id}`, payload)
export const deleteProvider = (id: number) => del<void>(`/ai/providers/${id}`)
export const enableProvider = (id: number) => post<AiProvider>(`/ai/providers/${id}/enable`)
export const disableProvider = (id: number) => post<AiProvider>(`/ai/providers/${id}/disable`)
export const checkProviderHealth = (id: number) => post<AiProvider>(`/ai/providers/${id}/health`)

// ---------------- 模型 ----------------
export const listModels = (params?: { provider_id?: number; kind?: AiKind }) =>
  get<AiModel[]>('/ai/models', { params: params ?? {} })
export const createModel = (payload: AiModelCreate) => post<AiModel>('/ai/models', payload)
export const updateModel = (id: number, payload: AiModelUpdate) =>
  patch<AiModel>(`/ai/models/${id}`, payload)
export const deleteModel = (id: number) => del<void>(`/ai/models/${id}`)
// 从上游 /v1/models 拉取候选（返回 [{id, owned_by}]）
export const pullModels = (providerId: number) =>
  get<AiModelPullCandidate[]>('/ai/models/pull', { params: { provider_id: providerId } })
// 批量导入：勾选的候选 + 每条的类型，返回 {created, skipped, models}
export const importModels = (providerId: number, items: AiModelImportItem[]) =>
  post<AiModelImportResult>('/ai/models/import', { provider_id: providerId, items })

// ---------------- AI Key ----------------
export const listKeys = () => get<AiKey[]>('/ai/keys')
export const getKey = (id: number) => get<AiKey>(`/ai/keys/${id}`)
export const createKey = (payload: AiKeyCreate) => post<AiKeyCreated>('/ai/keys', payload)
export const updateKey = (id: number, payload: AiKeyUpdate) => patch<AiKey>(`/ai/keys/${id}`, payload)
export const revokeKey = (id: number) => post<AiKey>(`/ai/keys/${id}/revoke`)

// ---------------- 用量审计 ----------------
export const listUsageEvents = (query: AiUsageQuery) =>
  get<AiUsageEventPage>('/ai/usage/events', { params: query })
export const listUsageDaily = (query: { key_id: number; from: string; to: string }) =>
  get<AiUsageDaily[]>('/ai/usage/daily', { params: query })

// ---------------- 护栏规则 ----------------
export const listGuardrails = () => get<GuardrailRule[]>('/ai/guardrails')
export const createGuardrail = (payload: GuardrailRuleCreate) =>
  post<GuardrailRule>('/ai/guardrails', payload)
export const updateGuardrail = (id: number, payload: GuardrailRuleUpdate) =>
  patch<GuardrailRule>(`/ai/guardrails/${id}`, payload)
export const deleteGuardrail = (id: number) => del<void>(`/ai/guardrails/${id}`)
export const bulkGuardrails = (payload: GuardrailBulk) =>
  post<GuardrailBulkResult>('/ai/guardrails/bulk', payload)

// 用量状态类型再导出，便于页面直接使用
export type { AiUsageStatus }
