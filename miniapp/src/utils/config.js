// 模拟器和真机统一通过电脑当前局域网地址访问后端。
// 开发时可通过 `VITE_API_BASE_URL=... npm run build:mp-weixin` 覆盖，
// 避免把正式域名或另一台开发电脑的地址写死在业务代码中。
// 当前电脑在本网络中的地址为 192.168.2.5；后端监听这个精确地址。
const configuredApiUrl = String(import.meta.env.VITE_API_BASE_URL || '').trim()
export const API_BASE_URL = (configuredApiUrl || 'http://192.168.2.5:8000').replace(/\/$/, '')

export const STORAGE_KEYS = {
  token: 'deeptravel_token',
  user: 'deeptravel_user',
}
