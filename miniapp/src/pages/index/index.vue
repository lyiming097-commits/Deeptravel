<template>
  <view class="auth-page">
    <view class="hero-scene">
      <view class="hero-light hero-light-one" />
      <view class="hero-light hero-light-two" />
      <view class="brand-copy">
        <text class="welcome-line">欢迎来到</text>
        <text class="brand-name">Deep Travel</text>
        <text class="brand-subtitle">AI 旅行助手 · 让旅程更简单</text>
      </view>

      <view class="flight-path" />
      <text class="flight-plane">✈</text>
      <view class="cloud cloud-one" />
      <view class="cloud cloud-two" />
      <view class="mountain mountain-far-one" />
      <view class="mountain mountain-far-two" />
      <view class="mountain mountain-main">
        <view class="snow snow-one" />
        <view class="snow snow-two" />
      </view>
      <view class="mountain mountain-side" />
      <view class="lake-shine" />
      <view class="pagoda" aria-hidden="true">
        <view class="pagoda-spire" />
        <view class="pagoda-roof pagoda-roof-top" />
        <view class="pagoda-room pagoda-room-top" />
        <view class="pagoda-roof pagoda-roof-main" />
        <view class="pagoda-room pagoda-room-main" />
        <view class="pagoda-base" />
      </view>
    </view>

    <view class="auth-card-wrap">
      <view class="auth-card">
        <view class="auth-tabs">
          <view :class="['tab', { active: mode === 'login' }]" @tap="switchMode('login')">
            <text>登录</text>
          </view>
          <view :class="['tab', { active: mode === 'register' }]" @tap="switchMode('register')">
            <text>注册</text>
          </view>
        </view>

        <view class="card-heading">
          <text class="card-title">{{ mode === 'login' ? '欢迎回来，继续你的美好旅程' : '创建账号，开启你的旅行' }}</text>
          <text class="card-tip">{{ mode === 'login' ? '登录账号，获取个性化的旅行推荐与服务' : '注册普通用户账号，保存你的旅行计划与会话' }}</text>
        </view>

        <view class="field">
          <view class="field-icon user-line-icon">
            <view class="user-head" />
            <view class="user-body" />
          </view>
          <view class="field-content">
            <text>用户名</text>
            <input v-model="form.username" maxlength="64" placeholder="请输入用户名" placeholder-class="placeholder" />
          </view>
        </view>

        <view v-if="mode === 'register'" class="field">
          <view class="field-icon nickname-icon">旅</view>
          <view class="field-content">
            <text>怎么称呼你（可选）</text>
            <input v-model="form.display_name" maxlength="80" placeholder="例如：小刘" placeholder-class="placeholder" />
          </view>
        </view>

        <view class="field">
          <view class="field-icon lock-line-icon">
            <view class="lock-loop" />
            <view class="lock-body" />
          </view>
          <view class="field-content">
            <text>密码</text>
            <input
              v-model="form.password"
              :password="!showPassword"
              maxlength="128"
              placeholder="请输入密码（至少 8 位）"
              placeholder-class="placeholder"
              @confirm="submit"
            />
          </view>
          <text class="password-toggle" @tap="showPassword = !showPassword">{{ showPassword ? '隐藏' : '显示' }}</text>
        </view>

        <view v-if="error" class="error">
          <text class="error-icon">!</text>
          <text class="error-message">{{ error }}</text>
        </view>

        <button class="primary-button" :disabled="loading" @tap="submit">
          <text>{{ loading ? '请稍候…' : mode === 'login' ? '登 录' : '注 册' }}</text>
          <view v-if="!loading" class="button-arrow">→</view>
        </button>

        <view class="auth-divider"><view /><text>其他登录方式</text><view /></view>

        <button class="wechat-button" :disabled="loading" @tap="wechatLogin">
          <view class="wechat-icon">微</view>
          <text>{{ loading ? '正在连接微信…' : '微信登录' }}</text>
        </button>

        <view class="agreement-note">
          <view class="shield-icon">✓</view>
          <view>
            <text>首次使用微信登录将自动创建普通用户账号</text>
            <text>登录即代表同意《用户协议》与《隐私政策》</text>
          </view>
        </view>
      </view>
    </view>

    <view class="footer-note">
      <view class="footer-shield">✓</view>
      <text>AI 可能会出错，重要行程信息请以官方实时数据为准</text>
    </view>
  </view>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { clearAuth, currentUser, request, saveAuth } from '../../utils/api'

const mode = ref('login')
const loading = ref(false)
const error = ref('')
const showPassword = ref(false)
const form = reactive({ username: '', password: '', display_name: '' })

function switchMode(nextMode) {
  if (mode.value === nextMode || loading.value) return
  mode.value = nextMode
  error.value = ''
  showPassword.value = false
  form.password = ''
}

onMounted(() => {
  const storedUser = currentUser()
  if (storedUser?.role === 'user') uni.reLaunch({ url: '/pages/home/home' })
  else if (storedUser) clearAuth()
})

async function submit() {
  error.value = ''
  const username = form.username.trim()
  if (username.length < 3) {
    error.value = '用户名至少需要 3 个字符。'
    return
  }
  if (form.password.length < 8) {
    error.value = '密码至少需要 8 个字符。'
    return
  }
  loading.value = true
  try {
    if (mode.value === 'register') {
      await request('/api/v1/auth/register', {
        method: 'POST',
        data: {
          username,
          password: form.password,
          display_name: form.display_name.trim() || null,
        },
        header: { 'Content-Type': 'application/json' },
      })
    }
    const login = await request('/api/v1/auth/user/login', {
      method: 'POST',
      data: { username, password: form.password },
      header: { 'Content-Type': 'application/json' },
    })
    saveAuth(login)
    uni.reLaunch({ url: '/pages/home/home' })
  } catch (err) {
    clearAuth()
    error.value = err.message || '登录失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function getWechatCode() {
  return new Promise((resolve, reject) => {
    if (typeof uni.login !== 'function') {
      reject(new Error('当前运行环境不支持微信登录，请使用微信开发者工具或微信打开'))
      return
    }
    uni.login({
      provider: 'weixin',
      success: (result) => {
        if (result?.code) resolve(result.code)
        else reject(new Error('未获取到微信登录凭证，请重试'))
      },
      fail: (reason) => reject(new Error(reason?.errMsg || '微信登录已取消')),
    })
  })
}

async function wechatLogin() {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    const code = await getWechatCode()
    const login = await request('/api/v1/auth/wechat/login', {
      method: 'POST',
      data: { code },
      header: { 'Content-Type': 'application/json' },
      timeout: 20000,
    })
    saveAuth(login)
    uni.reLaunch({ url: '/pages/home/home' })
  } catch (err) {
    clearAuth()
    error.value = err.message || '微信登录失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page { position: relative; min-height: 100vh; overflow: hidden; padding-bottom: calc(34rpx + env(safe-area-inset-bottom)); background: linear-gradient(160deg, #6474ee 0%, #7288f6 42%, #9faaff 100%); }
.hero-scene { position: relative; height: 610rpx; overflow: hidden; color: #fff; background: radial-gradient(circle at 78% 28%, #ccd6ff 0, #9bafff 23%, transparent 48%), linear-gradient(155deg, #5c69e5 0%, #7489f4 48%, #9eaefe 100%); }
.hero-light { position: absolute; border-radius: 50%; background: #fff; opacity: .12; filter: blur(3rpx); }
.hero-light-one { top: 88rpx; right: -60rpx; width: 300rpx; height: 300rpx; }
.hero-light-two { top: -120rpx; left: 165rpx; width: 260rpx; height: 260rpx; opacity: .08; }
.brand-copy { position: relative; z-index: 5; padding: calc(env(safe-area-inset-top) + 73rpx) 58rpx 0; }
.welcome-line, .brand-name, .brand-subtitle { display: block; }
.welcome-line { font-size: 42rpx; font-weight: 850; letter-spacing: 2rpx; text-shadow: 0 4rpx 12rpx #3848aa38; }
.brand-name { margin-top: 4rpx; font-size: 59rpx; font-style: italic; font-weight: 900; letter-spacing: -1rpx; text-shadow: 0 5rpx 15rpx #3848aa42; }
.brand-subtitle { margin-top: 18rpx; font-size: 24rpx; letter-spacing: 2rpx; opacity: .94; }
.flight-path { position: absolute; z-index: 4; top: 267rpx; right: 91rpx; width: 160rpx; height: 64rpx; transform: rotate(-9deg); border-top: 2rpx dashed #ffffffb8; border-radius: 50%; }
.flight-plane { position: absolute; z-index: 5; top: 231rpx; right: 60rpx; transform: rotate(9deg); color: #fff; font-size: 38rpx; }
.cloud { position: absolute; z-index: 1; height: 28rpx; border-radius: 30rpx; background: #e8edff; opacity: .58; }
.cloud::before, .cloud::after { position: absolute; bottom: 0; border-radius: 50%; background: inherit; content: ''; }
.cloud::before { left: 17rpx; width: 46rpx; height: 46rpx; }
.cloud::after { right: 16rpx; width: 34rpx; height: 34rpx; }
.cloud-one { left: 40rpx; bottom: 171rpx; width: 125rpx; }
.cloud-two { left: 214rpx; bottom: 205rpx; width: 90rpx; transform: scale(.72); opacity: .36; }
.mountain { position: absolute; z-index: 2; transform: rotate(45deg); border-radius: 34rpx 18rpx 30rpx 18rpx; }
.mountain-far-one { left: -10rpx; bottom: 32rpx; width: 260rpx; height: 260rpx; background: linear-gradient(135deg, #6e8be3, #425fbb); opacity: .76; }
.mountain-far-two { right: 192rpx; bottom: 23rpx; width: 255rpx; height: 255rpx; background: linear-gradient(135deg, #8da7f0, #5573ca); opacity: .9; }
.mountain-main { z-index: 3; right: 35rpx; bottom: 6rpx; width: 335rpx; height: 335rpx; background: linear-gradient(135deg, #e5eaff 0 14%, #bfcdfb 15% 31%, #7d9be6 32% 58%, #4e6fc8 100%); box-shadow: -20rpx 16rpx 50rpx #4862b735; }
.mountain-side { z-index: 2; right: -100rpx; bottom: -58rpx; width: 280rpx; height: 280rpx; background: linear-gradient(135deg, #c0ccfb, #6684d5); }
.snow { position: absolute; top: -2rpx; left: -2rpx; width: 76rpx; height: 76rpx; background: #f6f7ff; }
.snow-one { clip-path: polygon(0 0, 100% 0, 0 100%); }
.snow-two { top: 43rpx; left: -20rpx; width: 62rpx; height: 27rpx; transform: rotate(-5deg); border-radius: 50%; opacity: .78; }
.lake-shine { position: absolute; z-index: 4; right: -100rpx; bottom: -28rpx; left: -100rpx; height: 132rpx; border-radius: 50% 50% 0 0; background: linear-gradient(180deg, #75a0efbb, #406fd3e8); box-shadow: inset 0 15rpx 24rpx #cbd9ff2e; }
.pagoda { position: absolute; z-index: 5; left: 82rpx; bottom: 47rpx; width: 112rpx; height: 132rpx; color: #263f82; filter: drop-shadow(0 7rpx 7rpx #314f9c55); opacity: .92; }
.pagoda-spire { position: absolute; top: 0; left: 54rpx; width: 4rpx; height: 24rpx; border-radius: 4rpx; background: currentColor; }
.pagoda-spire::before { position: absolute; top: -2rpx; left: -5rpx; width: 14rpx; height: 7rpx; border-radius: 50%; background: currentColor; content: ''; }
.pagoda-roof { position: absolute; left: 0; width: 112rpx; height: 25rpx; background: currentColor; clip-path: polygon(0 68%, 10% 61%, 34% 15%, 48% 15%, 50% 0, 52% 15%, 66% 15%, 90% 61%, 100% 68%, 89% 79%, 61% 67%, 50% 94%, 39% 67%, 11% 79%); }
.pagoda-roof-top { top: 18rpx; transform: scale(.72); }
.pagoda-roof-main { top: 67rpx; }
.pagoda-room { position: absolute; border-right: 5rpx solid currentColor; border-left: 5rpx solid currentColor; }
.pagoda-room::after { position: absolute; top: 0; right: 8rpx; left: 8rpx; height: 4rpx; background: currentColor; content: ''; }
.pagoda-room-top { top: 38rpx; left: 41rpx; width: 30rpx; height: 34rpx; }
.pagoda-room-main { top: 89rpx; left: 27rpx; width: 58rpx; height: 35rpx; border-width: 6rpx; }
.pagoda-base { position: absolute; bottom: 2rpx; left: 15rpx; width: 82rpx; height: 8rpx; border-radius: 6rpx 6rpx 2rpx 2rpx; background: currentColor; box-shadow: 0 7rpx 0 -2rpx currentColor; }
.auth-card-wrap { position: relative; z-index: 10; margin: -52rpx 27rpx 0; }
.auth-card { padding: 31rpx 36rpx 37rpx; border-radius: 35rpx; background: #fff; box-shadow: 0 22rpx 55rpx #33459238; }
.auth-tabs { display: flex; height: 75rpx; border-bottom: 1rpx solid #eef0f7; }
.tab { position: relative; display: flex; height: 75rpx; flex: 1; align-items: flex-start; justify-content: center; color: #9298a8; font-size: 29rpx; font-weight: 700; }
.tab.active { color: #606bea; }
.tab.active::after { position: absolute; right: 27%; bottom: 0; left: 27%; height: 5rpx; border-radius: 5rpx; background: #6570ed; content: ''; }
.card-heading { margin: 35rpx 0 25rpx; text-align: center; }
.card-title, .card-tip { display: block; }
.card-title { color: #272d40; font-size: 29rpx; font-weight: 850; }
.card-tip { margin-top: 12rpx; color: #8990a0; font-size: 21rpx; line-height: 1.55; }
.field { display: flex; min-height: 102rpx; align-items: center; margin-top: 17rpx; padding: 13rpx 20rpx; border: 2rpx solid #e5e8f0; border-radius: 18rpx; background: #fff; }
.field:focus-within { border-color: #8992f1; box-shadow: 0 0 0 5rpx #6b74ed12; }
.field-icon { position: relative; display: flex; width: 48rpx; height: 55rpx; flex-shrink: 0; align-items: center; justify-content: center; margin-right: 14rpx; color: #858ca0; }
.user-head { position: absolute; top: 5rpx; width: 20rpx; height: 20rpx; border: 3rpx solid #858ca0; border-radius: 50%; }
.user-body { position: absolute; bottom: 4rpx; width: 32rpx; height: 24rpx; border: 3rpx solid #858ca0; border-bottom: 0; border-radius: 20rpx 20rpx 0 0; }
.lock-loop { position: absolute; top: 4rpx; width: 23rpx; height: 23rpx; border: 3rpx solid #858ca0; border-bottom: 0; border-radius: 14rpx 14rpx 0 0; }
.lock-body { position: absolute; bottom: 5rpx; width: 32rpx; height: 29rpx; border: 3rpx solid #858ca0; border-radius: 6rpx; }
.nickname-icon { font-size: 23rpx; font-weight: 800; }
.field-content { min-width: 0; flex: 1; }
.field-content > text { display: block; color: #8e94a4; font-size: 18rpx; }
.field-content input { width: 100%; height: 48rpx; color: #30364a; font-size: 25rpx; }
.placeholder { color: #aeb3bf; font-size: 23rpx; }
.password-toggle { flex-shrink: 0; padding: 15rpx 0 15rpx 12rpx; color: #777fe2; font-size: 19rpx; }
.error { display: flex; align-items: flex-start; gap: 9rpx; margin-top: 14rpx; padding: 11rpx 13rpx; border-radius: 11rpx; color: #c05269; background: #fff0f3; font-size: 21rpx; line-height: 1.5; }
.error-icon { display: flex; width: 27rpx; height: 27rpx; flex-shrink: 0; align-items: center; justify-content: center; border-radius: 50%; color: #fff; background: #dc6678; font-size: 17rpx; font-weight: 800; }
.error-message { min-width: 0; flex: 1; color: #c05269; line-height: 1.5; word-break: break-word; }
.primary-button { position: relative; display: flex; height: 84rpx; align-items: center; justify-content: center; margin: 27rpx 0 0; border-radius: 42rpx; color: #fff; background: linear-gradient(105deg, #7679f0, #535ed9); box-shadow: 0 13rpx 25rpx #5760d748; font-size: 29rpx; font-weight: 800; line-height: 84rpx; letter-spacing: 8rpx; }
.primary-button::after, .wechat-button::after { border: 0; }
.primary-button[disabled], .wechat-button[disabled] { opacity: .55; }
.button-arrow { position: absolute; right: 10rpx; display: flex; width: 64rpx; height: 64rpx; align-items: center; justify-content: center; border-radius: 50%; color: #646de4; background: #fff; font-size: 32rpx; font-weight: 500; letter-spacing: 0; }
.auth-divider { display: flex; align-items: center; gap: 17rpx; margin: 35rpx 0 20rpx; color: #a4a9b5; font-size: 19rpx; }
.auth-divider view { height: 1rpx; flex: 1; background: #e1e4eb; }
.wechat-button { display: flex; height: 77rpx; align-items: center; justify-content: center; gap: 13rpx; margin: 0; border: 2rpx solid #e0e4e9; border-radius: 39rpx; color: #30394d; background: #fff; box-shadow: 0 6rpx 14rpx #33445e14; font-size: 25rpx; font-weight: 750; line-height: 77rpx; }
.wechat-icon { display: flex; width: 37rpx; height: 37rpx; align-items: center; justify-content: center; border-radius: 50%; color: #fff; background: #31b968; font-size: 19rpx; font-weight: 900; }
.agreement-note { display: flex; align-items: flex-start; justify-content: center; gap: 10rpx; margin-top: 29rpx; color: #939baa; font-size: 18rpx; line-height: 1.75; text-align: center; }
.agreement-note text { display: block; }
.agreement-note text + text { color: #737ee8; }
.shield-icon, .footer-shield { display: flex; width: 25rpx; height: 28rpx; flex-shrink: 0; align-items: center; justify-content: center; border: 2rpx solid currentColor; border-radius: 6rpx 6rpx 10rpx 10rpx; font-size: 14rpx; }
.footer-note { position: relative; z-index: 2; display: flex; align-items: center; justify-content: center; gap: 10rpx; padding: 41rpx 32rpx 0; color: #eef1ff; font-size: 18rpx; line-height: 1.5; text-align: center; }
.footer-shield { color: #fff; }
@media (max-height: 760px) {
  .hero-scene { height: 535rpx; }
  .brand-copy { padding-top: calc(env(safe-area-inset-top) + 48rpx); }
  .auth-card { padding-top: 25rpx; }
  .card-heading { margin: 25rpx 0 19rpx; }
}
</style>
