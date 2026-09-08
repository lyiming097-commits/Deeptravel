export const USER_AVATARS = [
  { id: 'traveler', symbol: '旅', name: '旅行家', tone: 'teal' },
  { id: 'panda', symbol: '🐼', name: '熊猫', tone: 'green' },
  { id: 'whale', symbol: '🐳', name: '小鲸鱼', tone: 'blue' },
  { id: 'mountain', symbol: '⛰', name: '远山', tone: 'slate' },
  { id: 'sunflower', symbol: '🌻', name: '向日葵', tone: 'amber' },
  { id: 'moon', symbol: '🌙', name: '月亮', tone: 'violet' },
]

function storageKey(user) {
  const identity = user?.id || user?.username || 'guest'
  return `deeptravel_user_avatar:${identity}`
}

function fallbackAvatar(user) {
  return {
    id: 'initial',
    symbol: String(user?.display_name || user?.username || '旅').slice(0, 1),
    name: '默认头像',
    tone: 'coral',
  }
}

export function loadUserAvatar(user) {
  try {
    const id = uni.getStorageSync(storageKey(user))
    return USER_AVATARS.find((item) => item.id === id) || fallbackAvatar(user)
  } catch {
    return fallbackAvatar(user)
  }
}

export function saveUserAvatar(user, avatarId) {
  const avatar = USER_AVATARS.find((item) => item.id === avatarId)
  if (!avatar) return loadUserAvatar(user)
  try { uni.setStorageSync(storageKey(user), avatar.id) } catch { /* use in-memory selection */ }
  return avatar
}
