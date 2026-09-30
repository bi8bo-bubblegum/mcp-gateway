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
