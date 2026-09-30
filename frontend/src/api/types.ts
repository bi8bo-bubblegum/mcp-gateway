export type RiskLevel = 'low' | 'medium' | 'high'
export type ServiceHealth = 'unknown' | 'healthy' | 'unhealthy'
export type AuditStatus = 'started' | 'succeeded' | 'failed' | 'denied'

export interface ServiceAuth {
  bearer_token?: string | null
  headers?: Record<string, string>
}

export interface Service {
  id: number
  slug: string
  name: string
  url: string
  enabled: boolean
  health: ServiceHealth
  consecutive_failures: number
  last_error: string | null
  last_checked_at: string | null
  last_refreshed_at: string | null
  created_at: string
  updated_at: string
}

export interface ServiceCreate {
  slug: string
  name: string
  url: string
  auth?: ServiceAuth | null
  enabled: boolean
}

export interface ServiceUpdate {
  name?: string
  url?: string
  auth?: ServiceAuth | null
  enabled?: boolean | null
}

export interface ServiceRefreshResult {
  service_id: number
  discovered: number
  created: number
  updated: number
  removed: number
}

export interface Tool {
  id: number
  service_id: number
  service_slug: string
  upstream_name: string
  effective_name: string
  description: string | null
  input_schema: Record<string, unknown>
  schema_hash: string
  risk: RiskLevel
  enabled: boolean
  available: boolean
  discovered_at: string
  updated_at: string
}

export interface ToolUpdate {
  risk?: RiskLevel
  enabled?: boolean
}

export interface ParameterInjection {
  id?: number
  tool_id: number
  argument: string
  value: unknown
}

export interface TokenItem {
  id: number
  name: string
  token_prefix: string
  enabled: boolean
  allow_high_risk: boolean
  created_at: string
  revoked_at: string | null
  last_used_at: string | null
  visible_service_ids: number[]
  allowed_tool_ids: number[]
  parameter_injections: ParameterInjection[]
}

export interface TokenCreated extends TokenItem {
  token: string
}

export interface InjectionInput {
  tool_id: number
  argument: string
  value: unknown
}

export interface TokenCreate {
  name: string
  allow_high_risk: boolean
  visible_service_ids: number[]
  allowed_tool_ids: number[]
  parameter_injections: InjectionInput[]
}

export interface TokenPolicyUpdate {
  name?: string
  enabled?: boolean
  allow_high_risk?: boolean
  visible_service_ids?: number[]
  allowed_tool_ids?: number[]
  parameter_injections?: InjectionInput[] | null
}

export interface AuditEvent {
  id: number
  request_id: string
  token_id: number | null
  token_name: string | null
  service_slug: string | null
  tool_name: string
  status: AuditStatus
  denial_reason: string | null
  error_type: string | null
  argument_keys: string[]
  requested_argument_hashes: Record<string, string>
  effective_argument_hashes: Record<string, string> | null
  started_at: string
  finished_at: string | null
  duration_ms: number | null
}

export interface AuditEventPage {
  total: number
  limit: number
  offset: number
  items: AuditEvent[]
}

export interface AuditQuery {
  token_id?: number
  service_slug?: string
  tool_name?: string
  status?: AuditStatus
  started_after?: string
  started_before?: string
  limit?: number
  offset?: number
}
