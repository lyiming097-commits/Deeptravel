<template>
  <view class="home-page">
    <view class="page-head">
      <view class="head-copy">
        <text class="greeting">你好，{{ displayName }} 👋</text>
        <text class="greeting-tip">我是你的 AI 旅行顾问，帮你规划完美旅程</text>
      </view>
      <view :class="['avatar', `avatar-${userAvatar.tone}`]" @tap="openProfile">
        {{ userAvatar.symbol }}
      </view>
    </view>

    <view class="planner-card">
      <view class="planner-glow" />
      <view class="mountain mountain-back" />
      <view class="mountain mountain-front" />
      <view class="planner-copy">
        <text class="planner-title">想去哪里走走？</text>
        <text class="planner-subtitle">告诉我你的想法，AI 为你定制专属行程</text>
      </view>

      <scroll-view class="planner-fields" scroll-x :show-scrollbar="false">
        <view class="planner-field-row">
          <view
            v-for="field in plannerFields"
            :key="field.key"
            :class="['planner-field', { selected: plannerSelections[field.key] }]"
            @tap="selectPlannerField(field)"
          >
            <text class="planner-field-icon">{{ field.icon }}</text>
            <text>{{ plannerSelections[field.key]?.label || field.title }}</text>
          </view>
        </view>
      </scroll-view>

      <view class="planner-input-wrap">
        <input
          v-model="planIdea"
          class="planner-input"
          maxlength="300"
          confirm-type="send"
          placeholder="例如：国庆去杭州玩3天，预算2000元"
          placeholder-class="planner-placeholder"
          @confirm="submitIdea"
        />
        <view class="send-plan" hover-class="send-plan-active" @tap="submitIdea">➤</view>
      </view>
    </view>

    <view class="hot-strip">
      <view class="hot-label"><text>🔥</text><text>热门搜索</text></view>
      <scroll-view class="hot-scroll" scroll-x :show-scrollbar="false">
        <view class="hot-items">
          <text v-for="topic in visibleHotSearches" :key="topic" @tap="openHotSearch(topic)">{{ topic }}</text>
        </view>
      </scroll-view>
      <view class="change-hot" @tap="changeHotSearches"><text>↻</text><text>换一换</text></view>
    </view>

    <view class="section services-section">
      <view class="section-head">
        <view class="section-title-row">
          <text class="section-symbol">✦</text>
          <text class="section-title">AI 旅行服务</text>
          <text class="section-note">一站式解决你的旅行需求</text>
        </view>
        <text class="section-link" @tap="openAssistant">开始咨询 ›</text>
      </view>

      <view class="service-grid">
        <view
          v-for="feature in features"
          :key="feature.code"
          :class="['service-card', `service-${feature.tone}`]"
          hover-class="card-active"
          @tap="openFeature(feature.code)"
        >
          <view :class="['service-icon', `service-icon-${feature.tone}`]">{{ feature.icon }}</view>
          <view class="service-copy">
            <text class="service-name">{{ feature.name }}</text>
            <text class="service-description">{{ feature.description }}</text>
            <view class="service-tags">
              <text v-for="tag in feature.tags" :key="tag">{{ tag }}</text>
            </view>
          </view>
          <view class="service-arrow">›</view>
        </view>
      </view>
    </view>

    <view class="section destination-section">
      <view class="section-head compact-head">
        <view class="section-title-row">
          <text class="section-symbol coral">⌖</text>
          <text class="section-title">热门目的地推荐</text>
        </view>
      </view>
      <scroll-view class="filter-scroll" scroll-x :show-scrollbar="false">
        <view class="filter-row">
          <text
            v-for="filter in destinationFilters"
            :key="filter.key"
            :class="['filter-chip', { active: selectedDestinationFilter === filter.key }]"
            @tap="selectedDestinationFilter = filter.key"
          >{{ filter.icon }} {{ filter.label }}</text>
        </view>
      </scroll-view>
      <scroll-view class="destination-scroll" scroll-x :show-scrollbar="false" enhanced>
        <view class="destination-row">
          <view
            v-for="destination in filteredDestinations"
            :key="destination.city"
            :class="['destination-card', `destination-${destination.tone}`]"
            hover-class="card-active"
            @tap="openDestination(destination)"
          >
            <view class="destination-sun" />
            <text class="destination-landmark">{{ destination.landmark }}</text>
            <view class="destination-overlay">
              <text class="destination-city">{{ destination.city }}</text>
              <text class="destination-slogan">{{ destination.slogan }}</text>
              <view class="destination-meta">
                <text>★ {{ destination.score }}</text>
                <text>{{ destination.days }}日游</text>
                <text>人均约 ¥{{ destination.budget }}</text>
              </view>
            </view>
          </view>
        </view>
      </scroll-view>
    </view>

    <view class="section recent-section">
      <view class="section-head compact-head">
        <view class="section-title-row">
          <text class="section-symbol suitcase">▣</text>
          <text class="section-title">继续你的旅行计划</text>
        </view>
        <text v-if="recentPlan" class="section-link" @tap="openRecentPlan">继续规划 ›</text>
      </view>
      <view class="recent-card" hover-class="card-active" @tap="recentPlan ? openRecentPlan() : openFeature('TRAVEL_PLAN')">
        <view class="recent-visual"><text>{{ recentPlan ? '行' : '＋' }}</text></view>
        <view class="recent-copy">
          <text class="recent-title">{{ recentPlan?.title || '创建你的第一份专属行程' }}</text>
          <text class="recent-note">{{ recentPlan?.preview || '告诉 AI 目的地、时间和喜好，即刻开始规划' }}</text>
          <view class="recent-progress">
            <view :style="{ width: recentPlan ? '64%' : '18%' }" />
          </view>
        </view>
        <text class="recent-action">{{ recentPlan ? '继续' : '创建' }}</text>
      </view>
    </view>

    <view class="safe-bottom" />

    <view class="assistant-dock" hover-class="assistant-dock-active" @tap="openAssistant">
      <view class="assistant-face">🧑🏻‍💼</view>
      <text>AI 对话</text>
    </view>
  </view>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { clearAuth, currentUser, request } from '../../utils/api'
import { loadUserAvatar } from '../../utils/avatar'

const user = ref(currentUser())
const userAvatar = ref(loadUserAvatar(user.value))
const sceneNames = ref({})
const planIdea = ref('')
const plannerSelections = reactive({ destination: null, days: null, budget: null, preference: null })
const hotBatch = ref(0)
const selectedDestinationFilter = ref('autumn')
const recentPlan = ref(null)

const plannerFields = [
  { key: 'destination', title: '目的地', icon: '⌖', options: [{ label: '杭州', value: '目的地杭州' }, { label: '北京', value: '目的地北京' }, { label: '成都', value: '目的地成都' }, { label: '暂未决定', value: '目的地暂未决定，请推荐' }] },
  { key: 'days', title: '出行天数', icon: '▣', options: [{ label: '2天', value: '游玩2天' }, { label: '3天', value: '游玩3天' }, { label: '5天', value: '游玩5天' }, { label: '一周', value: '游玩一周' }] },
  { key: 'budget', title: '预算', icon: '◉', options: [{ label: '¥1000内', value: '预算1000元以内' }, { label: '¥2000', value: '预算2000元左右' }, { label: '¥5000', value: '预算5000元左右' }, { label: '预算灵活', value: '预算比较灵活' }] },
  { key: 'preference', title: '喜欢的玩法', icon: '♥', options: [{ label: '山水风光', value: '喜欢山水风光' }, { label: '历史人文', value: '喜欢历史人文' }, { label: '美食休闲', value: '喜欢美食和休闲体验' }, { label: '亲子体验', value: '偏好亲子体验' }] },
]

const featureDefaults = [
  { code: 'TRAVEL_PLAN', name: '智能规划行程', description: 'AI 定制专属行程方案', icon: 'AI', tone: 'coral', tags: ['景点推荐', '路线规划', '行程安排'] },
  { code: 'POI_DISCOVERY', name: '查询景点', description: '发现值得去的景点', icon: '⛰', tone: 'teal', tags: ['景点介绍', '门票信息', '游玩攻略'] },
  { code: 'ROUTE_PLANNING', name: '交通规划', description: '查询路线和交通方案', icon: '🚄', tone: 'blue', tags: ['高铁', '飞机', '公交地铁'] },
  { code: 'BUDGET_ESTIMATION', name: '预算计算', description: '估算旅行费用更省心', icon: '¥', tone: 'amber', tags: ['住宿', '餐饮', '交通', '门票'] },
]

const hotSearchGroups = [
  ['北京3日游', '杭州周末游', '上海亲子游', '成都美食游'],
  ['西安古城游', '洛阳2日游', '南京文化游', '宁波周边游'],
  ['秋季赏景', '高铁出行', '小众古镇', '亲子度假'],
]

const destinationFilters = [
  { key: 'autumn', label: '秋季推荐', icon: '🍁' },
  { key: 'nature', label: '山水风光', icon: '⛰' },
  { key: 'history', label: '历史古都', icon: '🏛' },
  { key: 'food', label: '美食之旅', icon: '🍜' },
  { key: 'photo', label: '网红打卡', icon: '📷' },
]

const destinations = [
  { city: '北京', landmark: '🏯', slogan: '银杏金黄 · 赏秋最佳', score: '4.8', days: 3, budget: 1500, tone: 'beijing', categories: ['autumn', 'history'] },
  { city: '杭州', landmark: '🛶', slogan: '西湖秋色 · 诗意江南', score: '4.9', days: 2, budget: 1200, tone: 'hangzhou', categories: ['autumn', 'nature', 'photo'] },
  { city: '南京', landmark: '🏛', slogan: '梧桐大道 · 金陵秋韵', score: '4.7', days: 3, budget: 1300, tone: 'nanjing', categories: ['autumn', 'history', 'photo'] },
  { city: '九寨沟', landmark: '🏔', slogan: '彩林湖泊 · 童话世界', score: '4.9', days: 3, budget: 2200, tone: 'jiuzhai', categories: ['autumn', 'nature', 'photo'] },
  { city: '成都', landmark: '🐼', slogan: '烟火成都 · 巴适慢游', score: '4.8', days: 3, budget: 1600, tone: 'chengdu', categories: ['food'] },
  { city: '西安', landmark: '🏯', slogan: '梦回长安 · 盛唐风华', score: '4.8', days: 3, budget: 1500, tone: 'xian', categories: ['history', 'food', 'photo'] },
]

const features = computed(() => featureDefaults.map((item) => ({
  ...item,
  name: sceneNames.value[item.code] || item.name,
})))

const displayName = computed(() => user.value?.display_name || user.value?.username || '旅行家')
const visibleHotSearches = computed(() => hotSearchGroups[hotBatch.value % hotSearchGroups.length])
const filteredDestinations = computed(() => {
  const matches = destinations.filter((item) => item.categories.includes(selectedDestinationFilter.value))
  return matches.length ? matches : destinations
})

onShow(async () => {
  user.value = currentUser()
  if (!user.value || user.value.role !== 'user') {
    if (user.value) clearAuth()
    uni.reLaunch({ url: '/pages/index/index' })
    return
  }
  userAvatar.value = loadUserAvatar(user.value)
  await Promise.allSettled([loadScenes(), loadRecentPlan()])
})

async function loadScenes() {
  const payload = await request('/api/v1/scenes')
  sceneNames.value = Object.fromEntries((payload.items || []).map((item) => [item.code, item.name]))
}

async function loadRecentPlan() {
  const payload = await request('/api/v1/chat/sessions?scene_code=TRAVEL_PLAN')
  recentPlan.value = (payload.items || [])[0] || null
}

function selectPlannerField(field) {
  uni.showActionSheet({
    itemList: field.options.map((item) => item.label),
    success: ({ tapIndex }) => { plannerSelections[field.key] = field.options[tapIndex] },
  })
}

function submitIdea() {
  const conditions = plannerFields.map((field) => plannerSelections[field.key]?.value).filter(Boolean)
  const freeText = planIdea.value.trim()
  const prompt = [freeText, ...conditions].filter(Boolean).join('，')
  if (!prompt) {
    uni.showToast({ title: '先输入想法或选择旅行条件', icon: 'none' })
    return
  }
  openPrompt('TRAVEL_PLAN', `${prompt}，请帮我制定一份清晰、详细的旅行方案。`)
}

function openFeature(sceneCode) {
  uni.navigateTo({ url: `/pages/chat/chat?scene=${encodeURIComponent(sceneCode)}` })
}

function openPrompt(sceneCode, prompt) {
  uni.navigateTo({
    url: `/pages/chat/chat?scene=${encodeURIComponent(sceneCode)}&prompt=${encodeURIComponent(prompt)}`,
  })
}

function openHotSearch(topic) {
  openPrompt('TRAVEL_PLAN', `请帮我规划${topic}，每天安排清晰，并详细介绍主要景点。`)
}

function changeHotSearches() {
  hotBatch.value = (hotBatch.value + 1) % hotSearchGroups.length
}

function openDestination(destination) {
  openPrompt('TRAVEL_PLAN', `我想去${destination.city}玩${destination.days}天，请规划一份景点介绍详细、交通安排合理的行程。`)
}

function openRecentPlan() {
  if (!recentPlan.value?.session_id) return
  uni.navigateTo({ url: `/pages/chat/chat?scene=TRAVEL_PLAN&session_id=${encodeURIComponent(recentPlan.value.session_id)}` })
}

function openAssistant() {
  openFeature('TRAVEL_PLAN')
}

function openProfile() {
  uni.switchTab({ url: '/pages/profile/profile' })
}
</script>

<style scoped>
.home-page { position: relative; min-height: 100vh; overflow: hidden; padding: calc(env(safe-area-inset-top) + 32rpx) 24rpx 36rpx; background: linear-gradient(180deg, #f7fbff 0, #fff 250rpx, #fbfcfd 100%); }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 20rpx; padding: 12rpx 8rpx 26rpx; }
.head-copy { min-width: 0; padding-right: 140rpx; }
.greeting, .greeting-tip { display: block; }
.greeting { color: #172d48; font-size: 35rpx; font-weight: 800; letter-spacing: .5rpx; }
.greeting-tip { margin-top: 8rpx; color: #8995a7; font-size: 22rpx; }
.avatar { display: flex; width: 66rpx; height: 66rpx; flex-shrink: 0; align-items: center; justify-content: center; border: 4rpx solid #fff; border-radius: 50%; box-shadow: 0 8rpx 20rpx #59708424; font-size: 30rpx; font-weight: 800; }
.avatar-coral { color: #e45b70; background: #fff0f2; }
.avatar-teal { color: #fff; background: linear-gradient(145deg, #55b9a7, #278b7d); }
.avatar-green { background: linear-gradient(145deg, #78b986, #438b5b); }
.avatar-blue { background: linear-gradient(145deg, #70acef, #477fca); }
.avatar-slate { background: linear-gradient(145deg, #7d91aa, #55687d); }
.avatar-amber { background: linear-gradient(145deg, #f3b85e, #dd8b37); }
.avatar-violet { background: linear-gradient(145deg, #a88bd0, #765baa); }
.planner-card { position: relative; overflow: hidden; padding: 30rpx 25rpx 25rpx; border: 2rpx solid #ffd1d5; border-radius: 28rpx; background: linear-gradient(145deg, #fff8f6 0%, #ffe6e7 64%, #ffd8dc 100%); box-shadow: 0 14rpx 34rpx #ef758322; }
.planner-glow { position: absolute; top: 46rpx; right: 245rpx; width: 48rpx; height: 48rpx; border-radius: 50%; background: #ffd5cf; opacity: .8; }
.mountain { position: absolute; right: -55rpx; bottom: 50rpx; width: 210rpx; height: 210rpx; transform: rotate(45deg); border-radius: 36rpx 24rpx 30rpx; }
.mountain-back { right: 82rpx; bottom: 20rpx; background: linear-gradient(135deg, #ffd5d9, #f5a7b6); opacity: .68; }
.mountain-front { right: -55rpx; bottom: -5rpx; background: linear-gradient(135deg, #f7bdc6, #ed899e); opacity: .68; }
.planner-copy, .planner-fields, .planner-input-wrap { position: relative; z-index: 1; }
.planner-title, .planner-subtitle { display: block; }
.planner-title { color: #17314d; font-size: 37rpx; font-weight: 850; }
.planner-subtitle { margin-top: 8rpx; color: #53657a; font-size: 22rpx; }
.planner-fields { width: 100%; margin-top: 22rpx; white-space: nowrap; }
.planner-field-row { display: inline-flex; gap: 10rpx; }
.planner-field { display: flex; height: 49rpx; align-items: center; gap: 7rpx; padding: 0 14rpx; border: 1rpx solid #fff; border-radius: 25rpx; color: #69778a; background: #ffffffdc; font-size: 20rpx; }
.planner-field.selected { border-color: #f3a3ad; color: #d95e71; background: #fff; font-weight: 700; }
.planner-field-icon { color: #ef7482; }
.planner-input-wrap { display: flex; height: 86rpx; align-items: center; margin-top: 19rpx; padding: 8rpx 10rpx 8rpx 20rpx; border-radius: 43rpx; background: #fff; box-shadow: 0 10rpx 24rpx #d9788620; }
.planner-input { min-width: 0; height: 68rpx; flex: 1; color: #33485f; font-size: 24rpx; }
.planner-placeholder { color: #aeb4c0; font-size: 22rpx; }
.send-plan { display: flex; width: 66rpx; height: 66rpx; flex-shrink: 0; align-items: center; justify-content: center; border-radius: 50%; color: #fff; background: linear-gradient(145deg, #ff7580, #ec536c); box-shadow: 0 8rpx 18rpx #ed5d7445; font-size: 27rpx; transform: rotate(-9deg); }
.send-plan-active, .card-active, .assistant-dock-active { opacity: .76; transform: scale(.98); }
.hot-strip { display: flex; height: 64rpx; align-items: center; gap: 12rpx; margin-top: 13rpx; padding: 0 14rpx; border: 1rpx solid #edf0f4; border-radius: 18rpx; background: #fff; box-shadow: 0 8rpx 20rpx #43556f0a; }
.hot-label { display: flex; flex-shrink: 0; align-items: center; gap: 6rpx; color: #27384f; font-size: 20rpx; font-weight: 750; }
.hot-scroll { min-width: 0; flex: 1; white-space: nowrap; }
.hot-items { display: inline-flex; gap: 10rpx; }
.hot-items text { padding: 7rpx 13rpx; border-radius: 18rpx; color: #334f75; background: #f2f6ff; font-size: 19rpx; }
.change-hot { display: flex; flex-shrink: 0; align-items: center; gap: 5rpx; color: #68778a; font-size: 19rpx; }
.section { margin-top: 34rpx; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; padding: 0 4rpx; }
.compact-head { min-height: 45rpx; }
.section-title-row { display: flex; min-width: 0; align-items: baseline; gap: 11rpx; }
.section-title { color: #1c304b; font-size: 29rpx; font-weight: 850; white-space: nowrap; }
.section-symbol { color: #6f86ed; font-size: 28rpx; }
.section-symbol.coral { color: #ef7281; }
.section-symbol.suitcase { color: #8c6544; font-size: 22rpx; }
.section-note { overflow: hidden; color: #9aa3b0; font-size: 19rpx; text-overflow: ellipsis; white-space: nowrap; }
.section-link { flex-shrink: 0; color: #84909f; font-size: 20rpx; }
.service-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14rpx; margin-top: 19rpx; }
.service-card { position: relative; display: flex; min-height: 148rpx; align-items: center; padding: 19rpx 16rpx; overflow: hidden; border: 1rpx solid; border-radius: 20rpx; transition: opacity .15s ease, transform .15s ease; }
.service-coral { border-color: #f8dadd; background: linear-gradient(145deg, #fff7f7, #fffafa); }
.service-teal { border-color: #cfeae4; background: linear-gradient(145deg, #f1fbf8, #f9fffd); }
.service-blue { border-color: #d5e3fb; background: linear-gradient(145deg, #f3f7ff, #fbfdff); }
.service-amber { border-color: #f4e1c0; background: linear-gradient(145deg, #fff9ef, #fffdfa); }
.service-icon { display: flex; width: 58rpx; height: 58rpx; flex-shrink: 0; align-items: center; justify-content: center; border-radius: 17rpx; color: #fff; box-shadow: 0 9rpx 18rpx #576a7d20; font-size: 24rpx; font-weight: 900; }
.service-icon-coral { background: linear-gradient(145deg, #ff8e94, #eb5a6b); }
.service-icon-teal { background: linear-gradient(145deg, #6ad1b9, #2ba88e); }
.service-icon-blue { background: linear-gradient(145deg, #75b3ff, #4a7ee1); }
.service-icon-amber { background: linear-gradient(145deg, #ffc65e, #f09b2c); }
.service-copy { min-width: 0; margin-left: 13rpx; }
.service-name, .service-description { display: block; }
.service-name { color: #294056; font-size: 24rpx; font-weight: 800; }
.service-coral .service-name { color: #d64e60; }
.service-teal .service-name { color: #187b69; }
.service-blue .service-name { color: #2866c1; }
.service-amber .service-name { color: #d1801d; }
.service-description { margin-top: 5rpx; overflow: hidden; color: #768495; font-size: 18rpx; text-overflow: ellipsis; white-space: nowrap; }
.service-tags { display: flex; gap: 5rpx; margin-top: 9rpx; overflow: hidden; white-space: nowrap; }
.service-tags text { padding: 4rpx 7rpx; border-radius: 8rpx; color: #8594a0; background: #ffffffa8; font-size: 15rpx; }
.service-arrow { position: absolute; top: 50%; right: 10rpx; display: flex; width: 33rpx; height: 33rpx; align-items: center; justify-content: center; margin-top: -17rpx; border-radius: 50%; color: #91a0ad; background: #fff; font-size: 26rpx; }
.filter-scroll, .destination-scroll { width: calc(100% + 48rpx); margin-left: -24rpx; white-space: nowrap; }
.filter-row { display: inline-flex; gap: 9rpx; padding: 16rpx 24rpx 11rpx; }
.filter-chip { padding: 9rpx 15rpx; border-radius: 20rpx; color: #6e7b8e; background: #f2f4f7; font-size: 19rpx; }
.filter-chip.active { color: #e55d70; background: #fff0f2; font-weight: 700; }
.destination-row { display: inline-flex; gap: 14rpx; padding: 3rpx 24rpx 13rpx; }
.destination-card { position: relative; width: 255rpx; height: 230rpx; overflow: hidden; border-radius: 20rpx; color: #fff; box-shadow: 0 12rpx 24rpx #38485920; transition: opacity .15s ease, transform .15s ease; }
.destination-beijing { background: linear-gradient(160deg, #e6aa68 0%, #ac583d 58%, #49352f 100%); }
.destination-hangzhou { background: linear-gradient(160deg, #8bc9cb 0%, #4f9291 50%, #315f64 100%); }
.destination-nanjing { background: linear-gradient(160deg, #dfb46b 0%, #a16a41 55%, #533b33 100%); }
.destination-jiuzhai { background: linear-gradient(160deg, #83b9d1 0%, #527f93 51%, #304a57 100%); }
.destination-chengdu { background: linear-gradient(160deg, #88b58e 0%, #4d7958 55%, #304c3c 100%); }
.destination-xian { background: linear-gradient(160deg, #d1966d 0%, #915946 55%, #513933 100%); }
.destination-sun { position: absolute; top: 22rpx; right: 24rpx; width: 38rpx; height: 38rpx; border-radius: 50%; background: #ffe6a0; box-shadow: 0 0 30rpx #ffecb3; opacity: .72; }
.destination-landmark { position: absolute; right: 20rpx; bottom: 54rpx; font-size: 92rpx; opacity: .64; filter: grayscale(.3); }
.destination-overlay { position: absolute; right: 0; bottom: 0; left: 0; padding: 55rpx 15rpx 14rpx; background: linear-gradient(180deg, transparent, #152329e8); }
.destination-city, .destination-slogan { display: block; }
.destination-city { font-size: 29rpx; font-weight: 850; }
.destination-slogan { margin-top: 3rpx; overflow: hidden; font-size: 18rpx; opacity: .88; text-overflow: ellipsis; white-space: nowrap; }
.destination-meta { display: flex; gap: 9rpx; margin-top: 9rpx; font-size: 16rpx; opacity: .9; }
.recent-card { display: flex; align-items: center; gap: 13rpx; margin-top: 15rpx; padding: 13rpx; border: 1rpx solid #e5eaee; border-radius: 18rpx; background: #fff; box-shadow: 0 8rpx 22rpx #42556a0b; transition: opacity .15s ease, transform .15s ease; }
.recent-visual { display: flex; width: 78rpx; height: 70rpx; flex-shrink: 0; align-items: center; justify-content: center; border-radius: 14rpx; color: #fff; background: linear-gradient(145deg, #68aea6, #367b77); font-size: 27rpx; font-weight: 900; }
.recent-copy { min-width: 0; flex: 1; }
.recent-title, .recent-note { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.recent-title { color: #33475b; font-size: 22rpx; font-weight: 800; }
.recent-note { margin-top: 5rpx; color: #929da9; font-size: 17rpx; }
.recent-progress { height: 5rpx; margin-top: 10rpx; overflow: hidden; border-radius: 4rpx; background: #e7edf0; }
.recent-progress view { height: 100%; border-radius: 4rpx; background: linear-gradient(90deg, #66b2a7, #41a78e); }
.recent-action { flex-shrink: 0; padding: 9rpx 14rpx; border-radius: 18rpx; color: #ec6879; background: #fff1f3; font-size: 18rpx; font-weight: 700; }
.safe-bottom { height: 116rpx; }
.assistant-dock { position: fixed; z-index: 30; right: 50%; bottom: 18rpx; display: flex; width: 172rpx; height: 62rpx; align-items: center; justify-content: center; gap: 9rpx; margin-right: -86rpx; border: 5rpx solid #fff; border-radius: 35rpx; color: #247368; background: linear-gradient(110deg, #faf4ff, #e6fbf5); box-shadow: 0 7rpx 25rpx #344b5d29; font-size: 21rpx; font-weight: 800; transition: opacity .15s ease, transform .15s ease; }
.assistant-face { display: flex; width: 37rpx; height: 37rpx; align-items: center; justify-content: center; border-radius: 50%; background: #fff; font-size: 21rpx; }
</style>
