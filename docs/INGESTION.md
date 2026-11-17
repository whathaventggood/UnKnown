# 批量采集与故障恢复

先按 README 安装后端依赖、执行数据库迁移并初始化种子。采集在终端显式执行，推荐请求只使用数据库，不同步采集。

```bash
# 查看参数
backend/.venv/bin/python scripts/ingest.py --help

# 中文 Wikipedia：按知识概念查询，不爬全站
backend/.venv/bin/python scripts/ingest.py --source wikipedia --query 热力学 --discipline physics --limit 20

# Wikidata：实体关系保留属性与方向
backend/.venv/bin/python scripts/ingest.py --source wikidata --query 拓扑学 --discipline mathematics --limit 10

# OpenAlex：免费基础查询仍受服务预算限制
backend/.venv/bin/python scripts/ingest.py --source openalex --query ecology --discipline biology --limit 30

# 查询任务和恢复失败/中断任务
backend/.venv/bin/python scripts/ingest.py --status <任务ID>
backend/.venv/bin/python scripts/ingest.py --resume <任务ID>
```

`--limit` 为 1..300，单批最多 30 条查询，最多处理 limit 个来源结果；去重后主题数量可能更少，不能把处理计数当作去重主题数。建议先小批核对学科映射和来源，再分学科增加规模。多个 `--query` 可以扩大候选，但同批只有一个显式主学科；不同学科请分别建任务。内部学科 ID 在 `data/seeds/topics.json` 可查。

服务端 `.env` 可配置 `INGESTION_USER_AGENT`（建议加入真实联系方式）和 `OPENALEX_API_KEY`。凭据不进入前端、任务参数或缓存。默认 `trust_env=False`，避免机器上失效的代理影响运行；只有需要使用操作者已配置的代理时才显式添加 `--trust-env`，不改变来源访问政策。

三类适配器都复用异步 HTTP 连接，固定来源地址、不接受任意内容 URL。每次请求超时默认 15 秒、最多重试 2 次、单实例请求间隔约 1.05 秒。429 与 5xx 有界退避（尊重数字 Retry-After，最多 30 秒）；认证失败、无效 JSON 和缺失摘要有独立错误码。成功公共响应在 `data/cache/ingestion` 缓存 24 小时，缓存键排除凭据。

OpenAlex 的 topics 搜索响应已经包含完整 topic 元数据，同一次采集复用它，避免对每个结果重复请求。断点恢复若内存缓存已消失，再对待处理 ID 查询详情；不下载快照或论文全文。没有摘要的实体记录失败，不调用模型补写事实。

`ingestion_jobs` 保存来源、参数、状态、处理量、错误、更新时间与 checkpoint。每个成功条目和每个失败都会提交断点；Ctrl-C 标记 interrupted，失败 ID 留在 pending 可重试。进程锁阻止同一 job 并发恢复；进程异常退出后操作系统释放锁，`--resume` 可以重新接管 running 状态记录。每条写入采用事务，成功条目保留，不因另一个条目失败而回滚整个批次。

规范化优先用 Wikidata QID 和跨语言 sitelink 对齐，已核验种子的规范来源标题有显式对应表；不做模糊标题自动合并。OpenAlex ID 稳定地对应来源主题，跨平台无可靠证据时保留为独立主题。来源、更新时间、版本、内容哈希、外部分层与映射依据分开归档。统计时只使用一个主学科。

状态 `complete` 代表本次有限批次处理完毕或达到上限，`partial` 表示有可恢复错误，不代表已抓取来源的全部内容。处理数包括已存在条目的更新，实际新增数以数据库去重计数为准。Wikidata 关系缺少库内另一端时只存声明元数据，不创建悬空图谱边。

## 检查

```bash
cd backend
.venv/bin/python -m pytest tests/test_ingestion.py -q
```

受控测试包含在线更新保留中文种子的回归检查、60 条种子/12 学科/22 条关系校验、重导去重、429 和缓存、凭据不落缓存、超时重试上限、无效响应、API 元数据解析、关系方向及部分失败断点恢复。普通测试不接触真实网络。

本次真实 API 接通、去重规模和未完成目标会另记在 `data/online/verification.json`（如果批量验证完成）与最终验收报告；不把替身测试或种子网页核验计入在线采集规模。至少 300 条是在线初始化目标，只有实际数据库/导出计数达到才可宣称完成。

## 300 条初始化与已核验快照

```bash
# 正常联网：最多 12 个主题搜索，每个最多35结果，最终择取300个去重主题
backend/.venv/bin/python scripts/initialize_online.py

# 网络受限时：导入本次实际采集保存的300条在线元数据，零网络请求
backend/.venv/bin/python scripts/initialize_online.py --snapshot data/online/openalex.json

# 恢复上次在线初始化
backend/.venv/bin/python scripts/initialize_online.py --resume <任务ID>
```

2026-11-17 实际验证了 OpenAlex 的12个受限查询：每查询上限35，天文实际12、音乐实际27，其余各35；轮流按学科取样后保存 **300个去重主题 / 300个来源 / 12个主学科**。临时SQLite完成全量导入与重导，第二次新增0。详见 `data/online/verification.json`。这是在线真实元数据，不是测试替身；默认产品数据库仍只自动初始化60个编辑种子，在线快照需要显式导入。

初始化任务保存在 ingestion_jobs，有限公共元数据按学科批次保存断点；恢复时重用已完成学科，失败学科仅恢复未完成ID。自动导出到忽略提交的 data/ingestion/<jobid>.json，不覆盖已提交的核验快照。查询按12个明确学科入口提供映射，外部 domain/field/subfield 元数据另存，交叉领域条目以首次选定主学科统计，不把搜索相关性当作严格分类证明。

OpenAlex topic 名称和描述为上游机器生成的研究簇标签，保留英文原文并显式说明。它们的来源、ID和元数据可核验，但不应据此声称每个描述都经专家审稿或能替代论文。论文全文没有下载。

本次还验证了正式命令：快照首次导入新增300、第二次新增0；与60种子共存得到360主题/360来源；初始化命令重放HTTP缓存得到300去重条目，完成任务恢复不重复请求或新增记录，任务表保留3条实际执行记录。该检查使用隔离临时数据库，未更改默认产品数据库。


## 本轮内容加工与发布（0003～0006）

导入后的本地检查不调用模型。每主题持久化 `content_status`、`content_intro`、`content_fingerprint`、`content_checks`、`processing_error`、处理次数和时间；来源变化会失效重做。RAW/EXTRACTED/ENRICHED/REVIEWED/PUBLISHED 是处理阶段，其中 REVIEWED 仅指本地规则，不是专家核验。

```bash
backend/.venv/bin/python scripts/process_content.py --kind online --limit 300
backend/.venv/bin/python scripts/process_content.py --limit 100 --after-id 上批输出的last_topic_id
backend/.venv/bin/python scripts/process_content.py --status 内容任务ID
backend/.venv/bin/python scripts/process_content.py --resume 内容任务ID
backend/.venv/bin/python scripts/process_content.py --limit 5 --enrich-ai --max-ai-calls 2 --max-reserved-tokens 25000
```

批次最多 300；AI 最多 20 个生成任务，Token 保守预留上限 100000。`--enrich-ai` 需要服务器 Key 和显式预算；`llm_retries` 仍计入保守预留。任务恢复沿用已消耗的累计次数/Token，不归零；失败记录安全代码，错误/断点写入 ingestion_jobs。CLI 锁防止同时运行多个内容任务。

本轮实际在隔离库导入已有 300 条 OpenAlex 归档并逐条检查，全部 EXTRACTED、AI 调用 0，缺少中文入口/问题/价值且仅有上游研究簇元数据。60 条整理种子通过自动准入。没有重新采集 Wikipedia/Wikidata，没有付费翻译或生成，也没有将测试夹具写入正式知识库。

仅有研究簇元数据时，翻译后最多 ENRICHED，仍不发布；需要补充独立入门材料。模型生成引用必须定位到实际片段，不能创建来源 URL/ID。来源更新不覆盖用户收藏、学习状态、自测与路径；更新来源导致旧材料失效时停止新推荐。
