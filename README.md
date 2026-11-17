# UnKnown · AI 认知破壁机

> Don't just discover what you like. Discover what you don't know exists.

一个默认中文、可本机自托管的知识探索系统。每日五条有出处的知识入口，从陌生主题走向可解释的跨领域联系，并保存个人探索足迹。

**可以直接运行的路径：**跳过或填写熟悉领域 → 三种模式推荐 → 阅读真实来源摘要 → 标记陌生/学习状态、收藏 → 查看探索记录和动态认知地图 → 沿有依据的关系继续探索。没有 LLM Key，也能完成这条路径。

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

## 部署到 Netlify

本项目推荐拆成两个服务：Netlify 托管 `frontend/` 的 Vue 静态站点，FastAPI 后端部署到 Render、Railway 或其他支持长期运行 Python Web Service 的平台。Netlify 的 Vite 默认构建命令是 `npm run build`，发布目录是 `dist`；仓库里的 `netlify.toml` 已经配置好这两个值和 SPA 路由回退规则。[Netlify 的 Vite 部署说明](https://docs.netlify.com/build/frameworks/framework-setup-guides/vite/)

1. 在 Netlify 选择 **Add new project → Import an existing project → GitHub**，选择 `whathaventggood/UnKnown`，分支选 `main`。由于 `netlify.toml` 已设置 `base = "frontend"`，不需要手动填写前端目录。
2. 先部署后端。以 Render 为例，新建 **Web Service**，仓库选择同一个项目，Root Directory 填 `backend`，Build Command 填 `uv sync --frozen --python 3.11`，Start Command 填 `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`。Render 的 FastAPI 服务需要监听 `0.0.0.0` 和平台提供的 `$PORT`。[Render 的 FastAPI 部署说明](https://render.com/docs/deploy-fastapi)
3. 在后端环境变量中设置 `COOKIE_SECURE=true`、`DATABASE_URL`、`CORS_ORIGINS=["https://你的站点.netlify.app"]`。如果启用 AI，再设置 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`。不要把这些服务端变量写进前端或提交到 GitHub。
4. 在 Netlify 的 **Project configuration → Environment variables** 中设置 `VITE_API_BASE_URL=https://你的后端地址/api`，然后重新部署。Netlify 构建时读取环境变量，浏览器请求会发送到这个后端地址；服务端 API Key 不会进入前端构建。[Netlify 环境变量说明](https://docs.netlify.com/build/environment-variables/overview/)
5. 打开 Netlify 站点，测试首页、详情页和刷新后的深链接。如果直接访问 `/topics/...` 返回 404，检查 `frontend/public/_redirects` 是否被包含在 `dist/`，以及 Netlify 的发布目录是否为 `dist`。SPA 需要将所有未知路径回退到 `/index.html`。[Netlify SPA 回退说明](https://docs.netlify.com/manage/routing/redirects/rewrites-proxies/)

注意：当前后端使用 SQLite。Render 普通实例的本地文件不适合作为长期数据盘；演示可以先使用临时 SQLite，正式使用应给服务配置持久化磁盘，或把数据层迁移到 PostgreSQL。Netlify 只负责前端，不能替代这个持久化后端。

生产构建由 FastAPI 同源提供，访问 [http://127.0.0.1:8000](http://127.0.0.1:8000)，接口文档 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。默认仅绑定本机，不会公开部署。线上 HTTPS 需设置 `COOKIE_SECURE=true`，由反向代理终止 TLS；使用 **1 个 worker**，因为 AI 同任务合并与个人聊天锁在进程内维护。暂不支持多进程或多实例共享 AI 并发控制。

数据库默认位于 `data/unknown.db`，迁移版本在 `backend/alembic/versions`。重启不会删除记录。改变 `DATABASE_URL` 应使用 SQLite 绝对路径。依赖完整锁定于 `backend/uv.lock` 与 `frontend/package-lock.json`。程序启动会升级现有数据库到最新迁移，升级前可在停服后备份数据库及 WAL 文件；没有自动破坏性重置。

## 三种推荐模式

- **完全陌生**：提高尚未探索领域和用户自述陌生内容的优先级，保留质量、可学习性要求。
- **跨领域桥梁**：从熟悉或已探索主题出发，使用有出处且保留类型与方向的关系。找不到可靠路径会明确降级。
- **广域探索**：先按主学科分层抽样，使用质量/可学习性/集合多样性；可选择使用近期历史去重，或完全不使用个人历史。两种行为在设置与界面明确区分。

默认权重 `0.35N + 0.25Q + 0.20D + 0.20L`；`D` 随当前已选集合变化。候选充足时五条覆盖至少四主学科、单科最多两条、至少两条新领域或细分主题机会。关联标签不增加主学科计数。候选不足按固定顺序放宽并记录原因，来源可追溯要求始终保留。

每日批次按匿名档案、IANA 时区日期、模式持久化；刷新页面读取原批次。“换一组”创建带父批次的新记录；设置变化仅提示，用户主动换组后应用。生成推荐不是曝光；曝光由实际可见卡片上报；打开详情才产生访问与首次探索。批次保存完整候选/历史/特征/随机种子/配置快照以便重放。

更多细节与指标定义见 [推荐算法](docs/RECOMMENDATION.md) 与 [离线评估](docs/EVALUATION.md)。评估采用合成历史，不证明真实学习效果；无真实反馈时自述陌生指标为不可计算。

## 数据与来源

默认离线库 **60 个真实来源主题 / 12 个主学科 / 22 条有类型的主题关系**。保留 Wikipedia 原始短摘、来源链接、独立许可、核验方法与日期；中文整理摘要明确标记 **AI 辅助**，不是原始引文。未获得的来源更新时间、数字页面 ID、版本号留空或明确使用标题定位，不伪造。

学科体系为版本化的人工编目，Wikipedia 分类不被当成严格学科树。原始资料、整理摘要、按需 AI 解释、事实关系和教学联系分别标记。质量评分是代理指标，不能证明内容真伪。

三个独立适配器提供 MediaWiki、Wikidata、OpenAlex 的只读接入；采集仅由 CLI 显式执行，不在普通推荐请求中同步采集。缓存、限流、有限重试、任务状态、失败原因和断点均可查询。完整命令与实际联网结果见 [采集说明](docs/INGESTION.md) 与 [数据来源核验](docs/DATA_SOURCES.md)。已实际采集并归档 **OpenAlex 300 个去重主题 / 12 主学科**，独立库重复导入新增 0。可显式运行 `backend/.venv/bin/python scripts/initialize_online.py --snapshot data/online/openalex.json` 离线导入，连同种子共 360 条。Wikipedia/Wikidata 在线 API 在本次环境超时。在线结果与默认种子、合成测试数据隔离。

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

AI 按需运行，刷新详情不会调用。入门/进阶/深入分别缓存；键包含模型、供应商配置、语言、提示词与来源版本。共享解释不含个人历史；聊天按档案隔离。输出必须通过结构和引用 ID 校验，模型生成 URL 不成为来源。没有支持材料的开放问题省略，类比有边界。**有效引用不等于来源确实支持所有陈述**，页面保留原文供核对。

超时、429、无效输出分别处理；重试、单次输出、上下文、个人与全局每日请求/Token 额度在 `.env.example` 配置。额度采用保守预留，usage 不提供时保持未知并按预留计账，失败也计请求额度；不配置价格就不估算金额。共享缓存命中不调用也不消耗生成请求额度。价格与远程实际收费不能由本系统保证，服务端本地预算是调用防护。

**本交付未使用真实付费 LLM 服务**；受控替身已验证证据流程，真实供应商集成仍需用户配置合法 Key 后单独验证。

## 身份与隐私

服务端创建高熵匿名 Cookie（HttpOnly / SameSite=Lax），数据库仅保存凭据哈希。API 从 Cookie 识别档案，不接受前端指定 `user_id`。浏览器清除 Cookie 后可能无法再次访问原档案，没有跨设备同步。

“设置 → 清除当前档案”有确认界面，会清除行为、学习状态、收藏、推荐和私有讨论；保留共享知识库及非个性化解释。匿名化使用计数保留全局额度总量，无聊天内容。外部资料仅是证据数据，不允许执行工具或读取文件。当前版本面向可信的单机自托管；不提供账号、支付、社交或任意 URL 抓取接口。

## 检查与评估

```bash
bash scripts/check.sh
# 单独运行
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q
cd frontend
npm run typecheck
npm run build
# 先启动后端和前端，再运行真实浏览器测试
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5183 npm run e2e
cd ..
backend/.venv/bin/python scripts/evaluate.py
backend/.venv/bin/python scripts/verify_offline.py
```

普通后端测试不会联网或产生付费调用。Playwright 首次需要 `npx playwright install chromium`；浏览器测试使用真实 API 和独立匿名档案，会清除测试档案记录。建议验证时用单独数据库：`DATABASE_URL=sqlite:////absolute/path/qa.db`。测试结果与实际覆盖范围见 [验收报告](docs/ACCEPTANCE.md)。

## 结构与范围

- `frontend/`：Vue 3、TypeScript、Vite、Router、Pinia、Tailwind、ECharts Graph。
- `backend/app/api/`：匿名身份、校验、请求/响应与错误边界。
- `backend/app/services/`：探索批次、导入、统计与有限地图。
- `backend/app/recommendation/`：无网络依赖的可解释推荐。
- `backend/app/ingestion/`：三个来源适配器、规范化、采集恢复。
- `backend/app/ai/`：Provider、证据、输出校验、缓存、额度与聊天。
- `data/seeds/`：可追溯默认内容；测试合成数据仅在 tests 内。

详见 [架构](docs/ARCHITECTURE.md)、[实现状态与限制](docs/ACCEPTANCE.md)。项目代码使用 [MIT](LICENSE)，第三方数据沿用各自许可与署名要求，MIT 不覆盖外部内容。
