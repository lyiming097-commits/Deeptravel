# DeepTravel 项目实现状态

本文件按《Python + DeepSeek 智能旅游助手项目设计文档》记录实际状态，避免把接口骨架误认为已完成能力。

## 已可运行

- Python 3.12、FastAPI、Vue 3、PostgreSQL 17 和 pgvector 0.8.6 本地链路。
- 环境变量集中配置、脱敏配置状态和数据库/pgvector 健康检查。
- PostgreSQL 会话与消息持久化，前端按用户隔离会话并显示多轮记录。
- 用户/管理员身份认证、scrypt 密码哈希、Bearer 会话令牌和管理员 RBAC；数据库部分唯一索引确保管理员账号只有一个。
- 用户可注册、登录、退出并查看自己的会话；管理员可管理用户、上传旅游文档并审核发布为正式知识。
- 文档大小/后缀校验、SHA-256 去重、PDF/DOCX/Markdown/TXT/HTML/CSV 解析。
- 句子边界优先分片、向量写入 PGVector；管理员上传文档支持编辑、发布和删除。
- PGVector 检索只读取已发布且启用的文档，并返回真实分片 ID、来源、URL 和相似度。
- Ollama 原生 `/api/embed` Provider、Qwen3 查询指令、批量处理、超时与 1024 维校验。
- DeepSeek、高德地图和联网搜索独立 Mock 开关，可分阶段启用真实服务。
- 可重复的真实 PGVector 评测脚本，输出 Hit@1、Hit@3、相似度和查询延迟并自动清理。
- 首轮 Ollama 真实评测：10 个问题 Hit@1/Hit@3 均为 100%，平均查询 62.9ms；详见 `docs/RAG_EVALUATION.md`。
- DeepSeek Chat API 客户端的超时、限流、鉴权和响应格式错误转换。
- Search Provider 抽象与 DuckDuckGo、Tavily、Mock 实现；默认真实 Provider 为无 Key 的 DuckDuckGo。
- HTTPX 静态抓取、Playwright 动态回退、BeautifulSoup DOM 清洗和 Trafilatura 正文抽取。
- Search MCP 抓取器会复用 Chromium，隔离 BrowserContext、限制并发并拦截图片/媒体/字体请求。
- 网页抓取限定 HTTPS，校验重定向、DNS 和 Playwright 子请求，拒绝本地/内网地址、超大响应、下载和非文本内容。
- 公网内容在每次请求中完成搜索、抓取、分片、Qwen3 Embedding 向量化和语义重排；每次仅保存前 1–2 条为 `READY` 知识，管理员可查看、编辑或删除。
- 高德远程 MCP Streamable HTTP Provider：标准握手、工具发现、POI、天气预报、地理编码、距离以及公交/驾车/步行路线。
- Python `mcp-server-12306` Streamable HTTP Provider：跨城市车次/余票、票价、车站、经停站和中转换乘查询；路线 Agent 会按地点范围自动选择 12306 或高德。
- 高德 MCP 真实 Key 联调通过；已发现 15 个远程工具，Provider 已加入地理编码缓存和密钥脱敏异常。
- 四个独立 LangGraph 专项 Agent：旅行规划、景点查询、路线规划和费用估算。
- 统一的 DeepSeek 模型优先意图分类器，支持行程、景点、交通、住宿、美食、购物、预算、天气和通用咨询；模型失败时自动使用规则降级。
- 地点实体抽取与高德 POI 解析已替换住宿固定区域词表，可识别“西溪湿地”、“灵隐寺”、“外滩”等任意用户地点，并用地图服务校准城市、行政区和坐标。
- 旅行规划使用 Plan-and-Execute，景点/路线使用受限 ReAct，费用估算使用 Reflection。
- 每个 Agent 均有独立工具白名单，并受工具调用数、图递归次数和总超时限制。
- 每个 Agent 均声明旅行顾问角色、证据优先级和防幻觉约束；前端切换场景时显示对应欢迎语。
- Agent 提示已改为问题驱动而非固定模板：最终回答模型会同时接收原问题、短期对话和 RAG/MCP/公网观测，再自行组织回答；行程场景可识别住宿咨询并直接查询酒店，不再无关地追问游玩天数。
- 聊天有 SSE 流式接口，后端在工具执行完成后增量推送最终答案，并保存完整交易。
- `execution_trace` 记录计划、工具动作与观测摘要，不暴露模型隐藏思维链。
- RAG、高德 MCP、网页搜索/抓取/临时向量化/语义重排已拆分为独立工具类，由 `AgentToolRegistry` 集中构建和注入。
- POI 图片字段规范化、回答中的景点实体补全由 `PoiMediaTool` 统一处理；行程和路线地图坐标校验、点位构建由 `ItineraryMapTool` 统一处理，Travel/Route Agent 不再维护图片与地图细节。
- 前端提供登录/注册、用户会话列表和微信/QQ 风格聊天气泡；四个业务场景统一使用自然语言输入，支持 SSE 流式回复和结构化结果。公网搜索链接保留在服务端审计记录中，不在聊天页展示。
- `chat_session.scene_code` 将会话归属到具体功能；Agent 调用只注入配置数量的最近消息作为短期记忆。

## 真实联调结果

- 景点 Agent 链路已跑通：`rag_search → poi_search → web_search → web_fetch → semantic_rerank`；四个 Agent 均可在当次请求中把公网 Top-K 证据交给大模型。
- 一次真实查询返回高德 POI 10 条、DuckDuckGo 语义证据 5 条。
- Trip.com 页面静态抓取成功；Klook 页面正文不足时正确回退搜索摘要。
- 已验证公网证据只在当次请求中生成并返回，不调用 PGVector 写入或候选审核流程。

## 部分实现

- DeepSeek：已支持普通非流式和 SSE 流式输出；结构化输出自动修复仍待完善。
- RAG：已接入本地 Qwen3-Embedding-0.6B；仍需扩充真实旅行问答评测集，并根据结果持续校准置信度阈值和重排策略。
- MCP：高德已使用官方 Python MCP SDK 和 Streamable HTTP；当前每次工具调用建立独立会话，持久会话、自动重连和退避重试待完善。项目内 Search MCP 仍使用固定 HTTP 工具接口。
- Agent：三种编排范式和执行限制已完成；尚未接入 PostgreSQL Checkpoint、中断后恢复和多 Agent 任务交接。
- 联网搜索：DuckDuckGo 真实链路已可用；网站反爬、地区性结果差异、动态页面和外部网络波动仍可导致单页抓取失败，需继续扩充域名策略和可观测性。
- 知识库：管理员上传、向量化、审核发布可用；异步 Worker、版本、回滚和分片编辑尚未完成。
- 前端：用户聊天、登录、会话列表和管理员管理页面已实现；继续完善密码找回、分页、审计日志和文档异步处理。

## 后续批次

1. DeepSeek 结构化输出自动修复、流式错误恢复和更细粒度的取消控制。
2. PostgreSQL Checkpoint、Agent 中断后恢复、高德 MCP 持久会话和调用退避。
3. 公网搜索域名策略、失败指标、临时 Top-K 证据的相关性与去重质量评测。
4. 高德多路线候选、实时交通信息和更完整的路线展示。
5. 管理员知识库异步 Worker、版本与回滚、审计日志。
6. 结构化行程持久化、自然语言局部修改和 PDF 报告。
7. 密码找回、令牌设备管理、安全评测和 Docker Compose。

## 需要项目方提供或确认

| 项目 | 是否必需 | 用途 |
|---|---|---|
| DeepSeek API Key | 已配置 | 对话、需求提取、规划和答案生成 |
| Embedding 方案 | 已完成 | 本机 Ollama + Qwen3-Embedding-0.6B，1024 维，不需要云端 Key |
| 高德 MCP Endpoint / API Key | 已配置并通过真实联调 | POI、天气、地理编码、距离与路线查询 |
| 12306 MCP Endpoint | 可选，跨城市铁路查询时必需 | Python `mcp-server-12306` 的 Streamable HTTP 地址，例如 `http://127.0.0.1:8200/mcp` |
| DuckDuckGo | 已启用，无需 Key | 默认真实公网搜索 |
| Tavily API Key | 可选 | 需要切换到 Tavily Provider 时才填写 |
| Search MCP 内部密钥 | 部署时必需 | 限制 Search MCP 只被主后端调用；本机开发可暂空 |
| 产品范围确认 | 已完成 | 本批采用注册登录、唯一管理员/普通用户分权和管理员知识库页面；PDF 上传已支持 |
| 联网规则 | 上线前必需 | 可信域名范围、临时证据使用规则和爬取合规要求 |
| 对象存储 | PDF/文件生产化时必需 | MinIO 或 OSS 地址、Bucket 和服务端凭据 |

不要把真实密钥写入本文档、聊天截图、前端环境变量或源码。只填写项目根目录的 `.env`。
