import { del, get, patch, post } from './client'
import type {
  AuditEventPage,
  AuditQuery,
  Service,
  ServiceCreate,
  ServiceRefreshResult,
  ServiceUpdate,
  TokenCreate,
  TokenCreated,
  TokenItem,
  TokenPolicyUpdate,
  Tool,
  ToolUpdate,
} from './types'

// ---------------- 上游服务 ----------------
export const listServices = () => get<Service[]>('/services')
export const createService = (payload: ServiceCreate) => post<Service>('/services', payload)
export const updateService = (id: number, payload: ServiceUpdate) =>
  patch<Service>(`/services/${id}`, payload)
export const deleteService = (id: number) => del<void>(`/services/${id}`)
export const enableService = (id: number) => post<Service>(`/services/${id}/enable`)
export const disableService = (id: number) => post<Service>(`/services/${id}/disable`)
export const refreshService = (id: number) =>
  post<ServiceRefreshResult>(`/services/${id}/refresh`)
export const checkServiceHealth = (id: number) => post<Service>(`/services/${id}/health`)

// ---------------- 工具 ----------------
export const listTools = (serviceId?: number) =>
  get<Tool[]>('/tools', { params: serviceId != null ? { service_id: serviceId } : {} })
export const updateTool = (id: number, payload: ToolUpdate) => patch<Tool>(`/tools/${id}`, payload)

// ---------------- 访问凭证 ----------------
export const listTokens = () => get<TokenItem[]>('/tokens')
export const getToken = (id: number) => get<TokenItem>(`/tokens/${id}`)
export const createToken = (payload: TokenCreate) => post<TokenCreated>('/tokens', payload)
export const updateTokenPolicy = (id: number, payload: TokenPolicyUpdate) =>
  patch<TokenItem>(`/tokens/${id}`, payload)
export const revokeToken = (id: number) => post<TokenItem>(`/tokens/${id}/revoke`)

// ---------------- 审计日志 ----------------
export const listAuditEvents = (query: AuditQuery) =>
  get<AuditEventPage>('/audit-events', { params: query })
