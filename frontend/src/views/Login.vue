<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { setAuth } from '@/stores/auth'
import { listServices } from '@/api'

const router = useRouter()
const username = ref('')
const password = ref('')
const submitting = ref(false)

async function submit() {
  if (!username.value || !password.value) {
    MessagePlugin.warning('请输入用户名和密码')
    return
  }
  submitting.value = true
  setAuth(username.value, password.value)
  try {
    // 用一次真实请求验证凭证（登录失败时拦截器会清掉凭证并提示）
    await listServices()
    router.push('/')
  } catch {
    // 错误提示由拦截器统一弹出，这里不再重复
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-head">
        <div class="logo-box">M</div>
        <div class="app-title">MCP 网关控制台</div>
      </div>
      <!-- 注意：t-form 的 submit 是组件自定义事件（payload 不是原生 Event），
           不能加 .prevent 修饰符——会对普通对象调 preventDefault 直接抛错；
           原生默认行为由 TDesign 内部阻止 -->
      <t-form label-width="0" @submit="submit">
        <t-form-item>
          <t-input v-model="username" placeholder="管理员用户名" clearable />
        </t-form-item>
        <t-form-item>
          <t-input
            v-model="password"
            type="password"
            placeholder="管理员密码"
            clearable
            @enter="submit"
          />
        </t-form-item>
        <t-button block type="submit" :loading="submitting">登录控制台</t-button>
      </t-form>
      <p class="login-hint">使用 GATEWAY_ADMIN_USERNAME / GATEWAY_ADMIN_PASSWORD 配置的账号登录</p>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(155deg, #0B44C8 0%, #0052D9 46%, #4C8CFF 100%);
}
/* 两团柔光，营造层次 */
.login-wrap::before,
.login-wrap::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}
.login-wrap::before {
  width: 520px; height: 520px; left: -140px; bottom: -180px;
  background: radial-gradient(circle, rgba(255, 255, 255, .14), transparent 65%);
}
.login-wrap::after {
  width: 420px; height: 420px; right: -120px; top: -140px;
  background: radial-gradient(circle, rgba(255, 255, 255, .1), transparent 65%);
}
.login-card {
  position: relative;
  z-index: 1;
  width: 380px;
  background: var(--color-bg-card);
  border-radius: 20px;
  padding: 36px 32px;
  box-shadow: var(--shadow-float);
}
.login-head { display: flex; align-items: center; margin-bottom: 28px; }
.login-head .logo-box {
  margin-left: 0;
  width: 32px; height: 32px; border-radius: 10px; font-size: 16px;
  box-shadow: var(--shadow-btn);
}
.login-hint {
  margin-top: 18px;
  font: var(--font-caption);
  color: var(--color-text-muted);
  line-height: 1.6;
}
</style>
