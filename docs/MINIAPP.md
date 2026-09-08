# DeepTravel 微信小程序用户端

`miniapp/` 是独立的 uni-app 用户端，使用微信小程序原生组件风格实现聊天、四个旅行功能、短期会话、景点图片和地图。现有 `frontend/` 保留为管理员 Web 端，不会被小程序构建覆盖。

## 运行前配置

编辑 [`miniapp/src/utils/config.js`](../miniapp/src/utils/config.js)，将 `API_BASE_URL` 设置为后端地址：

```js
export const API_BASE_URL = 'https://your-api.example.com'
```

本地真机调试时，电脑和手机需要在同一局域网，例如 `http://192.168.1.20:8000`。微信开发者工具可以临时勾选“不校验合法域名、TLS 版本及 HTTPS 证书”；正式发布必须把 HTTPS 后端域名加入小程序的 `request 合法域名`，图片代理域名也必须可访问。

项目已在 `manifest.json` 开启 `useLanDebug`，构建后的
`project.config.json` 和 `project.private.config.json` 也会保持为 `true`，因此
“真机调试”会通过局域网连接电脑。若按钮没有反应，请重新导入最新构建目录，
确认手机与电脑连接同一 Wi-Fi，并在开发者工具右上角重新扫码登录与点击“编译”。

## 安装与构建

```bash
cd miniapp
npm install

# 微信小程序开发构建
npm run dev:mp-weixin

# 生成上传目录
npm run build:mp-weixin
```

然后在微信开发者工具中打开 `miniapp/dist/dev/mp-weixin`（开发构建）或 `miniapp/dist/build/mp-weixin`（发布构建）。首次使用请在 `manifest.json` 的 `mp-weixin.appid` 填入你的小程序 AppID；无 AppID 时可使用测试号或开发者工具提供的临时 AppID。

## 与后端接口的对应关系

| 小程序能力 | 后端接口 |
| --- | --- |
| 注册/普通用户登录/微信登录/退出 | `/api/v1/auth/register`、`/api/v1/auth/user/login`、`/api/v1/auth/wechat/login`、`/api/v1/auth/logout` |
| 账号管理（普通账号修改自己的密码） | `PATCH /api/v1/auth/me/password` |
| 四个功能与欢迎语 | `/api/v1/scenes` |
| 当前功能会话列表 | `/api/v1/chat/sessions?scene_code=...` |
| 所有功能的历史会话 | `/api/v1/chat/sessions/all` |
| 打开会话 | `/api/v1/chat/sessions/{id}` |
| 删除自己的会话 | `DELETE /api/v1/chat/sessions/{id}` |
| 流式聊天 | `/api/v1/chat/sessions/{id}/messages/stream` |
| 景点图片代理 | `/api/v1/media/amap-image` |

微信基础库支持 `requestTask.onChunkReceived` 时，小程序会解析后端 SSE 的 `progress`、`token`、`done` 和 `error` 事件；不支持分块回调的旧客户端仍能保留普通请求兜底，显示完整回答。

## 页面说明

- `src/pages/index/index.vue`：用户登录和注册。
- `src/pages/home/home.vue`：四个旅行功能入口和热门城市几日游。
- `src/pages/chat/chat.vue`：微信聊天框布局，支持行程规划、景点查询、路线交通规划、费用估算四个 Agent；会话按功能隔离。
- `src/pages/profile/profile.vue`：用户资料、旅行头像选择、历史会话（查看、继续、删除）、账号管理（普通账号修改密码）和退出登录。微信登录账号点击账号管理会提示无法修改密码。头像按账号保存在当前小程序设备，并同步显示在首页与用户聊天气泡中。

管理员仍使用现有 Web 管理端上传、编辑和删除知识库文档，并通过 `/api/v1/auth/admin/login` 登录；小程序不会暴露管理员操作入口。管理员账号在小程序会被拒绝，普通用户账号在 Web 管理端也会被拒绝。

## 微信登录配置

小程序登录页提供“微信一键登录”。点击后由微信返回一次性 `code`，后端调用微信
`jscode2session` 换取用户标识，并自动创建（或复用）普通用户账号，随后签发
DeepTravel 会话 token。微信的 `session_key` 只在服务端短暂使用，不会返回给小程序，
也不会写入知识库或业务表。

在后端 `.env` 中配置微信公众平台的小程序凭证：

```text
WECHAT_APP_ID=你的小程序 AppID
WECHAT_APP_SECRET=你的小程序 AppSecret
WECHAT_LOGIN_TIMEOUT_SECONDS=10
```

未配置凭证时，接口会返回明确的配置提示，不会伪造登录成功。微信开发者工具中还需
在 `manifest.json` 的 `mp-weixin.appid` 填写真实 AppID；本地调试可按开发者工具提示
关闭合法域名校验，正式发布时请配置 HTTPS 合法域名。

## 模拟器启动失败排查

请在微信开发者工具中导入构建目录，而不是在终端直接执行目录路径：

```text
miniapp/dist/build/mp-weixin
```

如果提示 `access_token missing`、`access_token expired` 或“需要重新登录”，请点击
开发者工具右上角头像重新扫码登录，再点击“编译”。当前 `project.config.json` 中的
`touristappid` 只是没有真实 AppID 时的开发占位值；要使用微信登录和真机调试，必须将
`miniapp/src/manifest.json` 的 `mp-weixin.appid` 改为真实小程序 AppID 后重新构建。

若使用开发者工具 CLI 打开项目，还需在“设置 → 安全设置”开启“服务端口”；直接从 GUI
导入项目则不需要开启该端口。

开启服务端口后，也可以用 CLI 生成真机预览二维码（GUI 按钮无响应时使用）：

```bash
/Applications/wechatwebdevtools.app/Contents/MacOS/cli preview \
  --project /Users/liu123/Desktop/deeptravel-agent_副本/miniapp/dist/build/mp-weixin \
  --qr-format image \
  --qr-output /tmp/deeptravel-preview.png
```
