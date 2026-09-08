<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const scenes = ref([])
const selected = ref('TRAVEL_PLAN')
const message = ref('')
const history = ref([])
const sessions = ref([])
const sessionId = ref('')
const result = ref(null)
const health = ref(null)
const loading = ref(false)
const booting = ref(true)
const error = ref('')
const activeRequest = ref(null)

// Some privacy modes and embedded browsers deny localStorage access. Keep the
// login screen usable instead of aborting the whole Vue setup with a
// SecurityError and leaving a blank page.
function readStoredToken() {
  try { return localStorage.getItem('deeptravel_token') || '' } catch { return '' }
}

function writeStoredToken(value) {
  try { localStorage.setItem('deeptravel_token', value) } catch { /* optional */ }
}

function removeStoredToken() {
  try { localStorage.removeItem('deeptravel_token') } catch { /* optional */ }
}

const token = ref(readStoredToken())
const user = ref(null)
const authForm = ref({ username: '', password: '' })
const adminTab = ref('users')
const adminUsers = ref([])
const USER_PAGE_SIZE = 5
const userPage = ref(1)
const documents = ref([])
const adminForm = ref({ username: '', password: '', display_name: '' })
const selectedFile = ref(null)
const uploadSourceUrl = ref('')
const uploadCategory = ref('')
const uploadCity = ref('')
const adminBusy = ref(false)
const fileInput = ref(null)
const knowledgeCategories = ref([])
const selectedKnowledgeCategory = ref('all')
const DOCUMENT_PAGE_SIZE = 5
const documentPage = ref(1)
const expiryClock = ref(Date.now())
let expiryTimer = null
const realtimeKnowledgeCategories = computed(() => {
  const codes = new Set()
  const walk = (items) => (items || []).forEach((item) => {
    // TTL is maintained by the database, so newly configured real-time
    // categories automatically receive the same labels and countdown UI.
    if (item.ttl_hours != null) codes.add(item.code)
    walk(item.children)
  })
  walk(knowledgeCategories.value)
  return codes
})
const isRealtimeDocument = (item) => realtimeKnowledgeCategories.value.has(item.sub_category) || realtimeKnowledgeCategories.value.has(item.category)
const knowledgeCategoryOptions = computed(() => {
  const options = []
  const walk = (items, depth = 0) => (items || []).forEach((item) => {
    const children = item.children || []
    options.push({ ...item, children, depth })
    walk(children, depth + 1)
  })
  walk(knowledgeCategories.value)
  return options
})
// Real-time knowledge is created from verified online sources and expires
// automatically. Keep it visible to administrators, while the regular upload
// selector continues to offer only durable knowledge categories.
const uploadKnowledgeCategoryOptions = computed(() => knowledgeCategoryOptions.value.filter((item) =>
  item.depth > 0 && !item.children?.length && !realtimeKnowledgeCategories.value.has(item.code)))
const knowledgeCategoryLabels = computed(() => Object.fromEntries(
  knowledgeCategoryOptions.value.map((item) => [item.code, item.name]),
))
const managedDocuments = computed(() => documents.value.filter((item) =>
  ['READY', 'REVIEWING'].includes(item.status) && item.enabled !== false))
const visibleDocuments = computed(() => selectedKnowledgeCategory.value === 'all'
  ? managedDocuments.value
  : managedDocuments.value.filter((item) => {
      const selected = selectedKnowledgeCategory.value
      if ((item.sub_category || item.category) === selected) return true
      // Selecting a parent category includes all of its leaves.  The API
      // supplies parent_code, so this remains compatible with future dynamic
      // categories instead of hard-coding the taxonomy in the component.
      const node = knowledgeCategoryOptions.value.find((entry) => entry.code === selected)
      if (!node) return false
      const descendants = new Set()
      const collect = (entry) => {
        descendants.add(entry.code)
        ;(entry.children || []).forEach(collect)
      }
      collect(node)
      return descendants.has(item.sub_category) || descendants.has(item.category)
    }))
const documentPageCount = computed(() => Math.max(1, Math.ceil(visibleDocuments.value.length / DOCUMENT_PAGE_SIZE)))
const pagedVisibleDocuments = computed(() => {
  const page = Math.min(documentPage.value, documentPageCount.value)
  const start = (page - 1) * DOCUMENT_PAGE_SIZE
  return visibleDocuments.value.slice(start, start + DOCUMENT_PAGE_SIZE)
})
watch(selectedKnowledgeCategory, () => { documentPage.value = 1 })
watch(() => visibleDocuments.value.length, () => {
  if (documentPage.value > documentPageCount.value) documentPage.value = documentPageCount.value
})
const userPageCount = computed(() => Math.max(1, Math.ceil(adminUsers.value.length / USER_PAGE_SIZE)))
const pagedAdminUsers = computed(() => {
  const page = Math.min(userPage.value, userPageCount.value)
  const start = (page - 1) * USER_PAGE_SIZE
  return adminUsers.value.slice(start, start + USER_PAGE_SIZE)
})
watch(() => adminUsers.value.length, () => {
  if (userPage.value > userPageCount.value) userPage.value = userPageCount.value
})
const activeUserCount = computed(() => adminUsers.value.filter((item) => item.is_active).length)
const readyDocumentCount = computed(() => managedDocuments.value.filter((item) => item.status === 'READY').length)
const reviewingDocumentCount = computed(() => managedDocuments.value.filter((item) => item.status === 'REVIEWING').length)
const realtimeDocumentCount = computed(() => managedDocuments.value.filter(isRealtimeDocument).length)
const expiringSoonDocumentCount = computed(() => managedDocuments.value.filter((item) => {
  if (!item.expires_at) return false
  const remaining = new Date(item.expires_at).getTime() - expiryClock.value
  return remaining > 0 && remaining <= 24 * 60 * 60 * 1000
}).length)
const editingDocument = ref(null)
const editingContent = ref('')
const editingMode = ref('view')
const mapContainer = ref(null)
const mapError = ref('')
const mapRenderState = ref('idle')
const browserPreviewImages = ref([])
const browserPreviewIndex = ref(0)
const browserPreviewCurrent = computed(() => browserPreviewImages.value[browserPreviewIndex.value] || '')
const MAX_POI_IMAGES = 2
let itineraryMap = null
let leafletPromise = null
let mapRenderId = 0
const formattedDocumentBlocks = computed(() => {
  const lines = editingContent.value.replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let paragraph = []
  const flush = () => { if (paragraph.length) { blocks.push({ type: 'paragraph', text: paragraph.join(' ') }); paragraph = [] } }
  lines.forEach((line) => {
    const value = line.trim()
    if (!value) { flush(); return }
    const heading = value.match(/^#{1,6}\s+(.+)$/)
    if (heading) { flush(); blocks.push({ type: 'heading', level: value.match(/^#+/)[0].length, text: heading[1] }); return }
    if (/^([-*•])\s+/.test(value)) { flush(); blocks.push({ type: 'bullet', text: value.replace(/^[-*•]\s+/, '') }); return }
    if (/^\d+[.)]\s+/.test(value)) { flush(); blocks.push({ type: 'ordered', text: value.replace(/^\d+[.)]\s+/, '') }); return }
    paragraph.push(value)
  })
  flush()
  return blocks
})

const itineraryMapPoints = computed(() => {
  const resultData = result.value?.result || {}
  const mapPoints = resultData?.map?.points
  const poiPoints = resultData?.pois
  // Route answers do not have itinerary POIs, but the Amap route response
  // carries verified coordinates for its endpoints. Convert those endpoints
  // to the same compact map-point shape used by travel plans so route maps
  // render in exactly the same place and with the same dimensions.
  const routeData = (resultData?.route && typeof resultData.route === 'object')
    ? resultData.route
    : ((resultData?.driving && typeof resultData.driving === 'object')
      ? resultData.driving
      : ((resultData?.origin_location || resultData?.destination_location)
        ? resultData
        : null))
  const routePoints = routeData
    ? [
        {
          name: routeData.origin || resultData.origin || '起点',
          location: routeData.origin_location,
          address: routeData.origin_address || '',
        },
        {
          name: routeData.destination || resultData.destination || '终点',
          location: routeData.destination_location,
          address: routeData.destination_address || '',
        },
      ]
    : []
  const preferredPoints = Array.isArray(mapPoints) && mapPoints.length
    ? mapPoints
    : (Array.isArray(poiPoints) && poiPoints.length ? poiPoints : routePoints)
  const normalise = (points) => points.map((point) => {
    if (!point || typeof point !== 'object') return null
    let longitude = Number(point.longitude ?? point.lng)
    let latitude = Number(point.latitude ?? point.lat)
    const location = point.location
    if ((!Number.isFinite(longitude) || !Number.isFinite(latitude)) && Array.isArray(location)) {
      longitude = Number(location[0])
      latitude = Number(location[1])
    }
    if ((!Number.isFinite(longitude) || !Number.isFinite(latitude)) && location && typeof location === 'object') {
      longitude = Number(location.longitude ?? location.lng)
      latitude = Number(location.latitude ?? location.lat)
    }
    if ((!Number.isFinite(longitude) || !Number.isFinite(latitude)) && typeof location === 'string') {
      const values = location.split(',').map(Number)
      longitude = Number(values[0])
      latitude = Number(values[1])
    }
    return Number.isFinite(longitude) && Number.isFinite(latitude)
      && Math.abs(longitude) <= 180 && Math.abs(latitude) <= 90
      ? { ...point, longitude, latitude, location: `${longitude},${latitude}` }
      : null
  }).filter(Boolean)
  const normalised = normalise(preferredPoints)
  // A stale saved result may contain a non-empty map array with malformed
  // coordinates. Prefer valid POI coordinates before declaring the map empty.
  if (normalised.length || preferredPoints === poiPoints || preferredPoints === routePoints) return normalised
  const poiFallback = normalise(Array.isArray(poiPoints) ? poiPoints : [])
  return poiFallback.length ? poiFallback : normalise(routePoints)
})

const itineraryMapCaption = computed(() => {
  const resultData = result.value?.result || {}
  if (resultData?.query_type === 'poi_discovery' || selected.value === 'POI_DISCOVERY') {
    return '标注高德地图 MCP 返回的景点位置（仅显示地点，不规划路线）'
  }
  const routeData = resultData?.route || resultData?.driving
  const mode = resultData?.map?.mode || routeData?.mode
  const source = resultData?.map?.polyline_source || routeData?.polyline_source
  if (mode && itineraryMapRoute.value.length > 1) {
    if (source === 'step_direction_estimate') return `按${mode}路段方向绘制路线示意（非精确道路轨迹）`
    return `按${mode}路线绘制`
  }
  if (mode && isTrafficRouteMap.value) return `高德 MCP 未提供${mode}道路轨迹，仅显示起终点`
  if (mode) return `按${mode}显示起终点示意`
  if (resultData?.query_type === 'railway' || resultData?.query_type === 'cross_city_web') {
    return '跨城市起终点位置示意（暂无该交通方式轨迹）'
  }
  return routeData ? '根据高德地图 MCP 返回的起终点坐标绘制' : '根据高德地图 MCP 返回的景点坐标绘制'
})

const isPoiDiscoveryMap = computed(() => {
  const resultData = result.value?.result || {}
  return resultData?.query_type === 'poi_discovery' || selected.value === 'POI_DISCOVERY'
})

function routeCoordinate(value) {
  if (Array.isArray(value) && value.length >= 2) {
    const longitude = Number(value[0])
    const latitude = Number(value[1])
    return Number.isFinite(longitude) && Number.isFinite(latitude)
      ? { longitude, latitude }
      : null
  }
  if (typeof value === 'string') {
    const values = value.split(',').map(Number)
    const longitude = Number(values[0])
    const latitude = Number(values[1])
    return Number.isFinite(longitude) && Number.isFinite(latitude)
      ? { longitude, latitude }
      : null
  }
  if (!value || typeof value !== 'object') return null
  if (value.location !== undefined) return routeCoordinate(value.location)
  const longitude = Number(value.longitude ?? value.lng)
  const latitude = Number(value.latitude ?? value.lat)
  return Number.isFinite(longitude) && Number.isFinite(latitude)
    ? { longitude, latitude }
    : null
}

const itineraryMapRoute = computed(() => {
  const resultData = result.value?.result || {}
  const routeData = resultData?.route || resultData?.driving || resultData
  const candidates = [resultData?.map?.polyline, routeData?.polyline, routeData?.geometry, routeData?.steps]
  const raw = candidates.find((value) => (Array.isArray(value) ? value.length > 0 : Boolean(value)))
  const coordinates = []
  const add = (value) => {
    if (typeof value === 'string') {
      value.split(/[;|\s]+/).forEach((token) => {
        const point = routeCoordinate(token)
        if (point) coordinates.push(point)
      })
      return
    }
    if (Array.isArray(value)) {
      const point = routeCoordinate(value)
      if (point) {
        coordinates.push(point)
        return
      }
      value.forEach(add)
      return
    }
    if (value && typeof value === 'object') {
      const point = routeCoordinate(value)
      if (point) {
        coordinates.push(point)
        return
      }
      Object.entries(value).forEach(([key, nested]) => {
        if (['polyline', 'geometry', 'route_path', 'path', 'steps', 'segments', 'walking', 'bus', 'buslines', 'railway'].includes(key.toLowerCase())) add(nested)
      })
    }
  }
  add(raw)
  return coordinates.filter((point, index) => index === 0 || point.longitude !== coordinates[index - 1].longitude || point.latitude !== coordinates[index - 1].latitude)
})

const hasItineraryMap = computed(() => itineraryMapPoints.value.length > 0 || itineraryMapRoute.value.length > 1)

// A route response is different from an itinerary: when the map provider
// cannot return geometry, connecting two traffic endpoints with a line is
// misleading.  Keep the endpoint markers, but only draw a line for an
// observed/derived route polyline.  Itineraries may still connect their POIs
// as a compact day-by-day overview.
const isTrafficRouteMap = computed(() => {
  const data = result.value?.result || {}
  return Boolean(
    data?.route || data?.driving
    // ``RoutePlanningAgent._finalize`` flattens the selected route into the
    // result object, so city-internal responses have verified endpoint
    // fields but no nested ``route`` key.
    || (data?.origin_location && data?.destination_location && data?.mode)
    || ['railway', 'cross_city_web', 'cross_city_overview'].includes(data?.query_type)
    || data?.route_scope === 'cross_city'
  )
})

// A Leaflet map is useful when its CDN and tile service are reachable, but a
// travel answer must not lose its map just because a browser cannot load an
// external script.  This compact SVG uses the same verified coordinates as
// Leaflet and acts as a deterministic, network-free route diagram.
const mapSvgPoints = computed(() => {
  const points = itineraryMapPoints.value
  const route = itineraryMapRoute.value
  const allPoints = [...points, ...route]
  if (!allPoints.length) return []
  const longitudes = allPoints.map((point) => point.longitude)
  const latitudes = allPoints.map((point) => point.latitude)
  const minLongitude = Math.min(...longitudes)
  const maxLongitude = Math.max(...longitudes)
  const minLatitude = Math.min(...latitudes)
  const maxLatitude = Math.max(...latitudes)
  const longitudeSpan = Math.max(maxLongitude - minLongitude, 0.002)
  const latitudeSpan = Math.max(maxLatitude - minLatitude, 0.002)
  const project = (point) => ({
    ...point,
    x: 8 + ((point.longitude - minLongitude) / longitudeSpan) * 84,
    // SVG's y-axis grows downwards, so larger latitude is placed higher.
    y: 8 + ((maxLatitude - point.latitude) / latitudeSpan) * 84,
  })
  return points.map((point, index) => ({ ...project(point), index }))
})

const mapSvgPolyline = computed(() => {
  // A POI discovery map is marker-only. Connecting unrelated attractions
  // would imply an ordered route that the user did not request.
  if (isPoiDiscoveryMap.value) return ''
  const route = itineraryMapRoute.value
  if (route.length > 1) {
    const allPoints = [...itineraryMapPoints.value, ...route]
    const longitudes = allPoints.map((point) => point.longitude)
    const latitudes = allPoints.map((point) => point.latitude)
    const minLongitude = Math.min(...longitudes)
    const maxLongitude = Math.max(...longitudes)
    const minLatitude = Math.min(...latitudes)
    const maxLatitude = Math.max(...latitudes)
    const longitudeSpan = Math.max(maxLongitude - minLongitude, 0.002)
    const latitudeSpan = Math.max(maxLatitude - minLatitude, 0.002)
    return route.map((point) => `${8 + ((point.longitude - minLongitude) / longitudeSpan) * 84},${8 + ((maxLatitude - point.latitude) / latitudeSpan) * 84}`).join(' ')
  }
  if (isTrafficRouteMap.value) return ''
  return mapSvgPoints.value.map((point) => `${point.x},${point.y}`).join(' ')
})

function recoverImage(event, poi) {
  // Keep a direct-URL fallback for local development when the backend is
  // temporarily restarting; guard it so a failed CDN URL cannot loop.
  if (event.currentTarget.dataset.directFallback || !poi.photo) return
  event.currentTarget.dataset.directFallback = 'true'
  event.currentTarget.src = poi.photo
}

function closeBrowserImagePreview() {
  browserPreviewImages.value = []
  browserPreviewIndex.value = 0
}

function moveBrowserImagePreview(offset) {
  const total = browserPreviewImages.value.length
  if (total < 2) return
  browserPreviewIndex.value = (browserPreviewIndex.value + offset + total) % total
}

function handleBrowserImageClick(event) {
  const image = event.target?.closest?.('.message-attraction .image-grid img')
  if (!image) return
  const gallery = [...image.closest('.image-grid').querySelectorAll('img')]
    .map((item) => item.currentSrc || item.src)
    .filter(Boolean)
  if (!gallery.length) return
  const current = image.currentSrc || image.src
  browserPreviewImages.value = gallery
  browserPreviewIndex.value = Math.max(0, gallery.indexOf(current))
}

function handleBrowserPreviewKeydown(event) {
  if (!browserPreviewImages.value.length) return
  if (event.key === 'Escape') closeBrowserImagePreview()
  else if (event.key === 'ArrowLeft') moveBrowserImagePreview(-1)
  else if (event.key === 'ArrowRight') moveBrowserImagePreview(1)
}

function photoUrl(value) {
  // Amap normally returns strings, but different MCP deployments may wrap
  // them in {url}, {large_url}, {image_url}, etc. Keep the UI tolerant of
  // either shape so a valid image is never discarded before rendering.
  if (typeof value === 'string') {
    const candidate = value.trim()
    return /^https?:\/\//i.test(candidate) ? candidate : ''
  }
  if (!value || typeof value !== 'object') return ''
  for (const key of ['large_url', 'original_url', 'url', 'image_url', 'photo_url', 'thumbnail', 'src']) {
    const candidate = photoUrl(value[key])
    if (candidate) return candidate
  }
  return ''
}

function canonicalPhotoKey(value) {
  const url = photoUrl(value)
  if (!url) return ''
  try {
    const parsed = new URL(url)
    // CDN resize/query parameters can make the same source image look like
    // different URLs. Use the normalized host/path as the duplicate key while
    // retaining the first (usually highest-quality) URL for rendering.
    let pathname = parsed.pathname || '/'
    try { pathname = decodeURIComponent(pathname) } catch { /* keep encoded path */ }
    return `${parsed.hostname.toLowerCase()}${pathname.replace(/\/+$/, '')}`
  } catch {
    return url.toLowerCase().split(/[?#]/u, 1)[0].replace(/\/+$/, '')
  }
}

function canonicalAttractionKey(value, destination = '') {
  const clean = (input) => String(input || '')
    .trim()
    .toLocaleLowerCase()
    .replace(/[\s，,。；;、|]/gu, '')
    .split('')
    .filter((character) => !'()[]{}<>《》“”‘’\'"·/-'.includes(character))
    .join('')
  let name = clean(value)
  if (!name) return ''
  let city = clean(destination).replace(/市$/u, '')
  if (city && name.startsWith(city) && name.length > city.length) name = name.slice(city.length)
  return name.replace(/(风景名胜区|旅游景区|风景区|景区|景点)$/u, '')
}

const knownAttractionAliases = {
  '西湖': ['西湖', '杭州西湖', '西湖风景名胜区', '杭州西湖风景名胜区', 'West Lake'],
  '灵隐寺': ['灵隐寺', '杭州灵隐寺', '灵隐景区', 'Lingyin Temple'],
  '故宫': ['故宫', '北京故宫', '故宫博物院', 'Forbidden City'],
  '长城': ['长城', '万里长城', 'Great Wall'],
  '兵马俑': ['兵马俑', '秦始皇兵马俑', 'Terracotta Army'],
}

function attractionAliases(poi, destination = '') {
  const name = String(poi?.name || '').trim()
  const city = String(poi?.city || destination || '').trim().replace(/市$/u, '')
  const shortName = name.replace(new RegExp(`^${city}`), '').replace(/(风景名胜区|旅游景区|景区)$/u, '')
  const known = Object.entries(knownAttractionAliases)
    .filter(([, aliases]) => aliases.some((alias) => name.includes(alias) || alias.includes(name)))
    .flatMap(([canonical, aliases]) => [canonical, ...aliases])
  return [name, shortName, ...known, String(poi?.alias || '').trim(), ...String(poi?.alias || '').split(/[，,、/|]/).map((value) => value.trim())]
    .filter((value) => value.length >= 2)
    .sort((left, right) => right.length - left.length)
}

function attractionDescription(content, poi, destination = '', allowWithoutAlias = false) {
  const text = String(content || '')
    .replace(/\r\n?/g, '\n')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
  const aliases = attractionAliases(poi, destination)
  if (!aliases.length) return ''
  // A route sentence can mention every attraction in one line. It is useful
  // for navigation, but it is not an attraction introduction and must not be
  // copied into every image card.
  const routeOnly = /路线|交通方式|起点|终点|导航|换乘|公交|地铁|驾车|打车|乘坐|车站|站点|公里|分钟|耗时|直达|从.{1,16}(?:到|至).{1,16}|.{1,16}(?:→|➡).{1,16}/u
  const introduction = /位于|坐落|特色|以.{0,12}(?:闻名|著称)|历史|始建|建于|景观|建筑|文化|湖光|山水|适合|推荐|可以|值得|参观|游览|开放|门票|面积|街区|商业街/u
  const scheduleOnly = /(?:上午|中午|下午|晚上|早上|傍晚|清晨).{0,18}(?:安排|留给|前往|步行|乘坐|搭乘|驾车|打车|抵达|游览|参观|时间)|(?:步行|乘坐|搭乘|驾车|打车|骑行).{0,12}(?:到|前往|抵达)/u
  const addressPattern = /(?:路|街|巷|道|大道|弄)\s*\d+\s*号?/u
  const chunks = text.match(/[^。！？；\n]+[。！？；]?/gu) || []
  const candidates = []
  for (const chunk of chunks) {
    const sentence = chunk.replace(/^[-*•\s]+/, '').replace(/\s+/g, ' ').trim()
    if (sentence.length < 18 || (!allowWithoutAlias && !aliases.some((alias) => sentence.includes(alias)))) continue
    // Navigation text must never become an attraction introduction, even if
    // the same sentence also contains words such as “景色优美” or “适合”。
    if (routeOnly.test(sentence) || scheduleOnly.test(sentence)) continue
    // A street name in brackets is often only an address attached to a
    // different attraction. Do not use that schedule/address sentence as
    // the street's own introduction unless it contains real intro wording.
    if (addressPattern.test(sentence) && !introduction.test(sentence)) continue
    const score = (introduction.test(sentence) ? 3 : 0) + Math.min(sentence.length, 180) / 180
    candidates.push({ sentence, score })
  }
  candidates.sort((left, right) => right.score - left.score)
  const selected = candidates.slice(0, 2).map((item) => item.sentence)
  const description = selected.join(' ')
  return description.length > 300 ? `${description.slice(0, 297)}…` : description
}

function messageAttractions(item) {
  const resultData = item?.result
  if (!resultData || (!Array.isArray(resultData?.pois) && !Array.isArray(resultData?.map?.points))) return []
  const cards = []
  const seen = new Set()
  const seenPhotos = new Set()
  const seenDescriptions = new Set()
  const dayByName = new Map()
  for (const day of resultData.days_plan || []) {
    for (const name of day.activities || []) dayByName.set(String(name), day.day)
  }
  // Prefer full POI observations; map points are a compact fallback for
  // responses where only the map payload was persisted.
  const places = [...(resultData.pois || []), ...(resultData.map?.points || [])]
  const destination = String(resultData.destination || '').trim()
  for (const poi of places) {
    if (!poi || typeof poi !== 'object') continue
    const photos = Array.isArray(poi?.photos)
      ? poi.photos
      : [poi?.photo, poi?.image_url, poi?.photo_url, poi?.thumbnail]
    const images = []
    for (const photo of photos) {
      const url = photoUrl(photo)
      const photoKey = canonicalPhotoKey(url)
      if (url && photoKey) {
        if (!images.some((item) => item.photoKey === photoKey) && !seenPhotos.has(photoKey)) {
          images.push({
            photo: url,
            photoKey,
            imageSrc: `/api/v1/media/amap-image?url=${encodeURIComponent(url)}`,
          })
        }
      }
      if (images.length >= MAX_POI_IMAGES) break
    }
    if (!images.length) continue
    const key = canonicalAttractionKey(poi.name, destination) || String(poi.id || '')
    if (seen.has(key)) continue
    const modelDescription = attractionDescription(item?.content, poi, destination)
    const providerDescription = attractionDescription(poi.description, poi, destination)
    // Evidence-backed POI copy is preferred over a sentence from the model's
    // itinerary. The latter can describe how to travel between every place,
    // which is useful in the answer but not an attraction introduction.
    const description = providerDescription || modelDescription
    // Do not append a photo-only card with a generic type/address sentence.
    // It makes an unmentioned POI look as if the model had described it. A
    // card is rendered only when the answer or provider supplies a genuinely
    // useful description; the model prompt asks for this detail explicitly.
    const descriptionKey = description.replace(/\s+/gu, '')
    if (!description || description.length < 18 || seenDescriptions.has(descriptionKey)) continue
    seen.add(key)
    seenDescriptions.add(descriptionKey)
    for (const image of images) seenPhotos.add(image.photoKey)
    cards.push({
      ...poi,
      day: dayByName.get(String(poi.name || '')),
      description,
      images,
    })
  }
  return cards.slice(0, 12)
}

function messageContentParts(item) {
  const content = String(item?.content || '')
  const attractions = item?.role === 'assistant' ? messageAttractions(item) : []
  if (!attractions.length) return [{ type: 'text', text: content }]

  const mentions = attractions.map((poi) => {
    const aliases = attractionAliases(poi, item?.result?.destination)
    const positions = aliases.map((alias) => content.indexOf(alias)).filter((position) => position >= 0)
    if (!positions.length) return null
    const index = Math.min(...positions)
    const line = content.slice(index).split(/\n/u, 1)[0]
    const punctuation = [...line.matchAll(/[。！？；]/gu)]
    const punctuationOffset = punctuation[Math.min(1, punctuation.length - 1)]?.index
    const end = punctuationOffset == null ? index + line.length : index + punctuationOffset + 1
    return { poi, index, end }
  }).filter(Boolean).sort((left, right) => left.index - right.index)
  // Keep media and prose one-to-one. If the model did not mention a POI, its
  // image must not be appended as an unexplained card at the bottom; the
  // backend enrichment pass will try to resolve that named attraction first.
  if (!mentions.length) {
    return [{ type: 'text', text: content }]
  }

  const parts = []
  let cursor = 0
  let index = 0
  while (index < mentions.length) {
    const lineEnd = mentions[index].end
    if (lineEnd > cursor) parts.push({ type: 'text', text: content.slice(cursor, lineEnd) })
    while (index < mentions.length && mentions[index].end === lineEnd) {
      parts.push({ type: 'attraction', poi: mentions[index].poi })
      index += 1
    }
    cursor = lineEnd
  }
  if (cursor < content.length) parts.push({ type: 'text', text: content.slice(cursor) })
  return parts
}

function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L)
  if (leafletPromise) return leafletPromise
  leafletPromise = new Promise((resolve, reject) => {
    if (!document.querySelector('link[data-leaflet]')) {
      const link = document.createElement('link')
      link.rel = 'stylesheet'
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
      link.dataset.leaflet = 'true'
      document.head.appendChild(link)
    }
    const existingScript = document.querySelector('script[data-leaflet]')
    if (existingScript) {
      existingScript.addEventListener('load', () => resolve(window.L), { once: true })
      existingScript.addEventListener('error', () => reject(new Error('地图组件加载失败')), { once: true })
      // The script might have finished before this call installed listeners.
      if (window.L) resolve(window.L)
      return
    }
    const script = document.createElement('script')
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
    script.async = true
    script.dataset.leaflet = 'true'
    script.onload = () => window.L ? resolve(window.L) : reject(new Error('地图组件加载失败'))
    script.onerror = () => reject(new Error('地图组件加载失败'))
    document.head.appendChild(script)
  }).catch((error) => {
    // A transient CDN failure should be retryable on the next itinerary.
    leafletPromise = null
    document.querySelector('script[data-leaflet]')?.remove()
    throw error
  })
  return leafletPromise
}

function destroyItineraryMap() {
  if (itineraryMap) {
    try { itineraryMap.remove() } catch { /* already removed by the browser */ }
    itineraryMap = null
  }
}

function setMapContainer(element) {
  mapContainer.value = element || null
}

function renderMapFallback() {
  const container = mapContainer.value
  const points = mapSvgPoints.value
  if (!container || (!points.length && itineraryMapRoute.value.length < 2)) return
  const polyline = mapSvgPolyline.value
  const backdrop = isTrafficRouteMap.value && itineraryMapRoute.value.length < 2
    ? ''
    : '<path d="M0 25 C25 12 35 43 58 27 S82 12 100 24 M0 74 C20 60 36 88 60 69 S86 57 100 72" fill="none" stroke="#d7e8e8" stroke-width="1.2"/>'
  const labels = points.map((point) => (
    `<g><circle cx="${point.x}" cy="${point.y}" r="3.2" fill="#287ed5" stroke="#fff" stroke-width="1"/>` +
    `<text x="${point.x}" y="${point.y + 1.2}" text-anchor="middle" fill="#fff" font-size="3.2" font-weight="700">${point.index + 1}</text>` +
    `<text x="${Math.min(point.x + 4, 93)}" y="${Math.max(point.y - 3, 5)}" fill="#29485f" font-size="3.3">${escapeHtml(point.name)}</text></g>`
  )).join('')
  const lineMarkup = polyline
    ? `<polyline points="${polyline}" fill="none" stroke="url(#route-gradient-${mapRenderId})" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>`
    : ''
  const ariaLabel = isPoiDiscoveryMap.value ? '景点位置示意图' : '行程路线示意图'
  container.innerHTML = `<svg class="map-fallback-svg" viewBox="0 0 100 100" role="img" aria-label="${ariaLabel}"><defs><linearGradient id="route-gradient-${mapRenderId}" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#287ed5"/><stop offset="100%" stop-color="#31b995"/></linearGradient></defs><rect width="100" height="100" rx="5" fill="#eef6f8"/>${backdrop}${lineMarkup}${labels}</svg>`
}

async function renderItineraryMap() {
  const renderId = ++mapRenderId
  await nextTick()
  // The template is intentionally compact for the chat message loop. Update
  // its small heading after Vue mounts so saved sessions and live responses
  // both clearly distinguish a marker-only POI map from a route map.
  document.querySelectorAll('.itinerary-map-head h4').forEach((heading) => {
    heading.textContent = isPoiDiscoveryMap.value ? '景点地图' : '行程地图'
  })
  if (!hasItineraryMap.value) {
    destroyItineraryMap()
    if (mapContainer.value) {
      mapContainer.value.innerHTML = '<div class="map-empty">当前行程没有可定位的景点坐标，下面仍保留地点列表。</div>'
    }
    mapError.value = ''
    mapRenderState.value = 'idle'
    return
  }
  // The result and its v-if container are committed in separate Vue flushes
  // when a saved session is opened. Retry once in the next animation frame
  // instead of silently abandoning the map when the ref is not ready yet.
  if (!mapContainer.value) {
    window.requestAnimationFrame(() => {
      if (renderId === mapRenderId) renderItineraryMap()
    })
    return
  }
  mapRenderState.value = 'loading'
  mapError.value = ''
  // Show a route immediately while the optional Leaflet CDN is loading.
  destroyItineraryMap()
  renderMapFallback()
  try {
    const L = await loadLeaflet()
    if (renderId !== mapRenderId || !mapContainer.value) return
    destroyItineraryMap()
    mapContainer.value.replaceChildren()
    itineraryMap = L.map(mapContainer.value, { scrollWheelZoom: false })
    const points = itineraryMapPoints.value
    const route = itineraryMapRoute.value
    const routeLine = route.length > 1
      ? route.map((point) => [point.latitude, point.longitude])
      : (isTrafficRouteMap.value || isPoiDiscoveryMap.value ? [] : points.map((point) => [point.latitude, point.longitude]))
    const bounds = L.latLngBounds([...points.map((point) => [point.latitude, point.longitude]), ...routeLine])
    itineraryMap.fitBounds(bounds.pad(0.18), { maxZoom: 14 })
    const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
    })
    let tileErrorCount = 0
    tileLayer.on('tileerror', () => {
      tileErrorCount += 1
      // Do not leave a blank Leaflet canvas when the tile host is blocked.
      // The verified SVG route remains useful and does not require a network.
      if (tileErrorCount >= 1 && renderId === mapRenderId) {
        destroyItineraryMap()
        renderMapFallback()
        mapError.value = '底图暂时无法访问，已显示行程路线示意图。'
        mapRenderState.value = 'fallback'
      }
    })
    tileLayer.addTo(itineraryMap)
    const line = routeLine
    points.forEach((point, index) => {
      const coordinate = [point.latitude, point.longitude]
      const icon = L.divIcon({
        className: 'itinerary-marker',
        html: `<span>${index + 1}</span>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      })
      const day = point.day ? `第 ${point.day} 天 · ` : ''
      L.marker(coordinate, { icon }).addTo(itineraryMap)
        .bindPopup(`<b>${day}${escapeHtml(point.name)}</b><br>${escapeHtml(point.address || '')}`)
    })
    if (line.length > 1 && !isPoiDiscoveryMap.value) L.polyline(line, { color: '#287ed5', weight: 4, opacity: 0.75 }).addTo(itineraryMap)
    // Flex layouts and the scrollable chat panel can report a zero/partial
    // width during the first paint. Recalculate after both layout and fonts
    // have settled; each callback is guarded against a newer render.
    const invalidate = () => {
      if (renderId === mapRenderId) itineraryMap?.invalidateSize()
    }
    window.requestAnimationFrame(invalidate)
    window.setTimeout(invalidate, 120)
    window.setTimeout(invalidate, 500)
    mapRenderState.value = 'ready'
    mapError.value = ''
  } catch (error) {
    if (renderId !== mapRenderId) return
    destroyItineraryMap()
    renderMapFallback()
    mapError.value = error.message || '地图暂时无法加载，可使用下方地点列表。'
    mapRenderState.value = 'fallback'
  }
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]))
}

watch([itineraryMapPoints, itineraryMapRoute], renderItineraryMap, { deep: true })
// Images live inside the scrollable chat panel.  Native lazy-loading can
// incorrectly wait for a document-level viewport intersection and leave the
// cards blank until the user scrolls.  Promote rendered attraction images to
// eager loading while keeping ``decoding=async`` so text remains responsive.
watch(history, async () => {
  await nextTick()
  document.querySelectorAll('.message-attraction img[loading="lazy"]').forEach((image) => {
    image.setAttribute('loading', 'eager')
    image.setAttribute('decoding', 'async')
    image.setAttribute('referrerpolicy', 'no-referrer')
  })
}, { deep: true })
onBeforeUnmount(() => {
  mapRenderId += 1
  destroyItineraryMap()
  if (expiryTimer) window.clearInterval(expiryTimer)
  document.removeEventListener('click', handleBrowserImageClick)
  window.removeEventListener('keydown', handleBrowserPreviewKeydown)
})

const selectedScene = computed(() => scenes.value.find((item) => item.code === selected.value))
const latestAssistantIndex = computed(() => {
  for (let index = history.value.length - 1; index >= 0; index -= 1) {
    if (history.value[index]?.role === 'assistant') return index
  }
  return -1
})
const chatGuide = computed(() => ({
  TRAVEL_PLAN: '目的地 · 此刻想解决的问题（行程、住宿或当地体验）',
  POI_DISCOVERY: '目的地 · 喜欢的景点类型或体验',
  ROUTE_PLANNING: '城市 · 起点 · 终点 · 偏好的出行方式',
  BUDGET_ESTIMATION: '天数 · 人数 · 总预算或每人每日预算',
}[selected.value] || '直接告诉我你想了解的旅行问题'))
const chatPlaceholder = computed(() => ({
  TRAVEL_PLAN: '例如：杭州西湖附近有哪些酒店？也可以说想去杭州玩两天。',
  POI_DISCOVERY: '例如：郑州有哪些值得去的历史文化景点？',
  ROUTE_PLANNING: '例如：在郑州从郑州东站到河南博物院，想坐地铁。',
  BUDGET_ESTIMATION: '例如：两个人去郑州玩两天，总预算 3000 元。',
}[selected.value] || '请输入你的问题'))
const isAuthenticated = computed(() => Boolean(token.value && user.value))
const isAdmin = computed(() => user.value?.role === 'admin')
const isReady = computed(() => health.value?.status === 'ok')
const runtimeMode = computed(() => {
  if (!health.value) return '检测中'
  const mocks = Object.values(health.value.mocks || {})
  if (mocks.length && mocks.every(Boolean)) return '全量 Mock'
  if (mocks.some(Boolean)) return '混合模式'
  return '真实服务'
})

function authHeaders(extra = {}) {
  return token.value ? { Authorization: `Bearer ${token.value}`, ...extra } : extra
}

async function requestJson(url, options = {}) {
  const headers = authHeaders(options.headers || {})
  const response = await fetch(url, { ...options, headers })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(formatApiError(payload.detail) || `请求失败（HTTP ${response.status}）`)
  }
  return payload
}

function formatApiError(detail) {
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (Array.isArray(detail) && detail.length) {
    const item = detail[0]
    const field = item.loc?.at(-1)
    const labels = { username: '用户名', password: '密码', display_name: '称呼' }
    if (item.type === 'string_too_short') return `${labels[field] || '输入内容'}太短，请至少输入 ${item.ctx?.min_length || 1} 个字符。`
    if (item.type === 'string_too_long') return `${labels[field] || '输入内容'}太长，请减少内容后重试。`
    if (item.type === 'string_pattern_mismatch') return '用户名只能包含中文、字母、数字、下划线或短横线。'
    return `${labels[field] || '输入内容'}格式不正确，请检查后重试。`
  }
  return ''
}

function formatDocumentName(item) {
  const label = knowledgeCategoryLabels.value[item.sub_category] || knowledgeCategoryLabels.value[item.category] || '未分类'
  return `[${label}${item.city ? ` · ${item.city}` : ''}] ${item.file_name}`
}

function documentExpiry(item) {
  // Reading the clock keeps every rendered label reactive. The timer updates
  // it once a minute without another API request.
  const now = expiryClock.value
  if (!item?.expires_at) {
    return isRealtimeDocument(item)
      ? { label: '未设置有效期', className: 'expiry-warning', title: '该实时数据缺少过期时间，请检查分类 TTL 配置' }
      : { label: '长期有效', className: 'expiry-permanent', title: '该文档没有设置过期时间' }
  }
  const expiresAt = new Date(item.expires_at)
  if (Number.isNaN(expiresAt.getTime())) {
    return { label: '有效期未知', className: 'expiry-warning', title: String(item.expires_at) }
  }
  const remaining = expiresAt.getTime() - now
  const dateLabel = expiresAt.toLocaleString('zh-CN', { hour12: false })
  if (remaining <= 0) {
    return { label: '已过期', className: 'expiry-expired', title: `过期时间：${dateLabel}` }
  }
  const totalMinutes = Math.max(1, Math.ceil(remaining / 60000))
  const days = Math.floor(totalMinutes / 1440)
  const hours = Math.floor((totalMinutes % 1440) / 60)
  const minutes = totalMinutes % 60
  let duration = ''
  if (days > 0) duration = `${days}天${hours ? `${hours}小时` : ''}`
  else if (hours > 0) duration = `${hours}小时${minutes ? `${minutes}分钟` : ''}`
  else duration = `${minutes}分钟`
  const className = remaining <= 6 * 60 * 60 * 1000
    ? 'expiry-danger'
    : remaining <= 24 * 60 * 60 * 1000
      ? 'expiry-warning'
      : 'expiry-active'
  return { label: `剩余 ${duration}`, className, title: `过期时间：${dateLabel}` }
}

async function loadBootstrap() {
  try {
    const [scenePayload, healthPayload] = await Promise.all([
      requestJson('/api/v1/scenes'),
      requestJson('/health'),
    ])
    scenes.value = scenePayload.items
    health.value = healthPayload
    if (token.value) {
      try {
        const me = await requestJson('/api/v1/auth/me')
        if (me.user.role !== 'admin') {
          clearAuth()
          error.value = '浏览器管理端仅允许管理员登录，普通用户请使用微信小程序。'
          return
        }
        user.value = me.user
        adminTab.value = 'users'
        await loadAdminData()
      } catch {
        clearAuth()
      }
    }
  } catch (err) {
    error.value = `无法连接后端：${err.message}`
  } finally {
    booting.value = false
  }
}

function clearAuth() {
  token.value = ''
  user.value = null
  sessions.value = []
  sessionId.value = ''
  history.value = []
  removeStoredToken()
}

async function submitAuth() {
  error.value = ''
  const username = authForm.value.username.trim()
  const password = authForm.value.password
  if (!username || !password) {
    error.value = '请输入用户名和密码。'
    return
  }
  if (username.length < 3) {
    error.value = '用户名至少需要 3 个字符。'
    return
  }
  if (password.length < 8) {
    error.value = '密码至少需要 8 个字符。'
    return
  }
  loading.value = true
  try {
    const login = await requestJson('/api/v1/auth/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (login.user.role !== 'admin') throw new Error('浏览器管理端仅允许管理员登录。')
    token.value = login.access_token
    writeStoredToken(token.value)
    user.value = login.user
    adminTab.value = 'users'
    await loadAdminData()
    authForm.value = { username: '', password: '' }
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function logout() {
  try {
    if (token.value) await requestJson('/api/v1/auth/logout', { method: 'POST' })
  } catch {
    // 服务暂不可用时也清理本地凭证，避免继续使用过期会话。
  }
  activeRequest.value?.controller.abort()
  clearAuth()
}

async function loadSessions(sceneCode = selected.value) {
  const payload = await requestJson(`/api/v1/chat/sessions?scene_code=${encodeURIComponent(sceneCode)}`)
  if (sceneCode === selected.value) sessions.value = payload.items || []
}

async function deleteCurrentSession() {
  if (!sessionId.value || !window.confirm('确定删除当前会话吗？会话消息也会一并删除。')) return
  try {
    await requestJson(`/api/v1/chat/sessions/${sessionId.value}`, { method: 'DELETE' })
    resetConversation()
    await loadSessions()
  } catch (err) { error.value = err.message }
}

function showWelcome(sceneCode) {
  const scene = scenes.value.find((item) => item.code === sceneCode)
  history.value = scene?.welcome_message ? [{ role: 'assistant', content: scene.welcome_message, welcome: true }] : []
}

function normaliseStoredMessage(value) {
  return String(value || '')
    .replace(/\r\n?/g, '\n')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*•]\s+/gm, '• ')
    .replace(/^(\s*\d+)[.)、]\s*/gm, '$1. ')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\(https?:\/\/[^)\s]+\)/gi, '$1')
}

function messageRows(rows) {
  // Public-search URLs are removed by the API; keep source titles as a
  // non-linkable grounding label alongside the synthesized answer.
  return (rows || []).map((row) => ({
    role: row.role,
    content: row.role === 'assistant' ? normaliseStoredMessage(row.content) : row.content,
    citations: row.metadata?.citations || [],
    result: row.metadata?.result,
  }))
}

function normalizeResultPayload(payload) {
  if (!payload || typeof payload !== 'object' || !payload.result || typeof payload.result !== 'object') return payload
  if (payload.result.map) return payload
  const pois = Array.isArray(payload.result.pois) ? payload.result.pois : []
  return {
    ...payload,
    result: {
      ...payload.result,
      // Older saved responses did not include the map envelope. Reconstruct
      // it from POI coordinates so those sessions still render a map.
      map: { provider: 'OpenStreetMap', points: pois },
    },
  }
}

async function openSession(item) {
  if (loading.value) return
  error.value = ''
  try {
    const payload = await requestJson(`/api/v1/chat/sessions/${item.session_id}`)
    sessionId.value = payload.session_id
    if (payload.scene_code !== selected.value) throw new Error('该会话不属于当前功能')
    const latest = [...(payload.messages || [])].reverse().find((row) => row.role === 'assistant')
    result.value = latest?.metadata?.result
      ? normalizeResultPayload({ result: latest.metadata.result })
      : null
    history.value = messageRows(payload.messages)
  } catch (err) {
    error.value = err.message
  }
}

function resetConversation() {
  activeRequest.value?.controller.abort()
  activeRequest.value = null
  loading.value = false
  sessionId.value = ''
  result.value = null
  error.value = ''
  message.value = ''
  showWelcome(selected.value)
}

async function selectScene(sceneCode) {
  selected.value = sceneCode
  sessions.value = []
  resetConversation()
  await loadSessions(sceneCode)
}

async function ensureSession() {
  if (!sessionId.value) {
    const session = await requestJson(`/api/v1/chat/sessions?scene_code=${encodeURIComponent(selected.value)}`, { method: 'POST' })
    sessionId.value = session.session_id
    await loadSessions()
  }
  return sessionId.value
}

async function consumeEventStream(response, onEvent) {
  if (!response.body) throw new Error('浏览器不支持流式响应')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      let eventName = 'message'
      const dataLines = []
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim()
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (dataLines.length) onEvent(eventName, JSON.parse(dataLines.join('\n')))
      boundary = buffer.indexOf('\n\n')
    }
    if (done) break
  }
}

async function submit() {
  const content = message.value.trim()
  if (!content || loading.value || !isAuthenticated.value) return
  error.value = ''
  loading.value = true
  history.value.push({ role: 'user', content })
  let assistantIndex = -1
  let streamCompleted = false
  const controller = new AbortController()
  const requestToken = Symbol('chat-request')
  activeRequest.value = { controller, requestToken }
  try {
    const id = await ensureSession()
    const response = await fetch(`/api/v1/chat/sessions/${id}/messages/stream`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      signal: controller.signal,
      body: JSON.stringify({ scene_code: selected.value, message: content, parameters: {} }),
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(payload.detail || `请求失败（HTTP ${response.status}）`)
    }
    await consumeEventStream(response, (eventName, payload) => {
      if (eventName === 'progress') {
        if (assistantIndex === -1) {
          history.value.push({ role: 'assistant', content: '', citations: [], streaming: true, progressOnly: true })
          assistantIndex = history.value.length - 1
        }
        const fact = payload.message || ''
        if (fact) {
          if (history.value[assistantIndex].progressOnly && history.value[assistantIndex].content) history.value[assistantIndex].content += '\n'
          history.value[assistantIndex].content += fact
        }
        history.value[assistantIndex].progressOnly = true
      } else if (eventName === 'token') {
        if (assistantIndex === -1) {
          history.value.push({ role: 'assistant', content: '', citations: [], streaming: true })
          assistantIndex = history.value.length - 1
        }
        if (history.value[assistantIndex].progressOnly) {
          history.value[assistantIndex].content = ''
          history.value[assistantIndex].progressOnly = false
        }
        history.value[assistantIndex].content += payload.token || ''
      } else if (eventName === 'done') {
        streamCompleted = true
        result.value = normalizeResultPayload(payload)
        if (assistantIndex === -1) {
          history.value.push({ role: 'assistant', content: '', citations: [] })
          assistantIndex = history.value.length - 1
        }
        history.value[assistantIndex].content = payload.answer || ''
        history.value[assistantIndex].citations = payload.citations || []
        history.value[assistantIndex].result = payload.result
        history.value[assistantIndex].streaming = false
        history.value[assistantIndex].progressOnly = false
      } else if (eventName === 'error') {
        throw new Error(payload.detail || '对话处理失败')
      }
    })
    if (!streamCompleted) throw new Error('流式响应意外中断')
    message.value = ''
    await loadSessions()
  } catch (err) {
    if (err.name !== 'AbortError') {
      error.value = err.message
      if (assistantIndex !== -1) history.value[assistantIndex].streaming = false
    }
  } finally {
    if (activeRequest.value?.requestToken === requestToken) {
      activeRequest.value = null
      loading.value = false
    }
  }
}

function newConversation() { resetConversation() }

async function loadAdminData() {
  if (!isAdmin.value) return
  adminBusy.value = true
  try {
    const [users, docs, categories] = await Promise.all([
      requestJson('/api/v1/admin/users'),
      requestJson('/api/v1/admin/knowledge/documents'),
      requestJson('/api/v1/knowledge/categories'),
    ])
    adminUsers.value = users.items || []
    documents.value = docs.items || []
    knowledgeCategories.value = categories.items || []
    userPage.value = 1
    documentPage.value = 1
    if (!uploadCategory.value) {
      uploadCategory.value = uploadKnowledgeCategoryOptions.value[0]?.code || ''
    }
  } catch (err) {
    error.value = err.message
  } finally {
    adminBusy.value = false
  }
}

async function createManagedUser() {
  if (!adminForm.value.username || !adminForm.value.password) return
  adminBusy.value = true
  try {
    await requestJson('/api/v1/admin/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...adminForm.value, display_name: adminForm.value.display_name || null }) })
    adminForm.value = { username: '', password: '', display_name: '' }
    await loadAdminData()
  } catch (err) {
    error.value = err.message
  } finally {
    adminBusy.value = false
  }
}

async function toggleUser(item) {
  try {
    await requestJson(`/api/v1/admin/users/${item.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: !item.is_active }) })
    await loadAdminData()
  } catch (err) { error.value = err.message }
}

function onFileChange(event) { selectedFile.value = event.target.files?.[0] || null }

async function uploadDocument() {
  if (!selectedFile.value) return
  adminBusy.value = true
  try {
    const form = new FormData()
    form.append('file', selectedFile.value)
    if (uploadSourceUrl.value.trim()) form.append('source_url', uploadSourceUrl.value.trim())
    form.append('category', uploadCategory.value)
    if (uploadCity.value.trim()) form.append('city', uploadCity.value.trim())
    await requestJson('/api/v1/admin/knowledge/documents', { method: 'POST', body: form })
    selectedFile.value = null
    uploadSourceUrl.value = ''
    uploadCategory.value = uploadKnowledgeCategoryOptions.value[0]?.code || ''
    uploadCity.value = ''
    if (fileInput.value) fileInput.value.value = ''
    await loadAdminData()
  } catch (err) { error.value = err.message }
  finally { adminBusy.value = false }
}

async function publishDocument(item) {
  try {
    await requestJson(`/api/v1/admin/knowledge/documents/${item.id}/publish`, { method: 'POST' })
    await loadAdminData()
  } catch (err) { error.value = err.message }
}

async function deleteDocument(item) {
  if (!window.confirm(`确定删除“${formatDocumentName(item)}”吗？删除后不可恢复。`)) return
  try {
    await requestJson(`/api/v1/admin/knowledge/documents/${item.id}`, { method: 'DELETE' })
    if (editingDocument.value?.id === item.id) {
      editingDocument.value = null
      editingContent.value = ''
    }
    await loadAdminData()
  } catch (err) { error.value = err.message }
}

async function editDocument(item) {
  try {
    const payload = await requestJson(`/api/v1/admin/knowledge/documents/${item.id}`)
    editingDocument.value = { ...(payload.metadata || {}), ...payload }
    editingContent.value = payload.content || ''
    editingMode.value = 'view'
  } catch (err) { error.value = err.message }
}

async function saveDocumentEdit() {
  if (!editingDocument.value || !editingContent.value.trim()) return
  adminBusy.value = true
  try {
    await requestJson(`/api/v1/admin/knowledge/documents/${editingDocument.value.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: editingContent.value }),
    })
    editingDocument.value = null
    editingContent.value = ''
    await loadAdminData()
  } catch (err) { error.value = err.message }
  finally { adminBusy.value = false }
}

function selectAdminTab(tab) {
  adminTab.value = tab
  if (tab === 'users') {
    editingDocument.value = null
    editingContent.value = ''
  }
}

onMounted(() => {
  document.addEventListener('click', handleBrowserImageClick)
  window.addEventListener('keydown', handleBrowserPreviewKeydown)
  expiryTimer = window.setInterval(() => { expiryClock.value = Date.now() }, 60000)
})
onMounted(loadBootstrap)
</script>

<template>
  <main class="page">
    <div v-if="booting" class="auth-card"><p>正在连接 DeepTravel…</p></div>
    <template v-else-if="!isAuthenticated">
      <section class="auth-shell">
        <div class="auth-intro">
          <p class="eyebrow">DEEPTRAVEL ADMIN</p>
          <h1>DeepTravel 管理后台</h1>
          <p>浏览器端仅供系统管理员使用，用于维护旅游知识库和管理账号。普通旅行用户请在微信小程序注册和登录。</p>
          <div class="auth-points"><span>知识库分类</span><span>文档维护</span><span>用户管理</span></div>
        </div>
        <form class="auth-card" @submit.prevent="submitAuth">
          <p class="eyebrow">管理员入口</p>
          <h2>登录管理后台</h2>
          <label>管理员账号<input v-model="authForm.username" autocomplete="username" minlength="3" maxlength="64" required placeholder="请输入管理员账号" /></label>
          <label>密码<input v-model="authForm.password" type="password" autocomplete="current-password" minlength="8" maxlength="128" required placeholder="请输入管理员密码" /></label>
          <button class="primary full" type="submit" :disabled="loading">{{ loading ? '正在验证…' : '登录管理后台' }}</button>
          <p class="hint">普通用户请前往微信小程序。</p>
          <p v-if="error" class="error">{{ error }}</p>
        </form>
      </section>
    </template>
    <template v-else>
      <header class="hero"><div><p class="eyebrow">DEEPTRAVEL ADMIN</p><h1>系统管理后台</h1><p>管理旅游知识库和用户账号。</p></div><div class="account"><span class="avatar">{{ (user.display_name || user.username).slice(0, 1) }}</span><span>{{ user.display_name || user.username }}</span><button class="text-button" type="button" @click="logout">退出</button></div></header>
      <div class="top-actions"><div class="health"><span :class="['status-dot', { ready: isReady }]" />{{ isReady ? '服务正常' : '服务待检查' }} · {{ runtimeMode }}</div></div>
      <nav v-if="isAdmin" class="admin-primary-tabs panel" aria-label="管理员功能"><button type="button" :class="{ active: adminTab === 'users' }" @click="selectAdminTab('users')">用户管理</button><button type="button" :class="{ active: adminTab === 'documents' }" @click="selectAdminTab('documents')">知识库管理</button></nav>
      <section v-if="isAdmin" class="admin-overview" aria-label="管理数据概览"><article><span>用户总数</span><strong>{{ adminUsers.length }}</strong><small>已创建账号</small></article><article><span>正常用户</span><strong>{{ activeUserCount }}</strong><small>当前可登录</small></article><article><span>正式知识</span><strong>{{ readyDocumentCount }}</strong><small>已参与检索</small></article><article><span>待发布</span><strong>{{ reviewingDocumentCount }}</strong><small>需要管理员处理</small></article></section>
      <div v-if="sessionId && !isAdmin" class="session-delete-bar"><button class="text-button danger" type="button" @click="deleteCurrentSession">删除当前会话</button></div>
      <section v-if="isAdmin && adminTab === 'users'" class="admin-panel panel"><div class="admin-head"><div><h2>用户管理</h2><p>创建普通用户账号，并查看、启用或停用已有用户。</p></div></div><div class="admin-content"><form class="inline-form" @submit.prevent="createManagedUser"><input v-model="adminForm.username" placeholder="新用户名" /><input v-model="adminForm.display_name" placeholder="称呼" /><input v-model="adminForm.password" type="password" placeholder="初始密码（至少 8 位）" /><span class="admin-note">新建账号均为普通用户（管理员账号仅此一个）</span><button class="primary" type="submit" :disabled="adminBusy">创建用户</button></form><div class="table-wrap"><table><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>创建时间</th><th /></tr></thead><tbody><tr v-for="item in pagedAdminUsers" :key="item.id"><td><b>{{ item.display_name }}</b><small>{{ item.username }}</small></td><td>{{ item.role === 'admin' ? '管理员（唯一）' : '普通用户' }}</td><td><span :class="['badge', item.is_active ? 'ok' : 'off']">{{ item.is_active ? '正常' : '已停用' }}</span></td><td>{{ item.created_at ? new Date(item.created_at).toLocaleDateString() : '-' }}</td><td><button class="small-button" :disabled="item.id === user.id" @click="toggleUser(item)">{{ item.is_active ? '停用' : '启用' }}</button></td></tr></tbody></table><p v-if="!adminUsers.length" class="empty">暂无用户信息。</p></div><div v-if="adminUsers.length" class="knowledge-pagination"><span>共 {{ adminUsers.length }} 条，每页 {{ USER_PAGE_SIZE }} 条</span><div><button class="small-button" type="button" :disabled="userPage <= 1" @click="userPage -= 1">上一页</button><span class="page-indicator">第 {{ userPage }} / {{ userPageCount }} 页</span><button class="small-button" type="button" :disabled="userPage >= userPageCount" @click="userPage += 1">下一页</button></div></div></div><p v-if="error" class="error">{{ error }}</p></section>
      <section v-else class="layout"><aside class="panel scenes"><div class="panel-title"><h2>聊天与顾问</h2><button class="text-button" type="button" @click="newConversation">新会话</button></div><button v-for="scene in scenes" :key="scene.code" :class="['scene', { active: selected === scene.code }]" type="button" @click="selectScene(scene.code)"><span>{{ scene.name }}</span><small>{{ scene.description }}</small></button><div class="session-heading"><h3>{{ selectedScene?.name || '当前功能' }}会话</h3><button class="text-button" @click="loadSessions">刷新</button></div><button v-for="item in sessions" :key="item.session_id" :class="['session-item', { active: sessionId === item.session_id }]" type="button" @click="openSession(item)"><b>{{ item.title || '新会话' }}</b><small>{{ item.preview || '尚未发送消息' }}</small></button><p v-if="!sessions.length" class="empty">发送第一句话后，会话会保存在当前功能中。</p><div v-if="health" class="config-card"><b>服务状态</b><span>{{ runtimeMode }}</span><small>数据库 {{ health.database?.connected ? '已连接' : '未连接' }}</small><small>DeepSeek {{ health.configuration?.deepseek ? '已配置' : '未配置' }}</small><small>高德 MCP {{ health.configuration?.amap_mcp ? '已配置' : '未配置' }}</small><small>12306 MCP {{ health.configuration?.railway_mcp ? '已配置' : '未配置' }}</small><small>联网搜索 {{ health.configuration?.search_mcp ? '已配置' : '未配置' }}</small></div></aside><section class="panel workspace"><div class="workspace-head"><div><h2>{{ selectedScene?.name || '旅行助手' }}</h2><p>{{ selectedScene?.description }}</p></div><code>{{ selected }}</code></div><div v-if="history.length" class="conversation" aria-live="polite"><article v-for="(item, index) in history" :key="index" :class="['message', item.role]"><small>{{ item.role === 'user' ? '你' : selectedScene?.name || 'DeepTravel' }} {{ item.streaming ? '· 正在生成' : '' }}</small><template v-for="(part, partIndex) in messageContentParts(item)" :key="`${index}-${partIndex}`"><p v-if="part.type === 'text'">{{ part.text }}</p><div v-else class="message-attraction"><div class="attraction-copy"><b>{{ part.poi.name }}</b><span v-if="part.poi.day">第 {{ part.poi.day }} 天</span><p v-if="part.poi.description">{{ part.poi.description }}</p></div><div class="image-grid"><figure v-for="image in part.poi.images" :key="image.photo"><img :src="image.imageSrc" :alt="part.poi.name" loading="lazy" @error="recoverImage($event, image)" /><figcaption>{{ part.poi.name }}</figcaption></figure></div></div></template><div v-if="item.role === 'assistant' && item.result && index === latestAssistantIndex && hasItineraryMap" class="message-itinerary-map"><div class="itinerary-map-head"><h4>行程地图</h4><small>{{ itineraryMapCaption }}</small></div><div :ref="setMapContainer" class="map-canvas"></div><p v-if="mapError" class="map-fallback">{{ mapError }}</p><div class="map-place-list"><span v-for="(point, pointIndex) in itineraryMapPoints" :key="point.name + '-' + point.location"><b>{{ pointIndex + 1 }}</b>{{ point.name }}</span></div></div><div v-if="item.citations?.length" class="citations"><a v-for="(citation, citationIndex) in item.citations" :key="citation.chunk_id || citation.url || citationIndex" :href="citation.url || undefined" :target="citation.url ? '_blank' : undefined" rel="noreferrer">[{{ citationIndex + 1 }}] {{ citation.title }}</a></div></article></div><div class="chat-hint"><span>可以从这些信息开始聊：</span>{{ chatGuide }}</div><label class="composer-label" for="travel-message">{{ loading ? '顾问正在回复…' : '说说你的旅行想法' }}</label><textarea id="travel-message" v-model="message" rows="4" :placeholder="chatPlaceholder" @keydown.meta.enter="submit" @keydown.ctrl.enter="submit" /><div class="composer-actions"><span class="send-tip">按 ⌘/Ctrl + Enter 发送</span><button class="primary" type="button" :disabled="loading || !message.trim()" @click="submit">{{ loading ? '正在回复…' : '发送' }}</button></div><p v-if="error" class="error">{{ error }}</p><article v-if="result?.result" class="structured-result"><h3>本次回答摘要</h3><div v-if="result.result.days_plan" class="days"><div v-for="day in result.result.days_plan" :key="day.day" class="day"><b>第 {{ day.day }} 天</b><span>{{ day.activities.join(' · ') }}</span></div></div><div v-if="result.result.pois" class="chips"><span v-for="poi in result.result.pois" :key="poi.name">{{ poi.name }}</span></div><div v-if="result.result.breakdown" class="days"><div v-for="(amount, category) in result.result.breakdown" :key="category" class="day"><b>{{ category }}</b><span>{{ amount }} CNY</span></div></div><div v-if="result.result.mode" class="day"><b>{{ result.result.mode }}</b><span>预计 {{ result.result.duration_minutes }} 分钟</span></div></article></section></section>
    </template>
    <section v-if="isAdmin && adminTab === 'documents' && !editingDocument" class="panel knowledge-categories-panel">
      <div class="admin-section-head"><div><p class="section-kicker">KNOWLEDGE BASE</p><h2>知识库管理</h2><p>按分类维护旅游文档，实时资讯到期后将自动停止参与 RAG 检索。</p></div><div class="knowledge-summary"><span>{{ managedDocuments.length }} 条文档</span><span v-if="realtimeDocumentCount" class="realtime-count">{{ realtimeDocumentCount }} 条实时数据</span><span v-if="expiringSoonDocumentCount" class="expiring-count">{{ expiringSoonDocumentCount }} 条即将过期</span></div></div>
      <label class="knowledge-upload-category">上传文档分类 <select v-model="uploadCategory"><option v-for="item in uploadKnowledgeCategoryOptions" :key="item.code" :value="item.code">{{ item.name }}</option></select></label>
      <div class="upload-box"><input ref="fileInput" type="file" accept=".pdf,.docx,.md,.txt,.html,.htm,.csv" @change="onFileChange" /><input v-model="uploadCity" placeholder="城市（可选）" /><input v-model="uploadSourceUrl" placeholder="来源链接（可选）" /><button class="primary" :disabled="adminBusy || !selectedFile" @click="uploadDocument">上传并向量化</button></div>
      <nav class="knowledge-tabs" aria-label="知识分类筛选"><button v-for="item in knowledgeCategoryOptions" :key="item.code" :class="['knowledge-tab', `depth-${item.depth}`, { active: selectedKnowledgeCategory === item.code }]" @click="selectedKnowledgeCategory = item.code">{{ item.depth > 1 ? '› ' : '' }}{{ item.name }}</button></nav>
      <div class="category-documents"><article v-for="item in pagedVisibleDocuments" :key="`category-${item.id}`" :class="['admin-item', 'document-card', { 'document-expired': documentExpiry(item).className === 'expiry-expired' }]"><div class="document-main"><b>{{ item.file_name }}</b><div class="document-tags"><span>{{ knowledgeCategoryLabels[item.sub_category] || knowledgeCategoryLabels[item.category] || '未分类' }}</span><span v-if="item.city">{{ item.city }}</span><span v-if="isRealtimeDocument(item)" class="realtime-tag">实时数据</span><span :class="['badge', item.status === 'READY' ? 'ok' : 'off']">{{ item.status }}</span><span>{{ item.chunk_count || 0 }} 个分片</span><span :class="['expiry-badge', documentExpiry(item).className]" :title="documentExpiry(item).title">{{ documentExpiry(item).label }}</span></div><p v-if="item.preview" class="document-preview">{{ item.preview }}</p></div><div class="document-actions"><button class="small-button" @click="editDocument(item)">查看/编辑</button><button v-if="item.status === 'REVIEWING'" class="small-button" @click="publishDocument(item)">发布</button><button class="small-button danger" @click="deleteDocument(item)">删除</button></div></article><p v-if="!visibleDocuments.length" class="empty">该分类暂无文档。</p></div>
      <div v-if="visibleDocuments.length" class="knowledge-pagination"><span>共 {{ visibleDocuments.length }} 条，每页 {{ DOCUMENT_PAGE_SIZE }} 条</span><div><button class="small-button" type="button" :disabled="documentPage <= 1" @click="documentPage -= 1">上一页</button><span class="page-indicator">第 {{ documentPage }} / {{ documentPageCount }} 页</span><button class="small-button" type="button" :disabled="documentPage >= documentPageCount" @click="documentPage += 1">下一页</button></div></div>
      <p class="knowledge-note">状态为 REVIEWING 的管理员文档需要发布后才会参与检索；实时数据到期后会自动从 RAG 检索中排除，管理员仍可查看、编辑或删除。</p>
    </section>
    <section v-if="isAdmin && adminTab === 'documents' && editingDocument" class="panel knowledge-editor-page">
      <div class="workspace-head"><div><button class="text-button" type="button" @click="editingDocument = null">← 返回知识库分类</button><h2>编辑知识文档</h2><p>{{ formatDocumentName(editingDocument) }}</p></div><span class="badge ok">{{ editingDocument.status }}</span></div>
      <div class="editor-meta"><span>分类：{{ knowledgeCategoryLabels[editingDocument.sub_category] || knowledgeCategoryLabels[editingDocument.category] || '未分类' }}</span><span>城市：{{ editingDocument.city || '未指定' }}</span><span>来源：{{ editingDocument.source || editingDocument.source_url || '管理员上传' }}</span><span :class="['expiry-badge', documentExpiry(editingDocument).className]" :title="documentExpiry(editingDocument).title">有效期：{{ documentExpiry(editingDocument).label }}</span></div>
      <div class="editor-toolbar"><span class="editor-label">文档内容</span><div><button class="small-button" :class="{ active: editingMode === 'view' }" type="button" @click="editingMode = 'view'">阅读</button><button class="small-button" :class="{ active: editingMode === 'edit' }" type="button" @click="editingMode = 'edit'">编辑</button></div></div>
      <article v-if="editingMode === 'view'" class="document-reader"><div v-for="(block, index) in formattedDocumentBlocks" :key="index" :class="['reader-block', `reader-${block.type}`, `reader-level-${block.level || 0}`]">{{ block.text }}</div><p v-if="!formattedDocumentBlocks.length" class="empty">暂无文档内容。</p></article>
      <textarea v-else id="knowledge-editor-content" v-model="editingContent" rows="24" />
      <div class="editor-actions"><button class="small-button" type="button" @click="editingDocument = null">返回分类</button><button v-if="editingMode === 'view'" class="primary" type="button" @click="editingMode = 'edit'">编辑文档</button><button v-else class="primary" :disabled="adminBusy || !editingContent.trim()" @click="saveDocumentEdit">保存并重新向量化</button></div>
    </section>
    <div v-if="browserPreviewCurrent" class="image-preview-overlay" role="dialog" aria-modal="true" aria-label="图片预览" @click.self="closeBrowserImagePreview"><button class="image-preview-close" type="button" aria-label="关闭预览" @click="closeBrowserImagePreview">×</button><button v-if="browserPreviewImages.length > 1" class="image-preview-arrow previous" type="button" aria-label="上一张" @click="moveBrowserImagePreview(-1)">‹</button><img :src="browserPreviewCurrent" alt="景点大图" /><button v-if="browserPreviewImages.length > 1" class="image-preview-arrow next" type="button" aria-label="下一张" @click="moveBrowserImagePreview(1)">›</button><span>{{ browserPreviewIndex + 1 }} / {{ browserPreviewImages.length }}</span></div>
  </main>
</template>
