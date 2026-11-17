# 数据来源、许可与核验

核验日期：2026-11-17。代码许可与第三方内容许可分别适用。

## 内置知识库

`data/seeds/topics.json` 包含 **60 个主题、12 个唯一统计主学科、60 个真实 Wikipedia 来源、22 条有类型的关系**。每科 5 个主题。`data/seeds/verification.json` 列出核验清单，`data/seeds/ATTRIBUTION.md` 提供逐条署名链接。

这些是真实概念的参考内容，不是合成用户或测试数据。中文为本项目 AI 辅助编写并对照来源的入门整理摘要；不是专家审稿、Wikipedia 原文或逐句翻译。`quality_features.summary_kind` 与 `summary_label` 显式标记来源。`original_summary` 和来源 `excerpt` 只存独立的英文原文短摘，完整原文始终通过来源链接查看。

全部链接通过网页读取逐条核验了条目与相关段落。网页读取未提供可靠数字 page ID、来源更新时间或固定修订号，故种子不伪造这些值：`external_id` 使用 `en:title:<规范标题>`，`updated_at/version` 为空，`content_hash` 只覆盖实际保存的原文片段。`fetched_at` 是本次网页核验/归档时间，不代表来源更新时间。在线 MediaWiki 适配器能够记录 API 实际返回的 page ID 与 revision。

9 个来源有引证不足或专业程度提示，具体保存在 `quality_features.source_notice`。其质量代理分数被降低；可追溯、篇幅和更新日期都不是正确性证明。本次排除了有明显机器生成内容警示的备选条目，没有把这些备选混入默认种子。

一级学科是 UnKnown taxonomy v1 的编辑分类，目的是普通用户入口与统计解释。每主题只有一个主学科；关联学科只供展示，不虚增覆盖。映射依据逐条保留，不能把 Wikipedia 分类当成严格学科树。“黄金比例”从艺术设计视角进入，统计主学科因此设为艺术，关联数学；摘要特别区分数学性质与缺乏证据的审美断言。

关系区分来源支持的事实联系与编辑整理教学路径。后者标为 `teaching`，解释说明比较目的、边界与出处；不把结构相似当成因果事实。未将启发性 AI 类比写入正式图谱。

## Wikipedia / MediaWiki

使用固定的 `https://zh.wikipedia.org/w/api.php` 和 `https://en.wikipedia.org/w/api.php`，实现 `list=search`，`prop=extracts|info|pageprops|categories|langlinks|revisions`；读取摘要、语言、page ID、QID、分类、跨语言链接、来源 URL 与修订信息。[TextExtracts 文档](https://www.mediawiki.org/wiki/Extension:TextExtracts)、[API etiquette](https://www.mediawiki.org/wiki/API:Etiquette)。

公开只读接口通常可匿名访问，不能据此假设无限配额或永久可用。应配置带联系信息的 `INGESTION_USER_AGENT`，批量调用使用 `maxlag=5`、超时、缓存、串行限流和有限重试；认证与限流可能按身份或接口不同。[访问政策](https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy)、[限流政策](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)。

英文 Wikipedia 文本按页面适用的 CC BY-SA 4.0 条件署名与相同方式共享；本项目对保存的原文短摘及由其改编的中文摘要同样采用 CC BY-SA 4.0。署名为 Wikipedia contributors，并提供原条目/历史链接。图片和文章中特别标注的材料可能有独立许可；本项目不下载图片或受限全文。[Wikimedia 的 CC BY-SA 4.0 许可说明](https://foundation.wikimedia.org/wiki/Legal:Text_of_the_Creative_Commons_Attribution-ShareAlike_4.0_International_License/en)。

## Wikidata

固定接口 `https://www.wikidata.org/w/api.php`，使用 `wbsearchentities` 与 `wbgetentities`，不发起宽泛 SPARQL。每次只查询明确实体。Wikidata 结构化数据为 CC0；署名虽非该许可强制条件，仍保留实体与属性链接以便溯源。[数据访问](https://www.wikidata.org/wiki/Help:Data_access)、[Wikibase API](https://www.mediawiki.org/wiki/Wikibase/API/en)、[许可](https://www.wikidata.org/wiki/Wikidata:Licensing)。

当前支持 P31（instance of）、P279（subclass of）、P361（part of）、P527（has part）、P1269（facet of）、P921（main subject）、P101（field of work）。保留属性、方向、声明 ID 与参考信息；跳过 deprecated 声明。只有两端都在当前数据库时才生成正式边，其余原始关系保存在来源元数据，不伪造缺失节点。Wikidata 声明本身不保证正确或适合作为教学桥梁。

## OpenAlex

固定接口 `https://api.openalex.org`，支持研究 topics 搜索、topic 元数据与 work 元数据。topics 具有 domain/field/subfield 结构。当前 topics 的聚类名称与 description 在上游使用语言模型生成，适配器将此存入元数据说明，不能把这种标签当作经过审稿的知识解释。[Topics 官方说明](https://help.openalex.org/data/topics/)、[API 入口](https://help.openalex.org/api/)。

2026-11-17 的官方帮助说明：无 Key 可进行基础请求；免费 Key 提高预算，cursor 第一页以后的分页需要 Key。无 Key 的请求按网络 IP 共享免费预算；有日预算与每秒限额，429 需等待，不能当成无限免费。配额与价格会变动，请运行前重新核对官方文档。程序最多每秒约一次、最多重试两次，不自动创建账号、申请 Key、充值或购买服务。[认证与限额](https://help.openalex.org/api/authentication/)。

OpenAlex 书目元数据使用 CC0；论文、摘要及其他正文的权利需要分别判断。适配器只读取 API 元数据和可提供的摘要索引，保留 DOI、原始落地页与作者字段，不下载论文全文、不把元数据许可扩展到论文全文。[Works 字段说明](https://help.openalex.org/data/works/attributes/)。

## 本次真实接通状态

网页核验成功与 API 接通是两类检查。2026-11-17 初次公共 API 检查：

| 来源 | 实际结果 |
| --- | --- |
| Wikipedia API | 默认代理不可达；显式正常直连的 DNS 解析在 8 秒/15 秒上限内失败。 |
| Wikidata API | 显式正常直连在 8 秒上限内连接超时。 |
| OpenAlex API | 无 Key 的 `topics?search=entropy&per_page=1` 成功，返回真实 T11143 与摘要元数据。后续适配器/批量验证见 `INGESTION.md`。 |

受控 HTTP 替身的单元测试不能证明外部接口已经接通，也不产生付费调用。无网络、无 Key 的种子闭环与以上外部服务可用性独立。

OpenAlex 后续批量实测完成：300 个去重研究主题、300 个来源，覆盖12个本项目主学科；SQLite重导新增0。原始导出与记录为 `data/online/openalex.json`、`data/online/verification.json`。这不改变 Wikipedia/Wikidata API 当前超时的状态，也不把上游聚类描述等同于专家审稿解释。
