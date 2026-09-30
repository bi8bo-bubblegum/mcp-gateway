/** 时间展示工具：表格里统一 'MM-DD HH:mm'，详情里 'YYYY-MM-DD HH:mm' */

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

export function fmtTime(iso: string | null | undefined): string {
  const d = parse(iso)
  if (!d) return '—'
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fmtDateTime(iso: string | null | undefined): string {
  const d = parse(iso)
  if (!d) return '—'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 今天 0 点的 ISO 串，用于「今日审计」的时间过滤 */
export function todayStartISO(): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

/** 相对时间（几分钟前） */
export function fromNow(iso: string | null | undefined): string {
  const d = parse(iso)
  if (!d) return '—'
  const diff = Date.now() - d.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return fmtDateTime(iso)
}

/** 把用户输入的注入参数值转成 JSON 语义值：能 parse 就 parse（数字/布尔/对象），否则原样字符串 */
export function parseInjectionValue(raw: string): unknown {
  const trimmed = raw.trim()
  if (trimmed === '') return ''
  try {
    return JSON.parse(trimmed)
  } catch {
    return raw
  }
}

/** 毫秒 → 「时 分 秒 毫秒」组合展示，前导零单位自动省略（142 → "142 毫秒"，65250 → "1 分 5 秒 250 毫秒"） */
export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null || ms < 0) return '—'
  const hours = Math.floor(ms / 3_600_000)
  const minutes = Math.floor((ms % 3_600_000) / 60_000)
  const seconds = Math.floor((ms % 60_000) / 1000)
  const millis = ms % 1000
  const parts: string[] = []
  if (hours > 0) parts.push(`${hours} 时`)
  if (minutes > 0) parts.push(`${minutes} 分`)
  if (seconds > 0) parts.push(`${seconds} 秒`)
  if (millis > 0 || parts.length === 0) parts.push(`${millis} 毫秒`)
  return parts.join(' ')
}
