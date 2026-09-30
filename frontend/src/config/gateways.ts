// 网关定义：两套并列控制台（MCP 网关 / AI 网关）的导航与入口
// 顶栏切换器与侧栏菜单都从这里读取，避免把路由结构写死在组件里

export type GatewayKind = 'mcp' | 'ai'

export interface GatewayMenu {
  path: string
  label: string
  name: string // 路由 name，用于高亮判断
}

export interface GatewayDef {
  kind: GatewayKind
  label: string // 切换器与顶栏显示名
  desc: string // 切换器下拉项副标题
  entry: string // 选中后落地页
  menus: GatewayMenu[]
}

// MCP 网关：上游服务 / 工具授权 / 令牌审计
const MCP_MENUS: GatewayMenu[] = [
  { path: '/mcp', label: '概览', name: 'mcp-overview' },
  { path: '/mcp/services', label: '上游服务', name: 'mcp-services' },
  { path: '/mcp/tools', label: '工具管理', name: 'mcp-tools' },
  { path: '/mcp/tokens', label: '访问凭证', name: 'mcp-tokens' },
  { path: '/mcp/audit', label: '审计日志', name: 'mcp-audit' },
]

// AI 网关：多厂商模型 / 密钥分发 / token 计量
const AI_MENUS: GatewayMenu[] = [
  { path: '/ai', label: '概览', name: 'ai-overview' },
  { path: '/ai/providers', label: '厂商管理', name: 'ai-providers' },
  { path: '/ai/models', label: '模型管理', name: 'ai-models' },
  { path: '/ai/keys', label: 'AI Key', name: 'ai-keys' },
  { path: '/ai/usage', label: '用量审计', name: 'ai-usage' },
  { path: '/ai/guardrails', label: '护栏规则', name: 'ai-guardrails' },
]

export const GATEWAYS: GatewayDef[] = [
  {
    kind: 'mcp',
    label: 'MCP 网关',
    desc: '上游服务 / 工具授权 / 令牌审计',
    entry: '/mcp',
    menus: MCP_MENUS,
  },
  {
    kind: 'ai',
    label: 'AI 网关',
    desc: '多厂商模型 / 密钥分发 / token 计量',
    entry: '/ai',
    menus: AI_MENUS,
  },
]

export function getGateway(kind: GatewayKind): GatewayDef {
  return GATEWAYS.find((g) => g.kind === kind) ?? GATEWAYS[0]
}

/** 根据当前路径判断属于哪个网关（用于侧栏菜单与高亮） */
export function gatewayOfPath(path: string): GatewayDef {
  return path.startsWith('/ai') ? getGateway('ai') : getGateway('mcp')
}

export const GATEWAY_STORAGE_KEY = 'gateway.kind'
