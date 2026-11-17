# Shared implementation contract
All JSON responses direct, errors {error:{code,message,request_id}}. Cookie authentication; frontend fetch credentials include. All IDs strings. Dates ISO UTC. Primary discipline: id, name, color. All /api.

Profile: GET /profile -> {id, timezone, familiar_disciplines:string[], depth:'beginner'|'intermediate'|'deep', intensity:number, broad_use_history:bool, onboarding_complete:bool, ai:{configured:bool,model:string|null}}. PATCH same editable fields; /profile/reset POST {confirm:true}.

Topic summary: {id,title,original_title,summary,original_summary,language,primary_discipline:{id,name,color},related_disciplines:[],subfield,question,value,reading_minutes,sources:[{id,platform,external_id,url,title,language,license,fetched_at,updated_at,content_hash,excerpt}],state:{bookmarked:bool,familiarity:'unknown'|'known'|'unfamiliar',learning:'none'|'learning'|'understood',explored:bool,skipped_until:null|string},quality_score}. Detail GET /topics/:id same + relations array. Opening detail logs visit and first exploration. Related GET /topics/:id/related -> {items:[{topic:summary,relation:{id,type,label,explanation,source_url,direction,source_id,target_id,source_title,target_title}}]}.

GET /discover/today?mode=unknown|bridge|broad -> {id,date,mode,batch_number,parent_id,items:[{topic:summary,reason,features:{novelty,quality,diversity,learnability},score,bridge_path:[]}],constraints:{requested,actual,satisfied:[],relaxed:[],reason_codes:[],message},strategy_version,seed,settings_changed:bool}. POST /discover/refresh body {mode,idempotency_key} same response. POST /discover/impressions {batch_id,topic_ids:[]} -> {recorded:number}. Only mounted visible cards report actual impressions.

POST /topics/:id/feedback {action:'known'|'unfamiliar'|'learning'|'understood'|'none'|'skip'|'unskip',idempotency_key} -> {state}. Bookmark POST {topic_id}, DELETE /bookmarks/:topic_id. GET /bookmarks?limit=50&offset=0 -> {items:summary[],total}.

GET /stats -> {explored_count,discipline_count,bookmark_count,new_disciplines:[{id,name,color,first_explored_at}],distribution:[{id,name,color,count}],unexplored_disciplines:[{id,name,color}],timeline:[{topic_id,title,discipline_name,at}],paths:[{from_title,to_title,relation_type,explanation,source_url}],definitions:{...}}. GET /disciplines -> {items:[{id,name,color,description}]}.

GET /map?scope=all|explored&discipline=&q=&root=&limit=80&depth=1 -> {nodes:[{id,name,type:'discipline'|'subfield'|'topic',discipline_id,color,description,topic_id:null|string,explored:bool,bookmarked:bool,learning,count}],edges:[{id,source,target,type,label,explanation,source_url}],truncated:bool,limits:{nodes,edges,depth}}.

POST /ai/explain {topic_id,depth:'beginner'|'intermediate'|'deep',language:'zh'} -> {status:'ready'|'unavailable',message,cached,content:null|{overview,principle,example,analogy:{text,limits}|null,background,applications:string[],misconceptions:string[],open_questions:string[],questions:string[],claims:[{text,kind:'fact'|'analogy'|'uncertain',source_ids:[]}]},sources:[],usage:{input_tokens,output_tokens}|null}. POST /ai/chat {topic_id,message,depth} -> {status,message,answer,source_ids:[],sources:[],usage}. GET /ai/chat?topic_id -> {items:[{role,content,created_at,source_ids:[]}]}.

## Follow-up exploration contract (2026-11-17)

- `GET /learning?status=learning|understood&limit=20&offset=0` returns `{items:TopicOut[],total}` for the Cookie-authenticated profile. Default status is `learning`; limit 1–100, offset 0–100000. SQL filters and paginates before serialization, ordered by `Topic.title, Topic.id`. The endpoint does not log exploration or change bookmarks. No learning-update timestamp is claimed. Changing state uses the existing feedback endpoint; `none` removes a topic from both learning filters.
- `state.skipped_until` is the stored UTC expiry, including past dates, or null. `skip` sets three days from the server clock. `unskip` clears only expiry; familiarity, learning and bookmarks are independent. Retrying the same feedback key does not extend expiry. Expiry is a weak ranking penalty in future batches, not a ban or a change to the current batch. History-free broad mode does not apply personal skip feedback.
- Every related relation keeps the same source/target IDs, titles, direction, explanation and URL when viewed from either endpoint. These fields describe the stored direction; they must not be reversed to make the current topic appear to be the source.
- Every serialized `bridge_path` hop has `from_id,from_title,to_id,to_title,type,label,explanation,source_url,direction` (and may have `from_discipline_id`). Legacy batches are enriched on read without rewriting ranking snapshots. Names describe current catalog entries; replay continues to use the original snapshot.
- `GET /map?root=topic:ID` prioritizes the requested topic within the node budget. A missing/out-of-scope root returns an empty graph. The frontend explicitly announces fallback and requests the current map scope without root. Root is not a visit event.
- The frontend stores only exploration mode in sessionStorage. Scroll position and unresolved refresh keys stay in memory. Refresh retries reuse the same per-mode operation key until success; a new active refresh gets a new key. A full page reload discards unresolved keys and reads the latest server batch.
- Impressions include the card's original batch ID and retry at most once per observed payload. AI/detail requests use navigation and explanation generations to ignore outdated responses. Ignoring responses does not cancel backend work or provider billing.


## 本轮增量接口与安全约束

所有私有 API 需要匿名 Cookie 与 `X-Unknown-Request: 1`（首次请求可建立 Cookie）；POST/PATCH 仅 JSON。GET health/disciplines 是公开只读例外。缺少 Origin 仍需非简单头，恶意 Origin/Referer、无可信来源的 cross-site 请求返回 403；代理设置 PUBLIC_ORIGIN，CORS 仅明确来源。

| 接口 | 行为 |
| --- | --- |
| POST /discover/surprise | strength=gentle/cross/far，history_free，idempotency_key；一条合格主题或明确空结果 |
| GET /topics/{id}/paths | 最多 4 跳、3 个有据路径，包含方向/类型/来源/检索上限 |
| POST /paths | topic_ids、relation_ids、幂等键；检查连续、方向、来源和无环 |
| GET /paths、GET /paths/{id} | 当前档案分页路径和来源变化/失效标记 |
| PATCH /paths/{id}、DELETE /paths/{id} | 保存当前位置或删除保存 |
| GET /topics/{id}/challenge | 默认隐藏参考；reveal=true 明确读取现有参考 |
| POST /topics/{id}/challenge | challenge_id、自由回答、幂等键；保存参考对照，无自动正确率 |
| GET /topics/{id}/challenge/attempts | 当前档案最近作答，刷新保留 |
| PATCH /challenge-attempts/{id} | 主动 self_assessment=not_yet/partial/got_it |
| GET /revisits | 当前档案自愿回访；due_only=true 查询到期入口 |

反馈新增 name_only/concept_only/connections_unknown/forgotten/revisit/cancel_revisit/worthwhile/not_worthwhile；不改变已有 known/unfamiliar/learning/understood/skip/unskip 的含义。State 增加 revisit_at、worthwhile；Topic 增加内容状态/入口/检查报告；Stats 增加 7/30/90 天覆盖与明确反馈指标。无真实反馈分母返回 null。来源变化使挑战版本不匹配时返回 409，客户端保留作答草稿。访问、作答、自评和理解状态分开。
