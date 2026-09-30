import axios from 'axios'
import { MessagePlugin } from 'tdesign-vue-next'
import { basicHeader, clearAuth } from '@/stores/auth'
import router from '@/router'

/**
 * admin API 客户端。
 * - HTTP Basic 认证：凭证由登录页写入 localStorage，这里统一附加请求头
 * - 401 时清凭证并跳登录页；其余错误统一 toast 后端 detail
 * - 响应拦截器直接返回 data，调用方拿到的就是业务对象
 */
export const http = axios.create({
  baseURL: '/admin/v1',
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const header = basicHeader()
  if (header) config.headers.Authorization = header
  return config
})

http.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    let text =
      typeof detail === 'string'
        ? detail
        : detail
          ? JSON.stringify(detail)
          : ''
    if (status === 401) {
      clearAuth()
      if (router.currentRoute.value.path !== '/login') router.push('/login')
      text = '登录已失效，请重新登录'
    } else if (!text) {
      // axios / 网络层错误是英文，统一转成中文提示
      text = status ? `请求失败（HTTP ${status}）` : '网络异常，请检查后端服务是否已启动'
    }
    MessagePlugin.error(text)
    return Promise.reject(error)
  },
)

export const get = <T>(url: string, config?: object): Promise<T> =>
  http.get(url, config) as Promise<T>
export const post = <T>(url: string, body?: unknown): Promise<T> =>
  http.post(url, body) as Promise<T>
export const patch = <T>(url: string, body?: unknown): Promise<T> =>
  http.patch(url, body) as Promise<T>
export const del = <T>(url: string): Promise<T> => http.delete(url) as Promise<T>
