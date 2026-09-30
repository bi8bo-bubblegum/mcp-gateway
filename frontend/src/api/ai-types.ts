// AI 网关管理台类型定义，与后端 app/schemas/ai.py 对齐
// 枚举值后端返回英文串，前端在 labels.ts 中映射成中文

export type AiKind = 'chat' | 'embedding'
export type AiPeriod = 'none' | 'day' | 'month'
export type AiScope = 'request' | 'response' | 'both'
export type AiAction = 'block'
export type AiHealth = 'unknown' | 'healthy' | 'unhealthy'
export type AiUsageStatus = 'started' | 'succeeded' | 'failed' | 'denied'

// ---------------- 厂商（上游） ----------------
export interface AiProvider {
  id: number
  slug: string
  name: string
  base_url: string
  enabled: boolean
  health: AiHealth
  consecutive_failures: number
  last_error: string | null
  last_checked_at: string | null
  created_at: string
  updated_at: string
}

export interface AiProviderCreate {
  slug: string
  name: string
  base_url: string
  api_key?: string | null // 上游密钥，加密存储；留空不修改（编辑时）
  enabled: boolean
}

export interface AiProviderUpdate {
  name?: string
  base_url?: string
  api_key?: string | null
  enabled?: boolean | null
}

// ---------------- 模型（映射层） ----------------
export interface AiModel {
  id: number
  provider_id: number
  provider_model_name: string
  alias: string
  kind: AiKind
  enabled: boolean
  input_price: number | null
  output_price: number | null
  created_at: string
  updated_at: string
}

export interface AiModelCreate {
  provider_id: number
  provider_model_name: string
  alias: string
  kind: AiKind
  input_price?: number | null
  output_price?: number | null
  enabled?: boolean
}

export interface AiModelUpdate {
  provider_model_name?: string
  alias?: string
  kind?: AiKind
  enabled?: boolean | null
  input_price?: number | null
  output_price?: number | null
}

// 上游 /v1/models 返回的候选（仅外部名 + 归属，尚未入库）
export interface AiModelPullCandidate {
  id: string
  owned_by: string
}

// 批量导入的单条：上游真实名 + 对外别名（可选，缺省用上游名）+ 类型
export interface AiModelImportItem {
  provider_model_name: string
  alias?: string
  kind: AiKind
}

export interface AiModelImportResult {
  created: number
  skipped: number
  models: AiModel[]
}

// ---------------- AI Key（对外分发） ----------------
export interface AiKey {
  id: number
  name: string
  key_prefix: string
  owner: string | null
  enabled: boolean
  revoked_at: string | null
  period_token_limit: number | null
  period: AiPeriod
  rate_limit_rpm: number | null
  created_at: string
  last_used_at: string | null
  // 详情接口（GET /{id}）才会带 model_ids，列表接口不一定返回
  model_ids?: number[]
}

export interface AiKeyCreate {
  name: string
  owner?: string | null
  period: AiPeriod
  period_token_limit?: number | null
  rate_limit_rpm?: number | null
  model_ids?: number[]
}

export interface AiKeyUpdate {
  name?: string
  enabled?: boolean | null
  period?: AiPeriod
  period_token_limit?: number | null
  rate_limit_rpm?: number | null
  model_ids?: number[] // 提供即整体替换白名单
}

// 创建响应多出 key 明文（仅此一次）
export interface AiKeyCreated extends AiKey {
  key: string
}

// ---------------- 用量审计 ----------------
export interface AiUsageEvent {
  id: number
  key_id: number | null
  key_name: string | null
  model_id: number | null
  model_alias: string | null
  provider_slug: string | null
  endpoint: string | null
  stream: boolean
  status: AiUsageStatus
  denial_reason: string | null
  error_type: string | null
  upstream_status_code: number | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  usage_estimated: boolean
  guardrail_hits: { rule_id: number; rule_name: string }[] | null
  latency_ms: number | null
  first_token_ms: number | null
  started_at: string
  finished_at: string | null
}

export interface AiUsageEventPage {
  total: number
  limit: number
  offset: number
  items: AiUsageEvent[]
}

export interface AiUsageQuery {
  key_id?: number
  model_id?: number
  status?: AiUsageStatus
  started_after?: string
  started_before?: string
  limit?: number
  offset?: number
}

// 日汇总（仅用于留接口，本批概览用事件聚合）
export interface AiUsageDaily {
  key_id: number
  day: string
  requests: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

// ---------------- 护栏规则 ----------------
export interface GuardrailRule {
  id: number
  name: string
  pattern: string
  scope: AiScope
  action: AiAction
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface GuardrailRuleCreate {
  name: string
  pattern: string
  scope: AiScope
  action: AiAction
  enabled?: boolean
}

export interface GuardrailRuleUpdate {
  name?: string
  pattern?: string
  scope?: AiScope
  action?: AiAction
  enabled?: boolean | null
}

export interface GuardrailBulk {
  text: string
  scope: AiScope
  action: AiAction
  name_prefix?: string
  enabled?: boolean
}

export interface GuardrailBulkResult {
  created: number
  skipped: number
  rules: GuardrailRule[]
}
