# Agent 与工具层架构

## 分层原则

Agent 负责理解当前问题、选择步骤并综合回答；数据库检索、MCP 协议、网页抓取和向量计算全部放在工具层。工具观测会连同原问题一起交给最终回答模型，模型可以据此分析和比较，但不能补造未观测到的事实。

```text
Vue 登录 / 自然语言聊天 / 管理员中心
          │ Bearer Token + 用户会话隔离
FastAPI 认证与 RBAC / TravelAgent 路由
          │
模型优先意图分类 / 规则降级 / 地点实体抽取
          │
          ├── TravelPlanningAgent    Plan-and-Execute
          ├── PoiDiscoveryAgent      ReAct
          ├── RoutePlanningAgent     ReAct
          └── BudgetEstimationAgent  Reflection
                     │
             AgentToolRegistry
       ┌────────┼─────────┬──────────┬──────────────┐
       │        │         │          │              │
 RagSearchTool AmapMcpTool RailwayMcpTool SemanticWebSearchTool
       │        │         │          │              │
 READY PGVector 高德 MCP 12306 MCP  BrowserSearchTool
                                      │
                            Search MCP / DuckDuckGo
                             HTTPX 静态抓取
                                      │ 正文不足
                            Playwright 动态渲染
                                      │
                           BeautifulSoup + Trafilatura

                  PoiMediaTool / ItineraryMapTool
                    （图片与地图展示数据）
```

## 工具职责

| 工具类 | 职责 | 隐藏的底层实现 |
|---|---|---|
| `RagSearchTool` | 检索、证据标准化、可靠分片过滤、知识缺口判断 | `RagRetriever`、PGVector、Ollama Embedding |
| `AmapMcpTool` | POI、天气、公交/驾车/步行路线、距离的类型化调用 | 高德 Streamable HTTP MCP 或本地 Mock Provider |
| `RailwayMcpTool` | 跨城市车次、余票、票价、经停站和中转换乘查询 | Python `mcp-server-12306` Streamable HTTP |
| `BrowserSearchTool` | 通过 Search MCP 搜索并抓取候选页面 | DuckDuckGo/Tavily、HTTPX、Playwright、BeautifulSoup、Trafilatura |
| `SemanticWebSearchTool` | 在当前请求内对网页分片、Qwen3 向量化、余弦相似度重排和 Top-K 输出 | `BrowserSearchTool`、Embedding Provider |
| `PoiMediaTool` | 统一 POI 图片字段、识别回答中的景点实体、补齐经高德核验的图片、生成景点简介 | `AmapMcpTool`、`ItineraryMapTool` |
| `ItineraryMapTool` | 校验景点/路线坐标并生成前端地图点位，拒绝无效或虚构坐标 | 地图 Provider 观测 |
| `AgentToolRegistry` | 只在组合根创建工具并注入各 Agent | 环境配置和 Provider 选择 |

## 意图与地点理解

`TravelIntentClassifier` 会在每次 Agent 请求开始时先调用 DeepSeek 进行结构化意图分类，
支持 `itinerary`、`attraction`、`transportation`、`accommodation`、`food`、
`shopping`、`budget`、`weather` 和 `general` 九种主意图。模型同时抽取
`destination`、`area`、`origin`、`target` 和 `transport_mode` 等实体；地名必须实际出现
在用户原文中才会被采用，防止模型凭空生成地点。

DeepSeek 未配置、请求失败或返回非法类别时，使用加权规则分类器降级；规则只作为
安全兜底，不是地名白名单。网页类别过滤使用较小的搜索语义集合，例如将 `food`
映射为餐饮搜索类别，不再用它决定业务意图。

住宿区域不再使用“西湖、景区、市中心”等固定词表。轻量 NER 兜底会从“附近、
周边、一带”等位置关系中提取任意实体，例如“西溪湿地”、“灵隐寺”和“外滩”；
`AmapMcpTool.resolve_poi` 再通过高德 `maps_text_search` 或地理编码校准名称、城市、
行政区和坐标，Agent 用解析后的 POI 组合住宿、美食、景点和购物查询。

`BrowserSearchTool` 不操作用户的 GUI 浏览器；Search MCP 内部维护无头 Chromium，只在静态抽取不足时使用 Playwright。

每个 Agent 都会在系统提示中声明旅行顾问的专业方向、信息获取策略和防幻觉约束，不再使用“只负责某一种固定输出”的模板式定义。Agent 先判断用户当前意图，再决定真正需要的字段和工具；最终模型同时接收原问题、短期对话、RAG 证据、MCP 观测和公网证据，自行选择合适的回答结构。公网证据传给模型的是网页抓取、清洗和重排后的正文片段，不是搜索摘要或 URL；模型需要消化正文后作答，不输出链接列表。工具执行期间仅通过 SSE 发送已确认的业务事实，终态答案再增量输出，不输出模型隐藏思维链。

前端不再提交目的地、天数、人数和预算等独立表单字段，只提交当前自然语言消息。每个功能使用独立的 `scene_code` 会话列表，后端只携带同一用户、同一功能会话的最近消息作为短期记忆供 Agent 解析连续需求；路线与费用 Agent 在关键信息不足时先追问，不用默认地点或金额代替用户决定。

## Agent 调用链路

### 旅行规划

1. 先识别当前问题是多日行程、住宿咨询还是一般旅行建议，不把所有问题强制转换为行程。
2. 用 `RagSearchTool` 查询本地知识库。
3. 同时搜索和抓取网页，临时分片与向量化后返回语义最相关的 Top-K 证据，让模型参考最新信息。
4. 根据问题调用 `AmapMcpTool`：住宿问题查询酒店 POI，多日行程补充景点和天气。
5. 将原问题和所有工具观测交给模型综合；只有用户确实要求多日行程时才要求天数并生成每日安排。

### 景点查询

```text
RAG 观测 ─┐
高德 POI 观测 ─┼→ 原问题 + 全部观测 → 回答模型
公网搜索 → 抓取 → 临时分片 → 向量化 → Top-K 重排 ─┘
```

公网证据是每次问询的必经步骤，不再受 RAG 是否命中或目的地是否存在于固定列表的限制。
如果搜索、抓取或向量服务不可用，本次公网证据为空，不会把未经语义重排的任意摘要交给模型。

### 路线规划

 ReAct 控制器先由模型判断 `cross_city` / `city_internal` 范围和交通偏好，并在铁路请求中提取 12306 所需的出发地、到达地和日期；规则解析与 12306 `search-stations` 只作防幻觉兜底。模型抽取结果必须在程序侧经过原文实体校验、交通枚举校验和日期标准化后，才会传给 MCP。跨城市且未指定公交/驾车/步行时优先调用 `RailwayMcpTool` 查询 12306 真实车次；指定日期后可按问题追加票价、经停站和换乘查询。城市内路线或明确的公交/驾车/步行偏好调用 `AmapMcpTool`，随后调用距离工具做交叉观测，并将当次网页证据传给回答模型。

实现上，`route_agent.py` 只保留 Agent 编排、模型决策和同城 ReAct 图；日期/地点/交通偏好的纯解析函数位于 `route_helpers.py`，跨城铁路、航班网页和多方式概览位于 `route_workflows.py`。图片字段、景点实体补全和地图点位分别由 `PoiMediaTool`、`ItineraryMapTool` 处理，Agent 通过注册表注入并调用。这样新增图片来源、地图 Provider 或调整解析规则时，不会继续膨胀核心 Agent 文件。

### 费用估算

预算先计算分项草案，用 Reflection 检查算术、漏项和风险，并参考当次搜索到的价格与政策信息；外部价格没有可靠观测时仍标注为估算。

## 扩展方式

- 更换搜索服务：切换 `SEARCH_PROVIDER=duckduckgo|tavily` 或在 Search MCP Provider 层新增实现，Agent 无需修改。
- 更换 Embedding：实现 `EmbeddingProvider`，并在配置工厂中注册。
- 更换地图服务：实现 `MapProvider.call_tool`，然后注入 `AmapMcpTool`。
- 单元测试：直接注入 Fake Tool 或 Fake Provider，不需启动数据库、Ollama 或远程 MCP。

## 边界与安全

- Agent 仍使用场景工具白名单，未授权工具会在执行前被拒绝。
- 网页抓取只允许 HTTPS，对 DNS 解析、重定向、Playwright 子请求、内网地址、内容类型和体积进行限制。
- 正式知识库只检索 `READY`、启用且未过期的文档。管理员上传文档仍可先进入 `REVIEWING`；公网搜索重排后的前 1–2 条正文直接保存为 `READY`，管理员可按动态分类查看、编辑或删除。
- 公网正文候选仅保留当前查询中最相关的 1–2 个分片，实时天气、车次、余票和路线等结构化数据不写入知识库。
- 外部网页和 MCP 返回均被当作不可信数据，不作为模型指令执行。
- 服务端审计记录保留来源和相似度；公网 URL 不返回给聊天客户端，用户看到的是模型基于网页正文整理后的回答；不返回模型隐藏思维链。
- 流式连接断开时后端会取消请求生产任务，并使用请求级上下文传递 token 回调，避免并发用户之间互相污染。
- 密码使用带随机盐的 scrypt 哈希；服务端只保存 Bearer Token 的 SHA-256 摘要。聊天会话以 `user_id` 归属校验，普通用户不能读取其他账号的会话或访问管理员接口。
