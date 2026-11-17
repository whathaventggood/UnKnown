# UnKnown · AI 认知破壁机

> Don't just discover what you like. Discover what you don't know exists.

一个默认中文、可本机自托管的知识探索系统。每日五条有出处的知识入口，从陌生主题走向可解释的跨领域联系，并保存个人探索足迹。

**可以直接运行的路径：**跳过或填写熟悉领域 → 三种模式推荐 → 阅读真实来源摘要 → 标记陌生/学习状态、收藏或暂时跳过 → 从学习列表继续阅读 → 查看探索记录和动态认知地图 → 沿有依据的关系继续探索。没有 LLM Key，也能完成这条路径。

## 本机启动（macOS Apple Silicon / Linux）

需要 Python **3.11–3.13**、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和 Node.js **22.12+**（已在本机 Python 3.11、Node 26 验证）。不需要 Docker、本地模型、账号或付费服务。

在项目根目录运行：

```bash
cp -n .env.example .env  # 可选；不复制也能以默认设置运行，AI 关闭
bash scripts/dev.sh
```

打开终端打印的地址，默认 [http://127.0.0.1:5173](http://127.0.0.1:5173)。脚本会锁定安装依赖、运行迁移、幂等导入种子并启动前后端。首次安装需要联网，之后已安装依赖的核心功能可以离线使用。按 Ctrl+C 停止自己启动的服务。

若系统默认 `python3` 版本过新，仍使用 `python3.11`；或指定兼容解释器：

```bash
UNKNOWN_PYTHON=/opt/homebrew/bin/python3.11 bash scripts/dev.sh
```

端口被占用时，保留已有程序，指定新端口。前端更换来源后需在 `.env` 的 `CORS_ORIGINS` 中明确加入相应来源（默认也放行本机 5183）：

```bash
UNKNOWN_WEB_PORT=5183 bash scripts/dev.sh
```

手动启动/排查：

```bash
uv sync --project backend --frozen --python python3.11
cd frontend
npm ci
npm run build
cd ..
bash scripts/serve.sh
```

## 部署：优先同源 `/api`

推荐让静态页面与 `/api` 共用一个浏览器来源。构建后 FastAPI 已可同时提供前端与 API：

```bash
cd frontend
npm run build
cd ..
bash scripts/serve.sh
```

线上由 HTTPS 反向代理转发，配置 `COOKIE_SECURE=true`、`COOKIE_SAMESITE=lax`、`PUBLIC_ORIGIN=https://你的前端域名`，`CORS_ORIGINS` 仅列明确允许的前端来源。`PUBLIC_ORIGIN` 必须是完整来源，不带路径或末尾斜线；服务不会依据任意客户端的 `X-Forwarded-Host` 放行来源。若使用 Uvicorn 代理头功能，只信任实际代理的 IP，例如本机代理用 `--proxy-headers --forwarded-allow-ips=127.0.0.1`。

Netlify 托管前端时，在构建环境中设置 **`API_PROXY_ORIGIN=https://你的后端域名`**，并移除 `VITE_API_BASE_URL`。仓库构建脚本会在 SPA 回退前生成 `/api/*` 的服务端代理；浏览器继续使用 `/api`。后端设置 `PUBLIC_ORIGIN` 为 Netlify 前端来源、`COOKIE_SECURE=true`、`COOKIE_SAMESITE=lax`。后端仍需独立运行 FastAPI；Netlify 静态托管不负责 SQLite。[Netlify 代理说明](https://docs.netlify.com/manage/routing/redirects/rewrites-proxies/)。本轮验证了代理规则生成，尚未执行真实云部署。

跨站直连仍支持 `VITE_API_BASE_URL=https://后端/api`，但需要 `COOKIE_SAMESITE=none` 和 `COOKIE_SECURE=true`，浏览器仍可能拒绝第三方 Cookie。此设置不能保证匿名身份稳定；应用启动会验证 Cookie 是否能保留，失败时说明部署问题。[第三方 Cookie 行为](https://developer.mozilla.org/en-US/docs/Web/Privacy/Guides/Third-party_cookies)。不要通过关闭来源检查解决部署问题。

所有私人 API 请求都需要 `X-Unknown-Request: 1`，包括会记录访问/创建批次的 GET；前端已自动携带。修改请求接受 JSON，来源检查同时考虑 Origin、缺省 Origin 时的 Referer 和 Fetch Metadata。该头是基于浏览器非简单请求与严格 CORS 的 CSRF 防护，不是身份令牌。[OWASP API 请求头防护](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)。例如：

```bash
curl -H 'X-Unknown-Request: 1' -c /tmp/unknown-cookies.txt http://127.0.0.1:8000/api/profile
```

SQLite 默认 `data/unknown.db`。生产必须把数据库放在已挂载的持久化目录，例如 `DATABASE_URL=sqlite:////var/data/unknown.db`，并备份数据库；WAL 活跃时应使用 SQLite 的在线备份或停服后一并备份。临时文件系统不适合作为正式数据盘。升级使用 Alembic **0001→0006**，保留现有档案、收藏、学习状态和历史快照。请在升级前完成备份。

继续使用 **1 个 worker**。AI 任务合并与聊天清除世代仍在单进程内维护，当前不承诺多实例协调。

## 本轮新增入口

- 首页“随机破壁”：温和、跨界、完全陌生使用不同权重；可选择不按个人历史探索，只在主动点击时抽取一条。
- 详情可标记“听过名称 / 想了解应用 / 想了解跨学科联系 / 已忘记”，并保留原有陌生、已了解、学习状态和收藏。
- “从这个知识继续探索”：每跳有类型、方向、来源；可返回、继续、主动保存。已保存路径在“我的探索”重新打开。
- “认知挑战”：自由回答、查看参考、主动自评；无 Key 可用，作答刷新保留。字词线索不代表判对，作答不会自动标成理解。
- 详情“一周后回访”：到期后首页出现自愿入口；“我的探索 → 自愿回访”可提前打开或取消。
- “我的探索”展示 7/30/90 天覆盖及明确反馈；无反馈分母显示不可计算。地图新增层级筛选和理解自述形状区分。

## 三种推荐模式

- **完全陌生**：提高尚未探索领域和用户自述陌生内容的优先级，保留质量、可学习性要求。
- **跨领域桥梁**：从熟悉或已探索主题出发，使用有出处且保留类型与方向的关系。找不到可靠路径会明确降级。
- **广域探索**：先按主学科分层抽样，使用质量/可学习性/集合多样性；可选择使用近期历史去重，或完全不使用个人历史。两种行为在设置与界面明确区分。

新版策略 `unknown-rerank-2.0`。默认权重 `0.35N + 0.25Q + 0.20D + 0.20L`；`D` 随当前已选集合变化。候选充足时五条覆盖至少四主学科、单科最多两条、至少两条新领域或细分主题机会。关联标签不增加主学科计数。候选不足按固定顺序放宽并记录原因，来源可追溯要求始终保留。

每日批次按匿名档案、IANA 时区日期、模式持久化；刷新页面读取原批次。“换一组”创建带父批次的新记录；设置变化仅提示，用户主动换组后应用。生成推荐不是曝光；曝光由实际可见卡片上报；打开详情才产生访问与首次探索。批次保留完整排序输入、历史、特征、随机种子与配置；目录使用共享不可变压缩快照，旧 JSON 快照与旧算法仍可重放。

更多细节与指标定义见 [推荐算法](docs/RECOMMENDATION.md) 与 [离线评估](docs/EVALUATION.md)。评估采用合成历史，不证明真实学习效果；无真实反馈时自述陌生指标为不可计算。

## 数据与来源

默认离线库 **60 个真实来源主题 / 12 个主学科 / 22 条有类型的主题关系**。保留 Wikipedia 原始短摘、来源链接、独立许可、核验方法与日期；中文整理摘要明确标记 **AI 辅助**，不是原始引文。未获得的来源更新时间、数字页面 ID、版本号留空或明确使用标题定位，不伪造。

学科体系为版本化的人工编目，Wikipedia 分类不被当成严格学科树。原始资料、整理摘要、按需 AI 解释、事实关系和教学联系分别标记。质量评分是代理指标，不能证明内容真伪。

三个独立适配器提供 MediaWiki、Wikidata、OpenAlex 的只读接入；采集仅由 CLI 显式执行，不在普通推荐请求中同步采集。缓存、限流、有限重试、任务状态、失败原因和断点均可查询。完整命令与实际联网结果见 [采集说明](docs/INGESTION.md) 与 [数据来源核验](docs/DATA_SOURCES.md)。已实际采集并归档 **OpenAlex 300 个去重主题 / 12 主学科**，独立库重复导入新增 0。可显式运行 `backend/.venv/bin/python scripts/initialize_online.py --snapshot data/online/openalex.json` 离线导入，连同种子共 360 条。本轮已在隔离库对 300 条逐项加工检查，全部为 EXTRACTED；仅有上游研究簇元数据、缺少合格中文教学材料，暂不进入新推荐。Wikipedia/Wikidata API 的既往超时记录保留，本轮没有重新联网采集。在线结果与默认种子、合成测试数据隔离。

## 内容加工与发布准入

RAW → EXTRACTED → ENRICHED → REVIEWED → PUBLISHED 分别表示元数据、原文片段、入门材料、本地规则检查、准入发布。**REVIEWED 是自动结构/证据位置检查，不是专家审稿；PUBLISHED 不证明事实蕴含。** 缺少正文、许可、中文入口、核心问题或具体价值时保留原因，不补造材料。

```bash
# 显式导入已有真实快照，随后离线检查；不修改用户学习记录
backend/.venv/bin/python scripts/initialize_online.py --snapshot data/online/openalex.json
backend/.venv/bin/python scripts/process_content.py --kind online --limit 300
# 更大目录分批，用上一批输出的 last_topic_id 继续
backend/.venv/bin/python scripts/process_content.py --limit 100 --after-id 上批最后主题ID
# 恢复失败/中断任务
backend/.venv/bin/python scripts/process_content.py --status 内容任务ID
backend/.venv/bin/python scripts/process_content.py --resume 任务ID
# 明确启用付费加工时，必须同时设置调用数和保守 Token 累计上限
backend/.venv/bin/python scripts/process_content.py --limit 5 --enrich-ai --max-ai-calls 2 --max-reserved-tokens 25000
```

普通导入和页面请求不调用加工模型。来源变化会使内容检查失效并重做；任务和错误持久化，同一输入重复处理不重复生成。AI 恢复需再次明确 `--enrich-ai` 及累计预算；翻译研究簇仍不能使元数据自动变成可发布教学材料。详见 [采集与加工](docs/INGESTION.md)。

## 可选 AI 导师

只在服务端根目录 `.env` 设置：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
LLM_API_KEY=你的服务端密钥
LLM_JSON_MODE=true
```

硅基流动可将地址设为 `https://api.siliconflow.cn/v1` 并填写该服务实际支持的模型。模型与能力会变化，配置前核对 [DeepSeek 官方接口](https://api-docs.deepseek.com/api/create-chat-completion/) 或 [硅基流动官方接口](https://docs.siliconflow.cn/docs/api/chat-completions-post)。通用 Provider 默认不假设 JSON 模式可用，`LLM_JSON_MODE=false` 仍请求纯 JSON 并由本地验证。不使用流式或工具调用，服务地址仅来自服务端配置。

重启后生效。前端只显示可用状态与模型，不读取、传递或存储 Key。无需把 Key 告诉 AI 或写入聊天。默认直接连接；确需环境代理可显式设 `LLM_TRUST_ENV=true`（SOCKS 需另外安装 httpx 对应可选依赖）。

AI 按需运行，刷新详情不会调用。入门/进阶/深入分别缓存；键包含模型、供应商配置、语言、提示词与来源版本。共享解释不含个人历史；聊天按档案隔离。输出必须通过结构、来源 ID 和逐字引用片段定位；系统整理摘要不进入原文证据。只有研究簇元数据或没有足够原文片段时拒绝扩展生成。模型生成 URL 不成为来源。没有支持材料的开放问题省略，类比有边界。**有效引用不等于来源确实支持所有陈述**，页面保留原文供核对。

超时、429、无效输出分别处理；重试、单次输出、上下文、个人与全局每日请求/Token 额度在 `.env.example` 配置。额度采用保守预留，usage 不提供时保持未知并按预留计账，失败也计请求额度；不配置价格就不估算金额。共享缓存命中不调用也不消耗生成请求额度。价格与远程实际收费不能由本系统保证，服务端本地预算是调用防护。

**本交付未使用真实付费 LLM 服务**；受控替身已验证证据流程，真实供应商集成仍需用户配置合法 Key 后单独验证。

## 身份与隐私

服务端创建高熵匿名 Cookie（HttpOnly / SameSite=Lax），数据库仅保存凭据哈希。API 从 Cookie 识别档案，不接受前端指定 `user_id`。浏览器清除 Cookie 后可能无法再次访问原档案，没有跨设备同步。

“设置 → 清除当前档案”有确认界面，会清除行为、学习状态、收藏、推荐、保存路径、挑战作答、回访意愿和私有讨论；保留共享知识库及非个性化解释。匿名化使用计数保留全局额度总量，无聊天内容。外部资料仅是证据数据，不允许执行工具或读取文件。当前版本面向可信的单机自托管；不提供账号、支付、社交或任意 URL 抓取接口。

## 检查与评估

```bash
bash scripts/check.sh
# 单独运行
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q
cd frontend
npm run test:requests
npm run typecheck
npm run build
# 先启动后端和前端，再运行真实浏览器测试
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5183 npm run e2e
cd ..
backend/.venv/bin/python scripts/evaluate.py
backend/.venv/bin/python scripts/verify_offline.py
backend/.venv/bin/python scripts/evaluate_semantics.py
backend/.venv/bin/python scripts/benchmark.py --output docs/benchmark-results.json
backend/.venv/bin/python scripts/replay_batch.py 批次ID
```

普通后端测试不会联网或产生付费调用。Playwright 首次需要 `npx playwright install chromium`；浏览器测试使用真实 API 和独立匿名档案，会清除测试档案记录。建议验证时用单独数据库：`DATABASE_URL=sqlite:////absolute/path/qa.db`。组件请求回归可在 Node 下执行，不依赖浏览器；它不验证 DOM、布局或真实浏览器。测试结果与实际覆盖范围见 [验收报告](docs/ACCEPTANCE.md)。

## 结构与范围

- `frontend/`：Vue 3、TypeScript、Vite、Router、Pinia、Tailwind、ECharts Graph。
- `backend/app/api/`：匿名身份、校验、请求/响应与错误边界。
- `backend/app/services/`：探索批次、导入、统计与有限地图。
- `backend/app/recommendation/`：无网络依赖的可解释推荐。
- `backend/app/ingestion/`：三个来源适配器、规范化、采集恢复。
- `backend/app/ai/`：Provider、证据、输出校验、缓存、额度与聊天。
- `data/seeds/`：可追溯默认内容；测试合成数据仅在 tests 内。

详见 [架构](docs/ARCHITECTURE.md)、[实现状态与限制](docs/ACCEPTANCE.md)。项目代码使用 [MIT](LICENSE)，第三方数据沿用各自许可与署名要求，MIT 不覆盖外部内容。
