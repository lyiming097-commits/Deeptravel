<template>
  <view class="chat-page">
    <view class="topbar">
      <view>
        <text class="eyebrow">DEEPTRAVEL</text>
        <text class="page-title">{{ selectedScene?.name || '旅行顾问' }}</text>
      </view>
      <view class="top-actions">
        <text class="session-button" @tap="showSessions = true">会话</text>
        <text class="new-button" @tap="newConversation">＋</text>
      </view>
    </view>

    <scroll-view class="scene-scroll" scroll-x :show-scrollbar="false">
      <view class="scene-row">
        <view
          v-for="scene in scenes"
          :key="scene.code"
          :class="['scene-chip', { active: selectedSceneCode === scene.code }]"
          @tap="selectScene(scene.code)"
        >
          <text>{{ scene.name }}</text>
        </view>
      </view>
    </scroll-view>

    <scroll-view
      class="message-scroll"
      scroll-y
      :scroll-into-view="scrollIntoView"
      :lower-threshold="80"
    >
      <view v-if="!messages.length" class="empty-chat">
        <view class="advisor-avatar">
          <text class="advisor-person">🧑🏻‍💼</text>
          <view class="assistant-charm">✦</view>
        </view>
        <text class="empty-title">{{ selectedScene?.name || '旅行顾问' }}</text>
        <text class="empty-description">{{ selectedScene?.welcome_message || '告诉我你想去哪里，我们一起把旅程聊清楚。' }}</text>
      </view>

      <view v-for="(item, index) in messages" :id="`message-${index}`" :key="item.localId || index" :class="['message-row', item.role]">
        <view v-if="item.role === 'assistant'" class="avatar assistant-avatar">
          <text class="assistant-person">🧑🏻‍💼</text>
          <view class="assistant-charm">✦</view>
        </view>
        <view class="message-body">
          <view v-if="item.content" :class="['bubble', { progress: item.progressOnly }]">
            <template
              v-for="(block, blockIndex) in messageBlocks(item.content)"
              :key="`${item.localId || index}-block-${blockIndex}`"
            >
              <view :class="['content-line', `content-${block.type}`]">
                <text v-if="block.type !== 'blank'">{{ block.text }}</text>
              </view>
              <!-- Place a photo immediately after the answer block that
                   names the attraction. Unmatched POIs remain in the
                   structured section below instead of being guessed into a
                   random paragraph. -->
              <view
                v-for="poi in inlinePois(item, blockIndex)"
                :key="`${item.localId || index}-inline-${poi.name}`"
                class="poi-inline-media"
              >
                <text class="poi-inline-label">{{ poiDisplayName(poi) }} 图片</text>
                <scroll-view class="poi-images" scroll-x :show-scrollbar="false">
                  <image
                    v-for="image in poiImages(poi)"
                    :key="image"
                    class="poi-image"
                    :src="imageSource(image)"
                    mode="aspectFill"
                    :show-menu-by-longpress="true"
                    @tap.stop="previewPoiImage(poi, image)"
                    @error="handleImageError(image)"
                  />
                </scroll-view>
              </view>
            </template>
          </view>
          <text v-if="item.streaming && !item.content" class="typing">正在思考…</text>

          <view v-if="item.result" class="structured-content">
            <view v-if="remainingPois(item).length" class="poi-list">
              <view v-for="poi in remainingPois(item)" :key="`${poiDisplayName(poi)}-${poi.location || ''}`" class="poi-entry">
                <view class="poi-card">
                  <view class="poi-heading">
                    <text class="poi-name">{{ poiDisplayName(poi) }}</text>
                    <text v-if="poi.day" class="poi-day">第 {{ poi.day }} 天</text>
                  </view>
                  <view v-if="poiDescription(poi)" class="poi-intro">
                    <text class="poi-intro-label">景点介绍</text>
                    <text class="poi-description">{{ poiDescription(poi) }}</text>
                  </view>
                </view>
                <view v-if="poiImages(poi).length" class="poi-photo-card">
                  <text class="poi-photo-label">{{ poiDisplayName(poi) }} 图片</text>
                  <scroll-view class="poi-images" scroll-x :show-scrollbar="false">
                  <image
                    v-for="image in poiImages(poi)"
                    :key="image"
                    class="poi-image"
                    :src="imageSource(image)"
                    mode="aspectFill"
                    :show-menu-by-longpress="true"
                    @tap.stop="previewPoiImage(poi, image)"
                    @error="handleImageError(image)"
                  />
                  </scroll-view>
                </view>
              </view>
            </view>

            <view v-if="mapInfo(item)" class="map-card">
              <view class="map-title-row">
                <view class="map-title-copy">
                  <text class="map-title">{{ isPoiMap(item) ? '景点地图' : '行程地图' }}</text>
                  <text class="map-caption">{{ isPoiMap(item) ? '仅标注景点位置' : '根据已核验坐标展示' }}</text>
                </view>
                <view class="map-open" hover-class="map-open-active" @tap.stop="openMapDetail(item)">
                  <text>查看大图</text>
                  <text class="map-open-arrow">›</text>
                </view>
              </view>
              <map
                class="map"
                style="width: 100%; height: 330px;"
                :latitude="mapInfo(item).latitude"
                :longitude="mapInfo(item).longitude"
                :scale="mapInfo(item).scale"
                :markers="mapInfo(item).markers"
                :polyline="mapInfo(item).polyline"
                :enable-scroll="true"
                :enable-zoom="true"
                :enable-rotate="true"
                :show-compass="true"
                :show-scale="true"
              />
              <view class="map-place-list">
                <text v-for="(point, pointIndex) in mapInfo(item).points" :key="point.name + point.location">
                  <i>{{ pointIndex + 1 }}</i>{{ poiDisplayName(point) }}
                </text>
              </view>
            </view>

            <view v-if="item.citations?.length" class="citation-box">
              <text class="citation-title">参考信息</text>
              <text v-for="(citation, citationIndex) in item.citations.slice(0, 5)" :key="citation.chunk_id || citation.title || citationIndex" class="citation-item">
                {{ citationIndex + 1 }}. {{ citation.title || '旅行资料' }}
              </text>
            </view>
          </view>
        </view>
        <view v-if="item.role === 'user'" :class="['avatar', 'user-avatar', `avatar-${userAvatar.tone}`]">{{ userAvatar.symbol }}</view>
      </view>
      <view id="message-bottom" class="message-bottom" />
    </scroll-view>

    <view class="composer">
      <text class="composer-tip">{{ loading ? '顾问正在回复…' : '说说你的旅行想法' }}</text>
      <view class="composer-row">
        <textarea
          v-model="draft"
          class="composer-input"
          :disabled="loading"
          :maxlength="2000"
          :auto-height="true"
          cursor-spacing="20"
          confirm-type="send"
          placeholder="例如：想去杭州玩两天，喜欢历史和自然风景"
          placeholder-class="input-placeholder"
          @confirm="submit"
        />
        <button class="send-button" :disabled="loading || !draft.trim()" @tap="submit">发送</button>
      </view>
    </view>

    <view v-if="showSessions" class="sheet-mask" @tap.self="showSessions = false">
      <view class="session-sheet">
        <view class="sheet-head">
          <text class="sheet-title">{{ selectedScene?.name || '当前功能' }}会话</text>
          <text class="sheet-close" @tap="showSessions = false">关闭</text>
        </view>
        <scroll-view class="session-list" scroll-y>
          <view v-for="item in sessions" :key="item.session_id" :class="['session-item', { current: item.session_id === sessionId }]" @tap="openSession(item)">
            <text class="session-title">{{ item.title || '新会话' }}</text>
            <text class="session-preview">{{ item.preview || '尚未发送消息' }}</text>
            <text class="session-date">{{ formatDate(item.updated_at || item.created_at) }}</text>
          </view>
          <view v-if="!sessions.length" class="no-sessions">发送第一句话后，会话会保存在这里。</view>
        </scroll-view>
        <button class="sheet-new" @tap="newConversation">开始新会话</button>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { clearAuth, currentUser, request, streamMessage } from '../../utils/api'
import { API_BASE_URL } from '../../utils/config'
import { loadUserAvatar } from '../../utils/avatar'

const scenes = ref([])
const selectedSceneCode = ref('TRAVEL_PLAN')
const messages = ref([])
const sessions = ref([])
const sessionId = ref('')
const draft = ref('')
const loading = ref(false)
const error = ref('')
const showSessions = ref(false)
const scrollIntoView = ref('message-bottom')
const user = ref(currentUser())
const userAvatar = ref(loadUserAvatar(user.value))
const pendingPrompt = ref('')
const pendingPromptSubmitted = ref(false)
const pendingSessionId = ref('')
// Real devices may reject an HTTP/IP image URL even when the same backend
// endpoint is reachable through ``uni.request``. Cache successfully fetched
// bytes as local files and use those paths for the image component.
const localImageUrls = ref({})
const imageFetches = new Set()
const imageQueue = []
let activeImageFetches = 0
const MAX_IMAGE_FETCHES = 4

const selectedScene = computed(() => scenes.value.find((item) => item.code === selectedSceneCode.value))

onLoad((options) => {
  if (options?.scene) selectedSceneCode.value = options.scene
  if (options?.session_id) pendingSessionId.value = options.session_id
  if (options?.prompt) {
    try {
      pendingPrompt.value = decodeURIComponent(options.prompt)
    } catch {
      pendingPrompt.value = options.prompt
    }
  }
})

onShow(async () => {
  user.value = currentUser()
  if (!user.value || user.value.role !== 'user') {
    if (user.value) clearAuth()
    uni.reLaunch({ url: '/pages/index/index' })
    return
  }
  userAvatar.value = loadUserAvatar(user.value)
  if (!scenes.value.length) await loadScenes()
  await loadSessions()
  if (pendingSessionId.value) {
    const targetSessionId = pendingSessionId.value
    pendingSessionId.value = ''
    await openSession({ session_id: targetSessionId })
  } else if (!messages.value.length) showWelcome()
  if (pendingPrompt.value && !pendingPromptSubmitted.value) {
    pendingPromptSubmitted.value = true
    draft.value = pendingPrompt.value
    await nextTick()
    await submit()
  }
})

onMounted(() => {
  // Keep the native navigation title synchronized when the user changes the
  // specialist tab inside the chat page.
  uni.setNavigationBarTitle({ title: selectedScene.value?.name || '旅行顾问' })
})

async function loadScenes() {
  try {
    const payload = await request('/api/v1/scenes')
    scenes.value = payload.items || []
    if (!scenes.value.some((item) => item.code === selectedSceneCode.value)) {
      selectedSceneCode.value = scenes.value[0]?.code || 'TRAVEL_PLAN'
    }
    uni.setNavigationBarTitle({ title: selectedScene.value?.name || '旅行顾问' })
  } catch (err) {
    error.value = err.message || '功能列表加载失败'
  }
}

async function loadSessions() {
  try {
    const payload = await request(`/api/v1/chat/sessions?scene_code=${encodeURIComponent(selectedSceneCode.value)}`)
    sessions.value = payload.items || []
  } catch (err) {
    if (/登录|401|失效/.test(err.message || '')) return signOut()
    error.value = err.message || '会话加载失败'
  }
}

function showWelcome() {
  const welcome = selectedScene.value?.welcome_message
  messages.value = welcome ? [{ localId: `welcome-${selectedSceneCode.value}`, role: 'assistant', content: welcome }] : []
  scrollToBottom()
}

async function selectScene(code) {
  if (loading.value || code === selectedSceneCode.value) return
  selectedSceneCode.value = code
  sessionId.value = ''
  messages.value = []
  error.value = ''
  showSessions.value = false
  uni.setNavigationBarTitle({ title: selectedScene.value?.name || '旅行顾问' })
  await loadSessions()
  showWelcome()
}

function newConversation() {
  if (loading.value) return
  sessionId.value = ''
  messages.value = []
  draft.value = ''
  error.value = ''
  showSessions.value = false
  showWelcome()
}

function normalizeMessage(row) {
  const metadata = row.metadata || {}
  return {
    localId: `saved-${row.id || Math.random()}`,
    role: row.role,
    content: row.content || '',
    result: metadata.result || null,
    citations: metadata.citations || [],
  }
}

async function openSession(item) {
  if (loading.value) return
  try {
    const payload = await request(`/api/v1/chat/sessions/${item.session_id}`)
    sessionId.value = payload.session_id
    messages.value = (payload.messages || []).map(normalizeMessage)
    messages.value.forEach(prefetchImagesForDevice)
    showSessions.value = false
    scrollToBottom()
  } catch (err) {
    error.value = err.message || '会话打开失败'
  }
}

async function ensureSession() {
  if (sessionId.value) return sessionId.value
  const payload = await request(`/api/v1/chat/sessions?scene_code=${encodeURIComponent(selectedSceneCode.value)}`, { method: 'POST' })
  sessionId.value = payload.session_id
  await loadSessions()
  return sessionId.value
}

async function submit() {
  const content = draft.value.trim()
  if (!content || loading.value) return
  error.value = ''
  draft.value = ''
  messages.value.push({ localId: `user-${Date.now()}`, role: 'user', content })
  const assistant = { localId: `assistant-${Date.now()}`, role: 'assistant', content: '', citations: [], streaming: true, progressOnly: false }
  messages.value.push(assistant)
  const assistantIndex = messages.value.length - 1
  loading.value = true
  scrollToBottom()
  try {
    const id = await ensureSession()
    await streamMessage(id, { scene_code: selectedSceneCode.value, message: content, parameters: {} }, (eventName, payload) => {
      const item = messages.value[assistantIndex]
      if (!item) return
      if (eventName === 'progress') {
        const fact = payload.message || ''
        if (fact && !item.content) item.content = fact
        else if (fact) item.content += `\n${fact}`
        item.progressOnly = true
      } else if (eventName === 'token') {
        if (item.progressOnly) item.content = ''
        item.progressOnly = false
        item.content += payload.token || ''
      } else if (eventName === 'done') {
        item.streaming = false
        item.progressOnly = false
        item.result = payload.result || null
        item.citations = payload.citations || []
        // Streaming tokens are emitted before the server applies its final
        // link/Markdown cleanup.  Replace the provisional buffer with the
        // authoritative answer so headings, lists and spacing are consistent
        // with saved messages after the stream finishes.
        if (payload.answer) item.content = payload.answer
        prefetchImagesForDevice(item)
      } else if (eventName === 'error') {
        throw new Error(payload.detail || '对话处理失败')
      }
      scrollToBottom()
    })
    // Some real-device WeChat runtimes finish an SSE request before the
    // larger ``done`` frame (which contains POI photos and map data) has been
    // applied to the reactive page state.  The server has already persisted
    // the complete exchange by this point, so read the session once and use
    // its latest assistant message as a safe cross-platform fallback.
    try {
      const savedSession = await request(`/api/v1/chat/sessions/${id}`)
      const savedAssistant = [...(savedSession.messages || [])]
        .reverse()
        .find((message) => message.role === 'assistant')
      if (savedAssistant) {
        const normalized = normalizeMessage(savedAssistant)
        const item = messages.value[assistantIndex]
        if (item) {
          if (normalized.content) item.content = normalized.content
          if (normalized.result) item.result = normalized.result
          if (normalized.citations?.length) item.citations = normalized.citations
          prefetchImagesForDevice(item)
        }
      }
    } catch {
      // The streamed answer is still usable when the optional sync request
      // is unavailable; do not turn a successful response into an error.
    }
    messages.value[assistantIndex].streaming = false
    if (!messages.value[assistantIndex].content) messages.value[assistantIndex].content = '暂时没有生成回答，请再试一次。'
    await loadSessions()
  } catch (err) {
    messages.value.splice(assistantIndex, 1)
    error.value = err.message || '发送失败，请检查网络连接'
    uni.showToast({ title: error.value.slice(0, 18), icon: 'none' })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function signOut() {
  clearAuth()
  uni.reLaunch({ url: '/pages/index/index' })
}

function scrollToBottom() {
  nextTick(() => {
    scrollIntoView.value = ''
    setTimeout(() => { scrollIntoView.value = 'message-bottom' }, 20)
  })
}

function messagePois(item) {
  const pois = item?.result?.pois
  // Keep the UI defensive for old sessions created before the backend
  // filtering rules were tightened.  Route/product records are not
  // attractions and should never appear as cards or map markers, even when a
  // cached response still contains them.
  const attractionResult = isAttractionResult(item)
  return Array.isArray(pois)
    ? pois.filter((poi) => (
      poi
      && String(poi.name || '').trim()
      && isPlausiblePoi(poi)
      && (!isItineraryResult(item) || isScenicPoi(poi))
      // Do not render a blank attraction card. The verified point can still
      // appear on the map; a card is useful only when it has an introduction
      // or a matched image. This prevents ordinary long-tail POIs from
      // flooding the answer with name-only boxes.
      && (!attractionResult || Boolean(poiDescription(poi) || poiImages(poi).length))
    ))
    : []
}

const NON_SCENIC_POI_TERMS = [
  '环线', '环湖线', '游览线', '游线', '线路', '路线', '步行线路', '观光线路',
  '夜游', '灯光秀', '灯光演出', '演出', '演艺', '活动', '套餐', '项目',
  '观光车', '接驳车', '游船', '打卡点', '打卡线路', '体验项目',
  '一日游', '两日游', '半日游', '跟团游', '自由行', '旅拍',
]

const DESCRIPTIVE_POI_PREFIX = /^(从(?!化|江)|由|到|前往|位于|坐落|紧邻|毗邻|邻近|靠近|周边|附近|这里|方便|推荐|适合|可以)/
const DESCRIPTIVE_POI_ENDING = /(历史|文化|山色|山水|风光|特色|选择|推荐|体验)$/

function isItineraryResult(item) {
  const data = item?.result
  return Boolean(data && (data.intent === 'itinerary' || data.travel_intent === 'itinerary'))
}

function isAttractionResult(item) {
  const data = item?.result
  if (!data) return false
  return Boolean(
    data.query_type === 'poi_discovery'
    || data.intent === 'attraction'
    || data.travel_intent === 'attraction'
    || isItineraryResult(item),
  )
}

function isScenicPoi(poi) {
  const name = String(poi?.name || '').trim()
  return isPlausiblePoi(poi) && !NON_SCENIC_POI_TERMS.some((term) => name.includes(term))
}

function isPlausiblePoi(poi) {
  const name = String(poi?.name || '').trim()
  return Boolean(name)
    && !DESCRIPTIVE_POI_PREFIX.test(name)
    && !DESCRIPTIVE_POI_ENDING.test(name)
}

function poiDisplayName(poi) {
  const raw = String(poi?.display_name || poi?.name || '').replace(/\s+/g, ' ').trim()
  if (!raw) return ''
  const city = String(poi?.city || '').trim().replace(/市$/, '')
  let value = city && raw.startsWith(city) && raw.length > city.length + 1
    ? raw.slice(city.length).trim()
    : raw
  // Provider records may contain internal points and marketing suffixes. Use
  // the parent scenic name for display while retaining the original `name`
  // for matching, citations and provider calls.
  if (/[（(]/.test(value)) {
    value = value.replace(/[（(][^）)]*(?:打卡|游船|路线|线路|推荐|营销|内部|入口|观光)[^）)]*[）)]/g, '')
  }
  const genericPrefix = value.match(/^(?:景点|景区|公园|湿地公园|国家公园|主题乐园|古镇|博物馆|历史文化|自然风光|湖光山色)[·：:]\s*(.+)$/)
  if (genericPrefix) value = genericPrefix[1].trim()
  const parts = value.split(/\s*[-—–]\s*/)
  if (parts.length > 1 && parts[0].length >= 2 && /(?:打卡|游船|观光|路线|线路|环线|夜游)/.test(parts.slice(1).join(''))) {
    value = parts[0]
  }
  return value.replace(/^[\s，,。；;、]+|[\s，,。；;、]+$/g, '') || raw
}

function poiDescription(poi) {
  if (!poi || typeof poi !== 'object') return ''
  const direct = [poi.description, poi.introduction, poi.intro, poi.summary, poi.content]
    .find((value) => typeof value === 'string' && value.trim())
  if (!direct) return ''
  const value = direct.trim()
  // Do not label navigation/schedule text as an attraction introduction.
  if (/路线|交通方式|起点|终点|导航|换乘|公交|地铁|驾车|打车|乘坐|车站|站点|公里|分钟|耗时|直达/.test(value)) return ''
  if (/已找到该景点，可在地图中查看位置|暂无详细介绍/.test(value)) return ''
  return value
}

function messageBlocks(content) {
  const text = String(content || '').replace(/\r\n?/g, '\n')
  const blocks = []
  let previous = ''
  for (const raw of text.split('\n')) {
    const line = raw.replace(/[ \t]{2,}/g, ' ').trim()
    if (!line) {
      if (blocks.length && previous !== 'blank') blocks.push({ type: 'blank', text: '' })
      previous = 'blank'
      continue
    }
    let value = line
    let type = 'paragraph'
    const heading = value.match(/^#{1,6}\s+(.+)$/)
    const day = value.match(/^第\s*\d+\s*天(?:\s*[：:].*)?$/)
    const bullet = value.match(/^[-*•]\s+(.+)$/)
    const ordered = value.match(/^(\d+)[.)、]\s*(.+)$/)
    if (heading) {
      value = heading[1]
      type = 'heading'
    } else if (day) {
      type = 'heading'
    } else if (bullet) {
      value = `• ${bullet[1]}`
      type = 'list'
    } else if (ordered) {
      value = `${ordered[1]}. ${ordered[2]}`
      type = 'list'
    }
    value = value
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/__(.+?)__/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
    blocks.push({ type, text: value })
    previous = type
  }
  while (blocks.length && blocks[blocks.length - 1].type === 'blank') blocks.pop()
  return blocks.length ? blocks : [{ type: 'paragraph', text: '' }]
}

function poiNames(poi) {
  if (!poi || typeof poi !== 'object') return []
  const values = [poi.name, poi.alias]
    .flatMap((value) => String(value || '').split(/[，,、/|]/))
    .map((value) => value.trim())
    .filter((value) => value.length >= 2)
  return [...new Set(values)].sort((left, right) => right.length - left.length)
}

function poiPlacementIndex(item) {
  const blocks = messageBlocks(item?.content)
  const pois = messagePois(item)
  const placements = new Map()
  pois.forEach((poi) => {
    const names = poiNames(poi)
    if (!names.length || !poiImages(poi).length) return
    let bestIndex = -1
    let bestScore = -1
    blocks.forEach((block, index) => {
      const line = String(block.text || '').trim()
      if (!line || block.type === 'blank') return
      const matches = pois.filter((candidate) => {
        const aliases = poiNames(candidate)
        return aliases.some((alias) => alias && line.includes(alias))
      })
      // A day heading containing several attractions is not specific enough
      // to decide where an image belongs.  Wait for each attraction's own
      // descriptive line instead.
      if (matches.length !== 1) return
      if (!names.some((name) => line.includes(name))) return
      const remainder = names.reduce((value, name) => value.replace(name, ''), line)
      let score = remainder.trim().length >= 10 ? 100 : 20
      if (/[：:]/.test(line)) score += 10
      if (/(特色|闻名|始建|历史|适合|位于|景观|建筑|文化|湖光|山水|参观|游览|开放)/.test(line)) score += 15
      // A heading such as “西湖” is followed by its prose in the next block.
      // Place the image after that continuation paragraph, rather than
      // between the heading and the introduction. Stop at another heading or
      // another named POI so one attraction cannot inherit its neighbour's
      // paragraph.
      if (remainder.trim().length < 10 && blocks[index + 1]) {
        for (let nextIndex = index + 1; nextIndex < blocks.length; nextIndex += 1) {
          const next = blocks[nextIndex]
          const nextText = String(next.text || '').trim()
          if (!nextText || next.type === 'heading' || next.type === 'blank') break
          const nextMatches = pois.filter((candidate) => poiNames(candidate).some((alias) => alias && nextText.includes(alias)))
          if (nextMatches.length) break
          if (nextText.length >= 10 && !/(路线|交通方式|起点|终点|导航|换乘|公交|地铁|驾车|打车|乘坐|公里|分钟|耗时|直达)/.test(nextText)) {
            bestIndex = nextIndex
            score = 125
          }
          break
        }
      }
      if (score > bestScore) {
        bestScore = score
        bestIndex = index
      }
    })
    if (bestIndex >= 0) placements.set(String(poi.name), bestIndex)
  })
  return placements
}

function inlinePois(item, blockIndex) {
  if (!item?.content || item.progressOnly) return []
  const placements = poiPlacementIndex(item)
  return messagePois(item).filter((poi) => placements.get(String(poi.name)) === blockIndex)
}

function remainingPois(item) {
  const placements = poiPlacementIndex(item)
  return messagePois(item).filter((poi) => !placements.has(String(poi.name)))
}

function poiImages(poi) {
  const values = []
  const add = (value) => {
    if (typeof value === 'string' && /^https?:\/\//i.test(value) && !values.includes(value)) values.push(value)
    else if (Array.isArray(value)) value.forEach(add)
    else if (value && typeof value === 'object') ['large_url', 'original_url', 'url', 'image_url', 'photo_url', 'thumbnail', 'src'].forEach((key) => add(value[key]))
  }
  add(poi?.photos)
  add(poi?.photo)
  return values.slice(0, 2)
}

function imageUrl(url) {
  if (!url) return ''
  return `${API_BASE_URL}/api/v1/media/amap-image?url=${encodeURIComponent(url)}`
}

function imageSource(url) {
  return localImageUrls.value[url] || imageUrl(url)
}

function previewPoiImage(poi, currentImage) {
  const urls = poiImages(poi).map(imageSource).filter(Boolean)
  if (!urls.length) return
  const current = imageSource(currentImage)
  uni.previewImage({
    current: urls.includes(current) ? current : urls[0],
    urls,
    indicator: 'default',
    loop: true,
  })
}

function prefetchImagesForDevice(item) {
  // Do not gate this by ``getSystemInfoSync().platform``.  Some WeChat
  // foundation versions report ``devtools`` even during a real-device
  // preview, and lazy image loading may never emit an error event there.
  // Prefetching through our same-origin proxy is safe on every platform and
  // gives the native image component a local file path on real devices.
  const pois = messagePois(item)
  // Queue the first photo for every POI before queueing optional second
  // photos. This makes the images corresponding to the visible answer appear
  // promptly instead of spending all connections on one POI's gallery.
  for (let photoIndex = 0; photoIndex < 2; photoIndex += 1) {
    for (const poi of pois) {
      const image = poiImages(poi)[photoIndex]
      if (image) handleImageError(image)
    }
  }
}

function imageFileKey(url) {
  let hash = 2166136261
  for (const character of String(url || '')) {
    hash ^= character.charCodeAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return Math.abs(hash >>> 0).toString(36)
}

function imageExtension(response) {
  const header = response?.header || response?.headers || {}
  const contentType = String(header['content-type'] || header['Content-Type'] || '').toLowerCase()
  if (contentType.includes('png')) return 'png'
  if (contentType.includes('webp')) return 'webp'
  if (contentType.includes('gif')) return 'gif'
  return 'jpg'
}

function cacheImageFile(url, response) {
  const wxApi = typeof wx !== 'undefined' ? wx : null
  const fileManager = wxApi?.getFileSystemManager?.()
  const userDataPath = wxApi?.env?.USER_DATA_PATH
  if (!fileManager || !userDataPath || !response?.data) return
  const filePath = `${userDataPath}/deeptravel-${imageFileKey(url)}.${imageExtension(response)}`
  fileManager.writeFile({
    filePath,
    data: response.data,
    success: () => {
      localImageUrls.value = { ...localImageUrls.value, [url]: filePath }
    },
  })
}

function handleImageError(url) {
  if (!url || localImageUrls.value[url] || imageFetches.has(url)) return
  imageFetches.add(url)
  imageQueue.push(url)
  pumpImageFetches()
}

function pumpImageFetches() {
  while (activeImageFetches < MAX_IMAGE_FETCHES && imageQueue.length) {
    const url = imageQueue.shift()
    if (!url) continue
    activeImageFetches += 1
    uni.request({
      url: imageUrl(url),
      method: 'GET',
      responseType: 'arraybuffer',
      timeout: 20000,
      success: (response) => {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          cacheImageFile(url, response)
        }
      },
      complete: () => {
        activeImageFetches -= 1
        imageFetches.delete(url)
        pumpImageFetches()
      },
    })
  }
}

function parseLocation(value) {
  if (Array.isArray(value) && value.length >= 2) return { longitude: Number(value[0]), latitude: Number(value[1]) }
  if (typeof value === 'string') {
    const [longitude, latitude] = value.split(',').map(Number)
    return { longitude, latitude }
  }
  if (value && typeof value === 'object') return { longitude: Number(value.longitude ?? value.lng), latitude: Number(value.latitude ?? value.lat) }
  return null
}

function mapInfo(item) {
  const data = item?.result
  if (!data) return null
  // Merge compact map points with the final POI collection. The backend may
  // enrich coordinates for a model-mentioned attraction after the first map
  // payload was created; preferring one array would silently hide the other.
  const itinerary = isItineraryResult(item)
  const keepPoint = (point) => isPlausiblePoi(point) && (!itinerary || isScenicPoi(point))
  const mapPoints = Array.isArray(data.map?.points) ? data.map.points.filter(keepPoint) : []
  const poiPoints = Array.isArray(data.pois) ? data.pois.filter(keepPoint) : []
  const parsedPoints = [...mapPoints, ...poiPoints].map((point) => {
    const location = parseLocation(point.location || point)
    return location && Number.isFinite(location.longitude) && Number.isFinite(location.latitude) && Math.abs(location.longitude) <= 180 && Math.abs(location.latitude) <= 90
      ? {
          ...point,
          ...location,
          // Keep map labels consistent with cards. The original provider
          // name remains available in the payload for exact matching.
          name: poiDisplayName({
            ...point,
            // A route endpoint such as “北京南站” must keep its full label;
            // destination-prefix cleanup is only for itinerary POIs.
            city: point.city || (isItineraryResult(item) || isPoiMap(item) ? data.destination : ''),
          }),
          location: point.location || `${location.longitude},${location.latitude}`,
        }
      : null
  }).filter(Boolean)
  const points = []
  const seenPoints = new Set()
  for (const point of parsedPoints) {
    const key = String(point.name || '').replace(/\s+/g, '').toLowerCase() || point.location
    if (!key || seenPoints.has(key)) continue
    seenPoints.add(key)
    points.push(point)
    if (points.length >= 30) break
  }
  if (!points.length) return null
  const route = routePoints(data)
  const poiOnly = isPoiMap(item)
  const line = !poiOnly && route.length > 1 ? route : (!poiOnly && !isTrafficMap(data) ? points : [])
  const markers = points.map((point, index) => ({
    id: index + 1,
    latitude: point.latitude,
    longitude: point.longitude,
    title: point.name,
    label: { content: `${index + 1} ${point.name}`, color: '#29433f', fontSize: 11, anchorX: 0, anchorY: 0 },
    callout: { content: point.name, display: 'BYCLICK', padding: 5, borderRadius: 4 },
  }))
  const center = points[Math.floor(points.length / 2)]
  return {
    points,
    markers,
    latitude: center.latitude,
    longitude: center.longitude,
    scale: points.length === 1 ? 14 : 11,
    polyline: line.length > 1 ? [{ points: line.map((point) => ({ latitude: point.latitude, longitude: point.longitude })), color: '#157a6e', width: 5, dottedLine: false, arrowLine: true }] : [],
  }
}

function openMapDetail(item) {
  const detail = mapInfo(item)
  if (!detail) {
    uni.showToast({ title: '暂无可展示的地图', icon: 'none' })
    return
  }
  const poiOnly = isPoiMap(item)
  try {
    uni.setStorageSync('deeptravel_map_preview', {
      ...detail,
      title: poiOnly ? '景点地图' : '行程地图',
      caption: poiOnly ? '仅标注景点位置' : '根据已核验坐标展示',
    })
    uni.navigateTo({
      url: '/pages/map/map',
      fail: () => uni.showToast({ title: '地图页面打开失败', icon: 'none' }),
    })
  } catch {
    uni.showToast({ title: '地图数据加载失败', icon: 'none' })
  }
}

function routePoints(data) {
  const values = data?.map?.polyline || data?.route?.polyline || data?.driving?.polyline
  if (!values) return []
  const list = Array.isArray(values) ? values : String(values).split(/[;|\s]+/)
  return list.map(parseLocation).filter((point) => point && Number.isFinite(point.longitude) && Number.isFinite(point.latitude))
}

function isPoiMap(item) {
  return item?.result?.query_type === 'poi_discovery' || selectedSceneCode.value === 'POI_DISCOVERY'
}

function isTrafficMap(data) {
  return Boolean(data?.route || data?.driving || data?.route_scope === 'cross_city' || ['railway', 'cross_city_web', 'cross_city_overview'].includes(data?.query_type))
}

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : `${date.getMonth() + 1}月${date.getDate()}日`
}
</script>

<style scoped>
.chat-page { display: flex; flex-direction: column; height: 100vh; background: #f7faf9; }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 24rpx 32rpx 14rpx; background: #f7faf9; }
.eyebrow { display: block; color: #72a79e; font-size: 18rpx; font-weight: 700; letter-spacing: 4rpx; }
.page-title { display: block; margin-top: 8rpx; color: #233a37; font-size: 42rpx; font-weight: 700; }
.top-actions { display: flex; align-items: center; gap: 20rpx; }
.session-button { padding: 12rpx 18rpx; border: 1rpx solid #d6e5e1; border-radius: 24rpx; color: #50736c; background: #fff; font-size: 23rpx; }
.new-button { width: 56rpx; height: 56rpx; border-radius: 50%; color: #fff; background: #157a6e; font-size: 40rpx; line-height: 51rpx; text-align: center; }
.scene-scroll { flex-shrink: 0; padding: 10rpx 24rpx 20rpx; white-space: nowrap; }
.scene-row { display: inline-flex; gap: 14rpx; }
.scene-chip { padding: 17rpx 25rpx; border: 1rpx solid #deebe7; border-radius: 32rpx; color: #71847f; background: #fff; font-size: 24rpx; }
.scene-chip.active { border-color: #157a6e; color: #fff; background: #157a6e; box-shadow: 0 7rpx 18rpx #157a6e2b; }
.message-scroll { flex: 1; min-height: 0; padding: 8rpx 28rpx 24rpx; }
.empty-chat { display: flex; flex-direction: column; align-items: center; padding: 110rpx 42rpx 70rpx; text-align: center; }
.advisor-avatar, .avatar { display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; font-weight: 700; }
.advisor-avatar { position: relative; width: 90rpx; height: 90rpx; overflow: visible; color: #fff; background: linear-gradient(145deg, #fff5e8, #ffd8b5); box-shadow: 0 12rpx 28rpx #8b5a3430; font-size: 48rpx; }
.advisor-person { font-size: 54rpx; line-height: 1; }
.empty-title { margin-top: 22rpx; color: #29433f; font-size: 31rpx; font-weight: 700; }
.empty-description { margin-top: 18rpx; color: #778a85; font-size: 26rpx; line-height: 1.75; }
.message-row { display: flex; align-items: flex-start; gap: 14rpx; margin: 22rpx 0; }
.message-row.user { justify-content: flex-end; }
.message-body { max-width: 78%; }
.message-row.user .message-body { max-width: 78%; }
.avatar { flex-shrink: 0; width: 58rpx; height: 58rpx; font-size: 23rpx; }
.assistant-avatar { position: relative; overflow: visible; color: #157a6e; background: linear-gradient(145deg, #fff6e9, #ffdab9); box-shadow: 0 5rpx 14rpx #9b684027; }
.assistant-person { font-size: 34rpx; line-height: 1; }
.assistant-charm { position: absolute; right: -7rpx; bottom: -7rpx; display: flex; align-items: center; justify-content: center; width: 28rpx; height: 28rpx; border: 3rpx solid #fff; border-radius: 50%; color: #fff; background: linear-gradient(145deg, #ff9a91, #ee6578); box-shadow: 0 5rpx 12rpx #b8476038; font-size: 16rpx; font-weight: 800; line-height: 1; }
.user-avatar { color: #fff; background: #e58a66; font-size: 28rpx; }
.avatar-coral { background: linear-gradient(145deg, #ff998d, #e77765); }
.avatar-teal { background: linear-gradient(145deg, #55b9a7, #278b7d); }
.avatar-green { background: linear-gradient(145deg, #78b986, #438b5b); }
.avatar-blue { background: linear-gradient(145deg, #70acef, #477fca); }
.avatar-slate { background: linear-gradient(145deg, #7d91aa, #55687d); }
.avatar-amber { background: linear-gradient(145deg, #f3b85e, #dd8b37); }
.avatar-violet { background: linear-gradient(145deg, #a88bd0, #765baa); }
.bubble { display: block; padding: 21rpx 24rpx; border-radius: 6rpx 24rpx 24rpx; color: #304640; background: #fff; box-shadow: 0 5rpx 22rpx #2e6a5c0e; font-size: 28rpx; line-height: 1.7; word-break: break-word; }
.content-line { display: block; white-space: normal; word-break: break-word; }
.content-line + .content-line { margin-top: 10rpx; }
.content-heading { margin: 4rpx 0 2rpx; color: #214a42; font-size: 30rpx; font-weight: 700; line-height: 1.5; }
.content-list { padding-left: 4rpx; color: #34534c; }
.content-blank { height: 8rpx; margin: 0; }
.user .bubble { border-radius: 24rpx 6rpx 24rpx 24rpx; color: #fff; background: #157a6e; }
.bubble.progress { color: #68847d; background: #edf7f3; font-size: 24rpx; }
.typing { display: inline-block; padding: 18rpx 23rpx; border-radius: 6rpx 22rpx 22rpx; color: #80928d; background: #fff; font-size: 25rpx; }
.structured-content { margin-top: 14rpx; }
.poi-entry { margin-top: 14rpx; }
.poi-card { padding: 21rpx; border: 1rpx solid #deebe7; border-radius: 18rpx; background: #fff; }
.poi-heading { display: flex; align-items: center; gap: 12rpx; }
.poi-name { flex: 1; min-width: 0; overflow: hidden; color: #21443d; font-size: 29rpx; font-weight: 700; line-height: 1.45; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.poi-day { padding: 5rpx 10rpx; border-radius: 12rpx; color: #438b7e; background: #e8f5f1; font-size: 19rpx; }
.poi-intro { margin-top: 12rpx; padding: 14rpx 16rpx; border-radius: 12rpx; background: #f6faf8; }
.poi-intro-label { display: block; color: #4f8378; font-size: 21rpx; font-weight: 700; }
.poi-description { display: block; margin-top: 5rpx; color: #637873; font-size: 24rpx; line-height: 1.65; }
.poi-photo-card { margin-top: 8rpx; padding: 14rpx 16rpx 16rpx; border: 1rpx solid #e4eeeb; border-radius: 16rpx; background: #f8fbfa; }
.poi-photo-label { display: block; color: #5b8178; font-size: 21rpx; line-height: 1.4; }
.poi-inline-media { margin: 12rpx 0 4rpx; padding: 12rpx 14rpx 14rpx; border-radius: 14rpx; background: #f6faf8; }
.poi-inline-label { display: block; color: #5b8178; font-size: 21rpx; line-height: 1.4; }
.poi-images { margin-top: 15rpx; white-space: nowrap; }
.poi-image { display: inline-block; width: 230rpx; height: 150rpx; margin-right: 12rpx; border-radius: 12rpx; background: #e9f0ee; transition: opacity .15s ease, transform .15s ease; }
.poi-image:active { opacity: .84; transform: scale(.98); }
.map-card { margin-top: 18rpx; overflow: hidden; border: 1rpx solid #dce9e5; border-radius: 18rpx; background: #fff; }
.map-title-row { display: flex; align-items: center; justify-content: space-between; gap: 18rpx; padding: 18rpx 20rpx 14rpx; }
.map-title-copy { min-width: 0; }
.map-title, .map-caption { display: block; }
.map-title { color: #294b44; font-size: 27rpx; font-weight: 700; }
.map-caption { margin-top: 4rpx; color: #8a9c97; font-size: 20rpx; }
.map-open { display: flex; flex-shrink: 0; align-items: center; gap: 4rpx; padding: 10rpx 14rpx; border-radius: 18rpx; color: #157a6e; background: #eaf6f2; font-size: 21rpx; font-weight: 700; }
.map-open-active { opacity: .72; transform: scale(.97); }
.map-open-arrow { margin-top: -2rpx; font-size: 28rpx; font-weight: 500; line-height: 1; }
.map { width: 100%; height: 330rpx; }
.map-place-list { display: flex; flex-wrap: wrap; gap: 10rpx; padding: 15rpx 18rpx 18rpx; }
.map-place-list text { padding: 8rpx 12rpx; border-radius: 22rpx; color: #607873; background: #eff7f4; font-size: 21rpx; }
.map-place-list i { display: inline-flex; align-items: center; justify-content: center; width: 29rpx; height: 29rpx; margin-right: 6rpx; border-radius: 50%; color: #fff; background: #267e73; font-style: normal; font-size: 17rpx; }
.citation-box { margin-top: 14rpx; padding: 15rpx 20rpx; border-radius: 14rpx; background: #f0f6f4; }
.citation-title, .citation-item { display: block; color: #7b8f89; font-size: 20rpx; line-height: 1.6; }
.citation-title { margin-bottom: 5rpx; color: #587b72; font-weight: 700; }
.message-bottom { height: 12rpx; }
.composer { flex-shrink: 0; padding: 12rpx 28rpx calc(22rpx + env(safe-area-inset-bottom)); border-top: 1rpx solid #e1ece9; background: #fff; }
.composer-tip { display: block; margin-bottom: 10rpx; color: #8b9c98; font-size: 21rpx; }
.composer-row { display: flex; align-items: flex-end; gap: 12rpx; }
.composer-input { flex: 1; min-height: 76rpx; max-height: 190rpx; padding: 18rpx 20rpx; border: 1rpx solid #dceae6; border-radius: 18rpx; color: #2c433f; background: #f8fbfa; font-size: 27rpx; line-height: 1.45; }
.input-placeholder { color: #afbfba; font-size: 25rpx; }
.send-button { width: 120rpx; height: 76rpx; margin: 0; padding: 0; border-radius: 18rpx; color: #fff; background: #157a6e; font-size: 25rpx; line-height: 76rpx; }
.send-button[disabled] { opacity: .45; }
.sheet-mask { position: fixed; z-index: 20; inset: 0; display: flex; align-items: flex-end; background: #163a3380; }
.session-sheet { width: 100%; max-height: 75vh; padding: 26rpx 28rpx calc(24rpx + env(safe-area-inset-bottom)); border-radius: 30rpx 30rpx 0 0; background: #fff; }
.sheet-head { display: flex; align-items: center; justify-content: space-between; padding-bottom: 20rpx; }
.sheet-title { color: #29433f; font-size: 31rpx; font-weight: 700; }
.sheet-close { color: #79918a; font-size: 23rpx; }
.session-list { max-height: 53vh; }
.session-item { position: relative; margin: 8rpx 0; padding: 19rpx 90rpx 17rpx 18rpx; border: 1rpx solid #e1ece9; border-radius: 16rpx; background: #fbfdfc; }
.session-item.current { border-color: #81beb3; background: #eff8f5; }
.session-title, .session-preview, .session-date { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-title { color: #38544e; font-size: 26rpx; font-weight: 700; }
.session-preview { margin-top: 8rpx; color: #81918c; font-size: 22rpx; }
.session-date { position: absolute; top: 21rpx; right: 17rpx; color: #a0afaa; font-size: 19rpx; }
.no-sessions { padding: 50rpx 0; color: #91a19c; text-align: center; font-size: 23rpx; }
.sheet-new { height: 75rpx; margin: 20rpx 0 0; border-radius: 16rpx; color: #157a6e; background: #e5f4f0; font-size: 25rpx; line-height: 75rpx; }
</style>
