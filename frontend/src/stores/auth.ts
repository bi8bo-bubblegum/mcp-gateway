import { reactive } from 'vue'

const KEY = 'gateway.admin.auth'

export interface AdminAuth {
  username: string
  password: string
}

function load(): AdminAuth | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as AdminAuth) : null
  } catch {
    return null
  }
}

export const auth = reactive<{ data: AdminAuth | null }>({ data: load() })

export function setAuth(username: string, password: string): void {
  auth.data = { username, password }
  localStorage.setItem(KEY, JSON.stringify(auth.data))
}

export function clearAuth(): void {
  auth.data = null
  localStorage.removeItem(KEY)
}

export function basicHeader(): string | null {
  if (!auth.data) return null
  return 'Basic ' + btoa(`${auth.data.username}:${auth.data.password}`)
}

export function isLoggedIn(): boolean {
  return auth.data !== null
}
