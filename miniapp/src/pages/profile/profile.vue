<template>
  <view class="profile-page">
    <view class="profile-head">
      <view :class="['profile-avatar', `avatar-${selectedAvatar.tone}`]">{{ selectedAvatar.symbol }}</view>
      <view>
        <text class="profile-name">{{ user?.display_name || user?.username || '旅行用户' }}</text>
        <text class="profile-role">普通用户</text>
      </view>
    </view>

    <view class="avatar-card">
      <view class="avatar-card-head">
        <view>
          <text class="avatar-title">选择你的旅行头像</text>
          <text class="avatar-tip">更换后会同步显示在首页和聊天气泡中</text>
        </view>
        <text class="avatar-current">{{ selectedAvatar.name }}</text>
      </view>
      <view class="avatar-options">
        <view
          v-for="option in avatarOptions"
          :key="option.id"
          :class="['avatar-option', { selected: selectedAvatar.id === option.id }]"
          @tap="selectAvatar(option)"
        >
          <view :class="['avatar-option-symbol', `avatar-${option.tone}`]">{{ option.symbol }}</view>
          <text>{{ option.name }}</text>
          <view v-if="selectedAvatar.id === option.id" class="avatar-check">✓</view>
        </view>
      </view>
    </view>

    <view class="account-card">
      <view class="account-row account-row-static">
        <view class="account-icon account-icon-teal">号</view>
        <view class="account-copy">
          <text class="account-title">账号</text>
          <text class="account-value">{{ user?.username || '-' }}</text>
        </view>
      </view>
      <view class="account-divider" />
      <view class="account-row" @tap="openHistory">
        <view class="account-icon account-icon-blue">史</view>
        <view class="account-copy">
          <text class="account-title">历史会话</text>
          <text class="account-subtitle">查看和继续之前的旅行对话</text>
        </view>
        <text class="account-arrow">›</text>
      </view>
      <view class="account-divider" />
      <view class="account-row" @tap="openAccount">
        <view class="account-icon account-icon-violet">密</view>
        <view class="account-copy">
          <text class="account-title">账号管理</text>
          <text class="account-subtitle">修改密码，保护账号安全</text>
        </view>
        <text class="account-arrow">›</text>
      </view>
    </view>

    <view class="tip-card">
      <text class="tip-title">使用说明</text>
      <text>从首页选择旅行服务，或直接输入问题。尽量告诉我目的地、出行时间、游玩天数和个人偏好，AI 会据此为你规划。</text>
    </view>
    <button class="logout-button" @tap="logout">退出登录</button>

    <view v-if="showHistory" class="sheet-mask" @tap.self="closeHistory">
      <view class="sheet history-sheet">
        <view class="sheet-head">
          <view>
            <text class="sheet-title">历史会话</text>
            <text class="sheet-caption">每个功能最多保留 5 条</text>
          </view>
          <text class="sheet-close" @tap="closeHistory">关闭</text>
        </view>
        <scroll-view class="history-list" scroll-y>
          <view v-if="historyLoading" class="sheet-state">正在加载会话…</view>
          <view
            v-for="item in historyItems"
            :key="item.session_id"
            class="history-item"
            @tap="openHistorySession(item)"
          >
            <view class="history-item-head">
              <text class="history-scene">{{ item.scene_name || sceneName(item.scene_code) }}</text>
              <text class="history-date">{{ formatDate(item.updated_at || item.created_at) }}</text>
            </view>
            <text class="history-title">{{ item.title || '新会话' }}</text>
            <text class="history-preview">{{ item.preview || '尚未发送消息' }}</text>
            <view class="history-item-foot">
              <text>{{ item.message_count || 0 }} 条消息</text>
              <text class="history-open">打开会话 ›</text>
              <text class="history-delete" @tap.stop="deleteHistory(item)">删除</text>
            </view>
          </view>
          <view v-if="!historyLoading && !historyItems.length" class="sheet-state">
            还没有历史会话，去和旅行顾问聊聊吧。
          </view>
        </scroll-view>
      </view>
    </view>

    <view v-if="showAccount" class="sheet-mask" @tap.self="closeAccount">
      <view class="sheet account-sheet">
        <view class="sheet-head">
          <view>
            <text class="sheet-title">账号管理</text>
            <text class="sheet-caption">修改密码后当前设备仍保持登录</text>
          </view>
          <text class="sheet-close" @tap="closeAccount">关闭</text>
        </view>
        <view class="password-field">
          <text>当前密码</text>
          <input v-model="passwordForm.current_password" password maxlength="128" placeholder="请输入当前密码" placeholder-class="field-placeholder" />
        </view>
        <view class="password-field">
          <text>新密码</text>
          <input v-model="passwordForm.new_password" password maxlength="128" placeholder="至少 8 位字符" placeholder-class="field-placeholder" />
        </view>
        <view class="password-field">
          <text>确认新密码</text>
          <input v-model="passwordForm.confirm_password" password maxlength="128" placeholder="再次输入新密码" placeholder-class="field-placeholder" @confirm="changePassword" />
        </view>
        <text v-if="accountError" class="account-error">{{ accountError }}</text>
        <button class="save-password" :disabled="passwordLoading" @tap="changePassword">
          {{ passwordLoading ? '保存中…' : '保存新密码' }}
        </button>
      </view>
    </view>
  </view>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { clearAuth, currentUser, request } from '../../utils/api'
import { loadUserAvatar, saveUserAvatar, USER_AVATARS } from '../../utils/avatar'

const user = ref(currentUser())
const avatarOptions = USER_AVATARS
const selectedAvatar = ref(loadUserAvatar(user.value))
const showHistory = ref(false)
const historyLoading = ref(false)
const historyItems = ref([])
const showAccount = ref(false)
const passwordLoading = ref(false)
const accountError = ref('')
const passwordForm = reactive({ current_password: '', new_password: '', confirm_password: '' })
const isWechatAccount = () => String(user.value?.username || '').startsWith('wx_')

const FALLBACK_SCENE_NAMES = {
  TRAVEL_PLAN: 'AI 行程规划',
  POI_DISCOVERY: '景点查询',
  ROUTE_PLANNING: '路线交通规划',
  BUDGET_ESTIMATION: '费用估算',
}

onShow(() => {
  user.value = currentUser()
  if (!user.value || user.value.role !== 'user') {
    if (user.value) clearAuth()
    uni.reLaunch({ url: '/pages/index/index' })
    return
  }
  selectedAvatar.value = loadUserAvatar(user.value)
})

function selectAvatar(option) {
  selectedAvatar.value = saveUserAvatar(user.value, option.id)
  uni.showToast({ title: '头像已更换', icon: 'success' })
}

function sceneName(code) {
  return FALLBACK_SCENE_NAMES[code] || '旅行顾问'
}

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const now = new Date()
  const sameYear = date.getFullYear() === now.getFullYear()
  return `${sameYear ? '' : `${date.getFullYear()}年`}${date.getMonth() + 1}月${date.getDate()}日 ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

async function openHistory() {
  showHistory.value = true
  historyLoading.value = true
  try {
    const payload = await request('/api/v1/chat/sessions/all')
    historyItems.value = Array.isArray(payload.items) ? payload.items : []
  } catch (err) {
    if (/登录|401|失效/.test(err.message || '')) return signOut()
    historyItems.value = []
    uni.showToast({ title: err.message || '历史会话加载失败', icon: 'none' })
  } finally {
    historyLoading.value = false
  }
}

function closeHistory() {
  showHistory.value = false
}

function openHistorySession(item) {
  closeHistory()
  const scene = encodeURIComponent(item.scene_code || 'TRAVEL_PLAN')
  const session = encodeURIComponent(item.session_id)
  uni.navigateTo({ url: `/pages/chat/chat?scene=${scene}&session_id=${session}` })
}

function deleteHistory(item) {
  uni.showModal({
    title: '删除会话',
    content: '删除后将无法恢复，确定继续吗？',
    confirmColor: '#d16662',
    success: async ({ confirm }) => {
      if (!confirm) return
      try {
        await request(`/api/v1/chat/sessions/${encodeURIComponent(item.session_id)}`, { method: 'DELETE' })
        historyItems.value = historyItems.value.filter((entry) => entry.session_id !== item.session_id)
        uni.showToast({ title: '已删除', icon: 'success' })
      } catch (err) {
        if (/登录|401|失效/.test(err.message || '')) return signOut()
        uni.showToast({ title: err.message || '删除失败', icon: 'none' })
      }
    },
  })
}

function openAccount() {
  if (isWechatAccount()) {
    uni.showToast({ title: '微信登录无法修改密码', icon: 'none' })
    return
  }
  accountError.value = ''
  passwordForm.current_password = ''
  passwordForm.new_password = ''
  passwordForm.confirm_password = ''
  showAccount.value = true
}

function closeAccount() {
  if (passwordLoading.value) return
  showAccount.value = false
}

async function changePassword() {
  accountError.value = ''
  if (passwordLoading.value) return
  if (passwordForm.current_password.length < 8) {
    accountError.value = '请输入当前密码。'
    return
  }
  if (passwordForm.new_password.length < 8) {
    accountError.value = '新密码至少需要 8 个字符。'
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    accountError.value = '两次输入的新密码不一致。'
    return
  }
  if (passwordForm.current_password === passwordForm.new_password) {
    accountError.value = '新密码不能与当前密码相同。'
    return
  }
  passwordLoading.value = true
  try {
    await request('/api/v1/auth/me/password', {
      method: 'PATCH',
      data: {
        current_password: passwordForm.current_password,
        new_password: passwordForm.new_password,
      },
      header: { 'Content-Type': 'application/json' },
    })
    showAccount.value = false
    uni.showToast({ title: '密码修改成功', icon: 'success' })
  } catch (err) {
    if (/登录|401|失效/.test(err.message || '')) return signOut()
    accountError.value = err.message || '密码修改失败，请稍后重试。'
  } finally {
    passwordLoading.value = false
  }
}

async function logout() {
  try { await request('/api/v1/auth/logout', { method: 'POST' }) } catch { /* local logout still applies */ }
  signOut()
}

function signOut() {
  clearAuth()
  uni.reLaunch({ url: '/pages/index/index' })
}
</script>

<style scoped>
.profile-page { min-height: 100vh; padding: 36rpx 30rpx calc(50rpx + env(safe-area-inset-bottom)); background: #f7faf9; }
.profile-head { display: flex; align-items: center; gap: 20rpx; padding: 24rpx 6rpx 34rpx; }
.profile-avatar { display: flex; align-items: center; justify-content: center; width: 100rpx; height: 100rpx; border-radius: 34rpx; color: #fff; background: #157a6e; box-shadow: 0 12rpx 30rpx #157a6e30; font-size: 48rpx; font-weight: 700; }
.profile-name { display: block; color: #263f3b; font-size: 35rpx; font-weight: 700; }
.profile-role { display: block; margin-top: 10rpx; color: #7d918a; font-size: 23rpx; }
.avatar-card, .account-card, .tip-card { border: 1rpx solid #e0ece8; border-radius: 22rpx; background: #fff; }
.avatar-card { margin-bottom: 22rpx; padding: 25rpx 24rpx; }
.avatar-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16rpx; }
.avatar-title { display: block; color: #314c47; font-size: 27rpx; font-weight: 750; }
.avatar-tip { display: block; margin-top: 7rpx; color: #8a9a96; font-size: 20rpx; line-height: 1.5; }
.avatar-current { flex: none; padding: 7rpx 12rpx; border-radius: 18rpx; color: #388276; background: #e8f5f1; font-size: 19rpx; }
.avatar-options { display: flex; flex-wrap: wrap; gap: 16rpx; margin-top: 22rpx; }
.avatar-option { position: relative; display: flex; width: calc((100% - 32rpx) / 3); flex-direction: column; align-items: center; padding: 16rpx 8rpx 13rpx; border: 2rpx solid transparent; border-radius: 18rpx; color: #71847f; background: #f7faf9; font-size: 20rpx; }
.avatar-option.selected { border-color: #69ad9f; background: #eef8f5; }
.avatar-option-symbol { display: flex; align-items: center; justify-content: center; width: 72rpx; height: 72rpx; margin-bottom: 9rpx; border-radius: 24rpx; color: #fff; font-size: 34rpx; }
.avatar-check { position: absolute; top: 7rpx; right: 7rpx; display: flex; align-items: center; justify-content: center; width: 27rpx; height: 27rpx; border-radius: 50%; color: #fff; background: #399080; font-size: 17rpx; }
.avatar-coral { background: linear-gradient(145deg, #ff998d, #e77765); }
.avatar-teal { background: linear-gradient(145deg, #55b9a7, #278b7d); }
.avatar-green { background: linear-gradient(145deg, #78b986, #438b5b); }
.avatar-blue { background: linear-gradient(145deg, #70acef, #477fca); }
.avatar-slate { background: linear-gradient(145deg, #7d91aa, #55687d); }
.avatar-amber { background: linear-gradient(145deg, #f3b85e, #dd8b37); }
.avatar-violet { background: linear-gradient(145deg, #a88bd0, #765baa); }
.account-card { padding: 7rpx 24rpx; }
.account-row { display: flex; align-items: center; min-height: 108rpx; }
.account-icon { display: flex; flex: none; align-items: center; justify-content: center; width: 58rpx; height: 58rpx; border-radius: 18rpx; color: #fff; font-size: 25rpx; font-weight: 700; }
.account-icon-teal { background: linear-gradient(145deg, #67b9a9, #318f80); }
.account-icon-blue { background: linear-gradient(145deg, #75aef2, #4e83d0); }
.account-icon-violet { background: linear-gradient(145deg, #aa8fd5, #795cae); }
.account-copy { min-width: 0; margin-left: 18rpx; }
.account-title, .account-value, .account-subtitle { display: block; }
.account-title { color: #405952; font-size: 26rpx; font-weight: 700; }
.account-value, .account-subtitle { margin-top: 6rpx; color: #8a9a96; font-size: 21rpx; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-arrow { margin-left: auto; color: #b1c0bb; font-size: 40rpx; }
.account-divider { height: 1rpx; margin-left: 76rpx; background: #edf3f1; }
.tip-card { margin-top: 22rpx; padding: 25rpx 24rpx; background: #eaf6f2; }
.tip-card text { display: block; color: #65847b; font-size: 24rpx; line-height: 1.65; }
.tip-card .tip-title { margin-bottom: 8rpx; color: #32766b; font-size: 27rpx; font-weight: 700; }
.logout-button { height: 82rpx; margin-top: 60rpx; border: 1rpx solid #f0d9d6; border-radius: 16rpx; color: #c0645a; background: #fff; font-size: 27rpx; line-height: 80rpx; }
.sheet-mask { position: fixed; z-index: 20; top: 0; right: 0; bottom: 0; left: 0; display: flex; align-items: flex-end; background: rgba(25, 47, 43, .38); }
.sheet { width: 100%; padding: 28rpx 30rpx calc(28rpx + env(safe-area-inset-bottom)); border-radius: 30rpx 30rpx 0 0; background: #fff; box-shadow: 0 -10rpx 40rpx rgba(46, 79, 70, .16); }
.history-sheet { max-height: 78vh; }
.account-sheet { padding-bottom: calc(40rpx + env(safe-area-inset-bottom)); }
.sheet-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18rpx; margin-bottom: 23rpx; }
.sheet-title { display: block; color: #2d4841; font-size: 31rpx; font-weight: 800; }
.sheet-caption { display: block; margin-top: 7rpx; color: #94a29e; font-size: 20rpx; }
.sheet-close { flex: none; padding: 8rpx 0 8rpx 18rpx; color: #548e82; font-size: 23rpx; }
.history-list { max-height: 58vh; }
.history-item { margin-bottom: 16rpx; padding: 20rpx; border: 1rpx solid #e7efec; border-radius: 18rpx; background: #fbfdfc; }
.history-item:last-child { margin-bottom: 0; }
.history-item-head, .history-item-foot { display: flex; align-items: center; }
.history-scene { padding: 6rpx 11rpx; border-radius: 14rpx; color: #3b8779; background: #e8f5f1; font-size: 19rpx; }
.history-date { margin-left: auto; color: #a0ada9; font-size: 18rpx; }
.history-title { display: block; margin-top: 14rpx; color: #3e5650; font-size: 25rpx; font-weight: 700; }
.history-preview { display: -webkit-box; margin-top: 8rpx; overflow: hidden; color: #82928d; font-size: 21rpx; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.history-item-foot { margin-top: 15rpx; color: #a0ada9; font-size: 19rpx; }
.history-open { margin-left: auto; color: #548e82; }
.history-delete { margin-left: 22rpx; color: #c76d67; }
.sheet-state { padding: 50rpx 20rpx; color: #8b9c97; text-align: center; font-size: 23rpx; }
.password-field { margin-bottom: 20rpx; padding: 17rpx 20rpx 14rpx; border: 1rpx solid #e4eeeb; border-radius: 16rpx; background: #f9fcfb; }
.password-field > text { display: block; color: #5e756e; font-size: 21rpx; }
.password-field input { height: 54rpx; margin-top: 5rpx; color: #304a43; font-size: 26rpx; }
.field-placeholder { color: #b0bdb9; }
.account-error { display: block; margin: 2rpx 4rpx 18rpx; color: #c45e59; font-size: 21rpx; line-height: 1.45; }
.save-password { height: 82rpx; border-radius: 16rpx; color: #fff; background: linear-gradient(135deg, #4caa97, #287f74); font-size: 27rpx; line-height: 82rpx; }
.save-password[disabled] { opacity: .6; }
</style>
