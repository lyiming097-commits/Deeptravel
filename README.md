# DeepTravel 智能旅游助手

基于 Python、DeepSeek、RAG、PostgreSQL/PGVector、LangGraph 和 MCP 的本地全栈项目。前端采用 Vite + Vue 3，后端采用 FastAPI；地图数据通过高德远程 MCP Streamable HTTP 获取，联网搜索默认使用 DuckDuckGo，Tavily 可作为可选 Provider。

## 当前能力

- PostgreSQL 17 + pgvector 持久化会话、消息、知识文档和向量分片。
- PDF、DOCX、Markdown、TXT、HTML 和 CSV 文档解析、分片、去重、知识库管理。
- 仅检索 `READY` 且启用的知识文档，并返回可回溯的来源引用。
- DeepSeek 对话客户端、高德标准 MCP Streamable HTTP Provider 和 Search MCP DuckDuckGo/Tavily 适配器。
- Ollama + Qwen3-Embedding-0.6B 本地语义向量化（1024 维）。
- DeepSeek、高德和搜索支持独立 Mock 开关，可分阶段接入真实服务。
- 四个独立 LangGraph 专项 Agent，包含工具白名单、调用上限、总超时和可审计执行摘要。
- 四个 Agent 均有明确的旅行顾问角色和证据优先级，缺少可靠观测时明确说明不确定性，不凭空编造事实。
- 用户切换业务场景后会先看到对应顾问的自我介绍；对话回答通过 SSE 增量流式返回，工具检索在后台异步执行。
- 用户和管理员分离：用户只能查看、继续和保存自己的聊天会话；管理员可管理用户、上传、编辑和删除旅游知识。
- 登录后采用微信/QQ 类聊天框，四个功能都通过一个自然语言输入框交流，不需要逐项填写目的地、天数、人数或预算。
- 四个功能各自拥有独立会话列表；每次请求只携带该功能最近一小段对话作为短期记忆，不会把长期全部聊天记录注入模型。
- 每次问询都可通过 Search MCP 搜索、HTTPX/Playwright 两级抓取、BeautifulSoup/Trafilatura 清洗，再用 Qwen3 Embedding 重排，并将临时 Top-K 正文证据交给大模型综合回答；聊天页面不返回公网链接列表。
- 每个 Agent 先由 DeepSeek 识别行程、景点、交通、住宿、美食、购物、预算、天气等意图，模型不可用时才使用确定性规则兜底。
- 住宿与本地生活查询支持任意地标实体：从自然语言提取“西溪湿地”、“灵隐寺”、“外滩”等区域，并通过高德 MCP POI 校准，不依赖固定区域词库。
- 公网搜索结果在当前请求中搜索、抓取、分片、向量化和重排；每次仅将语义最相近的 1–2 条正文直接保存为 `READY` PGVector，管理员可查看、编辑和删除。

详细说明见 [Agent 与工具层架构](docs/AGENT_ARCHITECTURE.md) 和 [项目实现状态](docs/PROJECT_STATUS.md)。

## 四个专项 Agent

| 功能 | Agent | 推理范式 | 主要工具 |
|---|---|---|---|
| 旅行规划 | `travel-planning-agent` | Plan-and-Execute | RAG、网页检索/抓取/重排、高德 POI/天气、住宿咨询与每日行程 |
| 景点查询 | `poi-discovery-agent` | 受限 ReAct | RAG 、高德 POI 、当次网页检索/重排 |
| 路线规划 | `route-planning-agent` | 受限 ReAct | 跨城市 12306 车次/余票/换乘/经停、城市内高德公交/驾车/步行、距离校验 |
| 费用估算 | `budget-estimation-agent` | Reflection | 预算分项计算、算术/漏项复核、当次价格信息 |

RAG 与当次公网证据链路：

```text
PGVector RAG
  → 使用 DuckDuckGo/Tavily 搜索
  → HTTPX 静态抓取，正文不足时回退 Playwright
  → BeautifulSoup DOM 清洗 + Trafilatura 正文抽取
  → Ollama/Qwen3 Embedding 余弦相似度重排
  → 返回当前请求的 Top-K 临时网页证据给 Agent 和大模型
```

RAG 使用正式知识与已保存的高相关网页正文；公网搜索结果仅保留每次重排后的 1–2 个分片，管理员可在后台维护。

`execution_trace` 仅返回计划步骤、工具动作和观测摘要，不保存、不返回模型隐藏思维链。

工具实现集中在 `backend/app/tools/`：Agent 仅调用 `RagSearchTool`、`AmapMcpTool`、`RailwayMcpTool`、`SemanticWebSearchTool`、`PoiMediaTool` 和 `ItineraryMapTool`，不直接依赖 PGVector、MCP 传输、网页抓取器或 Embedding Provider。图片字段规范化、景点实体补全和地图点位构建由对应工具负责；路线 Agent 的解析与跨城工作流分别位于 `backend/app/agent/route_helpers.py` 和 `backend/app/agent/route_workflows.py`，核心文件只负责编排。

## 环境要求

- Python 3.12+
- Node.js 18+
- PostgreSQL 15+（当前本机为 17.11）
- pgvector（当前本机为 0.8.6）

## 首次安装

```bash
cp .env.example .env
# 将 .env 中 DATABASE_URL 的 YOUR_LOCAL_USERNAME 改为 macOS 用户名

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e './backend[dev]'
python -m playwright install chromium

cd frontend
npm install
cd ..
```

## 使用第三方 Claude Code API

项目已在 `.claude/settings.json` 配置第三方 API 地址和模型 `gpt5.6sol`，不会保存 API Key。启动 Claude Code 时使用脚本，在终端中隐式输入 Token：

```bash
./scripts/start_claude_third_party.sh
```

如果第三方平台要求 `x-api-key` 而不是 Bearer Token，请将脚本中的 `ANTHROPIC_AUTH_TOKEN` 改为 `ANTHROPIC_API_KEY`，并按照平台文档配置鉴权方式。不要执行 `claude auth login`，也不要把 Token 写入 Git 或聊天窗口。

初始化或安全升级数据库（脚本不会删除已有数据）：

```bash
createdb deeptravel 2>/dev/null || true
psql -d deeptravel -f scripts/init_db.sql
```

不要直接执行 `psql "$DATABASE_URL"`：应用 URL 包含 SQLAlchemy 使用的 `+asyncpg`，`psql` 无法识别。

## 配置模式

安装并启动本地 Embedding 服务：

```bash
brew install ollama
brew services start ollama
ollama pull qwen3-embedding:0.6b
```

推荐的分阶段配置：

```env
TEST_MODE=false
MOCK_LLM=false
MOCK_AMAP=false
MOCK_SEARCH=false

EMBEDDING_PROVIDER=ollama
EMBEDDING_BASE_URL=http://127.0.0.1:11434
EMBEDDING_MODEL=qwen3-embedding:0.6b
EMBEDDING_DIMENSIONS=1024
```

上述配置使用真实 DeepSeek、Ollama、高德 MCP 和 DuckDuckGo。所有密钥只放在 `.env`，不要发到前端或提交仓库。

### 高德 MCP Streamable HTTP

项目使用高德官方远程 MCP，不直接调用高德 REST API。将 Key 只填入项目根目录 `.env`：

```env
MOCK_AMAP=false
AMAP_PROVIDER=mcp
AMAP_MCP_ENDPOINT=https://mcp.amap.com/mcp
AMAP_MCP_API_KEY=你的高德_Key
AMAP_MCP_TIMEOUT_SECONDS=30
```

客户端通过标准 `initialize`、`tools/list` 和 `tools/call` 交互，Key 只在后端组装到 MCP URL 查询参数中。当前已适配 POI、天气预报、地理编码、驾车距离和公交路线，并缓存地理编码结果。密钥不会下发到 Vue 前端。

### 12306 MCP Streamable HTTP

铁路服务采用 Python 版 [`mcp-server-12306`](https://github.com/drfccv/mcp-server-12306)，作为独立 MCP 服务运行；主后端通过同样的标准 Streamable HTTP 客户端调用，不把其 MCP SDK 或 12306 请求依赖混入当前虚拟环境。

先在单独的环境安装并启动服务（服务默认端口为 8000，这里改用 8200 避免与 FastAPI 冲突）：

```bash
python3.12 -m venv .venv-12306
source .venv-12306/bin/activate
python -m pip install -U pip
python -m pip install mcp-server-12306
# 某些 shell/IDE 会预置 DEBUG=release；12306 服务要求布尔值，因此显式覆盖。
DEBUG=false SERVER_HOST=127.0.0.1 SERVER_PORT=8200 mcp-12306
```

然后在项目根目录 `.env` 配置：

```env
RAILWAY_MCP_ENDPOINT=http://127.0.0.1:8200/mcp
RAILWAY_MCP_TIMEOUT_SECONDS=30
# 每次回答最多展示的车次数量，完整数量仍会保留在结果摘要中
RAILWAY_RESULT_LIMIT=9
```

未指定出发时段时，路线 Agent 会在最多 9 趟车次内尽量均衡抽取早上、
中午/下午和晚上各 3 趟；如果某个时段车次不足，会用其他时段的候选补足。
用户明确说“上午/下午/晚上”或“20 点左右”等时段时，只返回该时段的车次，
不会混入其他时段。

路线 Agent 会根据地点自动区分场景：

- “郑州到杭州，2026-09-01 想坐高铁”属于跨城市出行，优先调用 `query-tickets` 查询高铁、动车、普铁车次和余票；用户提到票价、经停或换乘时，继续调用对应的 `query-ticket-price`、`get-train-route-stations`、`query-transfer`。
- “西湖到灵隐寺，想坐公交”属于城市内路线，继续调用高德地图 MCP，不会把景点名称当成铁路车站。
- 对静态城市名列表之外的城市，Agent 会先用 12306 的 `search-stations` 做车站实体确认，再决定是否走铁路分支；明确的景点、湖泊、寺庙、机场等本地 POI 会跳过该确认，避免把景点误判成车站。
- 明确说“公交/地铁/公共交通”时会尊重该偏好，即使两地跨城也不会强行改成铁路；未指定方式的跨城请求才默认优先查询铁路。
- 只说“从一个城市到另一个城市”而未指定方式时，会并行比较铁路、驾车和飞机公开信息；每类默认展示不超过 3 个可核实选项（铁路数量可由 `RAILWAY_RESULT_LIMIT` 调整），不会把全部车次塞给模型。
- 跨城市铁路查询未给日期时不会猜日期，会先请用户补充；航班不是 12306 的能力，只会作为公网正文参考，不能冒充实时航班数据。
- 铁路自然语言参数由大模型结合上下文提取，程序随后校验地点必须出现在原文、交通方式属于允许枚举，并将“明天/后天/2天后”等日期统一转换为 `YYYY-MM-DD` 后再调用 12306，避免把“郑州坐火车”等夹带短语误当成车站名。
- 路线对话会携带当前会话最近的用户消息；例如先说“郑州到大连”，再说“两天后出发”，Agent 会合并两轮信息后查询，而不会只解析第二句话。

### 真实联网搜索

默认使用 DuckDuckGo，不需要 API Key：

```env
MOCK_SEARCH=false
SEARCH_PROVIDER=duckduckgo
DUCKDUCKGO_REGION=cn-zh
DUCKDUCKGO_SAFESEARCH=moderate
WEB_FETCH_RENDERER=auto
PLAYWRIGHT_MAX_CONCURRENCY=2
SEARCH_MCP_INTERNAL_API_KEY=一个自定义的随机长字符串
```

若需要 Tavily，可改为 `SEARCH_PROVIDER=tavily` 并填写 `TAVILY_API_KEY`。修改后同时重启 Search MCP 和 FastAPI。`SEARCH_MCP_INTERNAL_API_KEY` 必须在两个进程的环境中保持一致。

抓取器只允许 HTTPS，会检查重定向、DNS 和 Playwright 的子请求，并拒绝本地/内网地址、下载、超大响应与非文本内容。生产部署仍建议把 Search MCP/Playwright 放在独立容器并限制网络出口。

## 启动

分别打开三个终端。

终端 1，Search MCP：

```bash
source .venv/bin/activate
python -m backend.mcp_servers.search_server.server
```

终端 2，FastAPI：

```bash
source .venv/bin/activate
# 浏览器管理端与小程序真机同时调试：绑定电脑当前局域网 IP
python -m uvicorn backend.app.main:app --reload --host 电脑当前局域网IP --port 8000
```

终端 3，Vue：

```bash
cd frontend
npm run dev -- --host 0.0.0.0
```

真机调试时，管理员前端代理和小程序构建地址都应指向电脑当前局域网 IP。
更换网络后，可通过构建环境变量更新小程序地址，无需改业务代码：

```bash
cd miniapp
VITE_API_BASE_URL=http://电脑当前局域网IP:8000 npm run build:mp-weixin
```

若手机与后端电脑不在同一网络，可运行 `zsh ./启动Cloudflare体验.command --no-pause` 创建临时免费的 HTTPS 隧道。脚本会自动用隧道地址重建小程序，导入 `miniapp/dist/build/mp-weixin` 后即可在微信开发者工具“真机调试”扫码体验；无需共享局域网，但本机服务和隧道必须持续运行。随机 `trycloudflare.com` 地址仅适合临时调试，长期体验版仍需固定 HTTPS 域名并配置微信合法域名。

管理员页面也可通过 `DEEPTRAVEL_BACKEND_URL` 临时指定：

```bash
DEEPTRAVEL_BACKEND_URL=http://127.0.0.1:8000 npm run dev -- --host 0.0.0.0
```

访问 <http://127.0.0.1:5173/>。后端状态页为 <http://127.0.0.1:8000/health>。

### 登录与管理员

管理员账号只有一个，由 `.env` 中的 `ADMIN_USERNAME` 和 `ADMIN_INITIAL_PASSWORD` 初始化；本项目已创建 `admin` 管理员。普通用户可以自行注册，管理员也可以批量创建普通用户，但任何接口都不能再创建或提升第二个管理员。管理员可在页面的“管理员中心”停用用户、按动态分类上传旅游文档，并发布 `REVIEWING` 文档。分类树来自 `GET /api/v1/knowledge/categories`。

对应 API 为 `POST /api/v1/auth/register`、`POST /api/v1/auth/login`、`POST /api/v1/auth/user/login`、`POST /api/v1/auth/admin/login`、`POST /api/v1/auth/wechat/login`、`POST /api/v1/auth/logout` 和 `GET /api/v1/auth/me`。聊天会话接口需要 `Authorization: Bearer <access_token>`，后端会校验会话所属用户，不能跨账号读取。微信小程序登录需要在后端 `.env` 配置 `WECHAT_APP_ID` 与 `WECHAT_APP_SECRET`。

聊天请求默认使用流式接口：`POST /api/v1/chat/sessions/{session_id}/messages/stream`。响应为 Server-Sent Events：`progress` 事件只发送已经确认的目的地、路线方式、地点数量或预算计算结果，不暴露模型隐藏思维；`token` 事件逐段返回已经过规则约束的最终答案，`done` 事件返回结构化结果、去链接的来源标签和执行摘要，`error` 事件表示本次请求失败。会话创建和列表接口可通过 `scene_code` 区分 `TRAVEL_PLAN`、`POI_DISCOVERY`、`ROUTE_PLANNING`、`BUDGET_ESTIMATION` 四个功能。

## 自检与测试

```bash
source .venv/bin/activate
python scripts/check_env.py
ruff check backend tests scripts
pytest -q
python scripts/evaluate_rag.py

cd frontend
npm run build
```

RAG 评测脚本会临时入库五份旅行测试文档，输出 Hit@1、Hit@3、相似度分布和延迟，并在结束时自动删除全部评测记录。

## 知识文档最小流程

上传文档后状态为 `REVIEWING`，必须审核发布后才能参与 RAG：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admin/knowledge/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F 'file=@/绝对路径/成都攻略.md' \
  -F 'source_url=https://资料来源地址'

curl -X POST \
  http://127.0.0.1:8000/api/v1/admin/knowledge/documents/文档ID/publish \
  -H "Authorization: Bearer $TOKEN"
```

联网搜索得到的网页会将重排后的前 1–2 条正文保存为 `READY` 知识，管理员可在“旅游文档”中按分类查看、编辑或删除。交通动态、景区公告、节假日活动和文旅新闻会按分类 TTL 自动过期。

真实密钥不提交 Git；`.env` 已加入 `.gitignore`。
# 微信小程序用户端

项目新增独立的 uni-app 用户端，源码位于 [`miniapp/`](miniapp/)，管理员 Web 端仍保留在 [`frontend/`](frontend/)。普通用户只在小程序注册和登录，管理员只从 Web 管理端登录，后端会校验账号角色并拒绝错误入口。小程序支持四个旅行 Agent、按功能隔离的 5 条短期会话、SSE 流式回答、景点图片和地图。

```bash
cd miniapp
npm install
# 微信开发者工具开发构建
npm run dev:mp-weixin
# 发布构建
npm run build:mp-weixin
```

使用前请在 [`miniapp/src/utils/config.js`](miniapp/src/utils/config.js) 设置后端 HTTPS 地址，并在微信公众平台配置 `request 合法域名`。完整接口说明见 [`docs/MINIAPP.md`](docs/MINIAPP.md)。
