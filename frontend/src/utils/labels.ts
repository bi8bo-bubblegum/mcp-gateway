import type { AuditStatus, RiskLevel, ServiceHealth } from '@/api/types'

export const HEALTH_LABEL: Record<ServiceHealth, string> = {
  healthy: '健康',
  unhealthy: '异常',
  unknown: '未知',
}

export const HEALTH_TONE: Record<ServiceHealth, 'success' | 'danger' | 'default'> = {
  healthy: 'success',
  unhealthy: 'danger',
  unknown: 'default',
}

export const RISK_LABEL: Record<RiskLevel, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

export const RISK_TONE: Record<RiskLevel, 'success' | 'warning' | 'danger'> = {
  low: 'success',
  medium: 'warning',
  high: 'danger',
}

export const AUDIT_STATUS_LABEL: Record<AuditStatus, string> = {
  started: '进行中',
  succeeded: '成功',
  failed: '失败',
  denied: '拒绝',
}

export const AUDIT_STATUS_TONE: Record<AuditStatus, 'primary' | 'success' | 'danger' | 'warning'> = {
  started: 'primary',
  succeeded: 'success',
  failed: 'danger',
  denied: 'warning',
}

/** 网关策略拒绝原因码 → 中文展示 */
export const DENIAL_REASON_LABEL: Record<string, string> = {
  service_not_visible: '服务不可见',
  tool_not_allowed: '工具未授权',
  high_risk_not_allowed: '高风险未放行',
  tool_unavailable: '工具不可用',
  injection_invalid: '注入配置无效',
  tool_not_found: '工具不存在',
  denied: '已拒绝',
}

// ---------------- AI 网关枚举映射 ----------------
export const AI_KIND_LABEL: Record<'chat' | 'embedding', string> = {
  chat: '对话',
  embedding: '向量',
}

export const AI_PERIOD_LABEL: Record<'none' | 'day' | 'month', string> = {
  none: '不限',
  day: '每日',
  month: '每月',
}

export const AI_SCOPE_LABEL: Record<'request' | 'response' | 'both', string> = {
  request: '请求',
  response: '响应',
  both: '请求+响应',
}

export const AI_ACTION_LABEL: Record<'block', string> = {
  block: '拦截',
}

export const AI_STATUS_LABEL: Record<'started' | 'succeeded' | 'failed' | 'denied', string> = {
  started: '进行中',
  succeeded: '成功',
  failed: '失败',
  denied: '拒绝',
}

export const AI_STATUS_TONE: Record<
  'started' | 'succeeded' | 'failed' | 'denied',
  'primary' | 'success' | 'danger' | 'warning'
> = {
  started: 'primary',
  succeeded: 'success',
  failed: 'danger',
  denied: 'warning',
}

/** 用量审计拒绝原因码 → 中文（与 MCP DENIAL_REASON_LABEL 互补，AI 侧专用） */
export const AI_DENIAL_LABEL: Record<string, string> = {
  invalid_api_key: '密钥无效',
  model_not_found: '模型不存在',
  permission_denied: '未授权',
  insufficient_quota: '配额不足',
  rate_limit_exceeded: '限流超限',
  guardrail_blocked: '护栏拦截',
  upstream_error: '上游异常',
  cancelled: '已取消',
}
