<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,watch,computed} from 'vue'
import {useRoute} from 'vue-router'
import {ArrowLeft,ArrowUpRight,Bookmark,Check,BookOpen,HelpCircle,Clock3,Link2,Sparkles,Send,ChevronDown,ShieldCheck} from 'lucide-vue-next'
import {api,post,key,safeUrl} from '../api'
import type {Topic,Relation,Depth,State,Explain,ChatItem,Source} from '../types'
import {useApp} from '../stores/app'
import Notice from '../components/Notice.vue'
const route=useRoute(),app=useApp(),topic=ref<Topic|null>(null),related=ref<{topic:Topic;relation:Relation}[]>([]),loading=ref(true),error=ref(''),busy=ref(false),depth=ref<Depth>(app.profile?.depth||'beginner'),explanation=ref<Explain|null>(null),aiLoading=ref(false),aiError=ref(''),chat=ref<ChatItem[]>([]),message=ref(''),chatLoading=ref(false),chatError=ref(''),originalOpen=ref(false)
const relatedLoading=ref(false),relatedError=ref(''),historyLoading=ref(false),historyError=ref(''),historyNotice=ref(''),chatSources=ref<Source[]>([])
const id=computed(()=>String(route.params.id)),allSources=computed(()=>[...new Map([...(topic.value?.sources||[]),...(explanation.value?.sources||[]),...chatSources.value].map(s=>[s.id,s])).values()])
function sourceFor(sid:string):Source|undefined{return allSources.value.find(x=>x.id===sid)}
let pageVersion=0,explainVersion=0,historyVersion=0,chatRevision=0
const messageOf=(e:unknown)=>e instanceof Error?e.message:'请求未完成，请重试。'
async function loadRelated(version=pageVersion,topicId=id.value){
 relatedLoading.value=true;relatedError.value=''
 try{const res=await api<{items:{topic:Topic;relation:Relation}[]}>(`/topics/${topicId}/related`);if(version===pageVersion)related.value=res.items}
 catch(e){if(version===pageVersion)relatedError.value=messageOf(e)}
 finally{if(version===pageVersion)relatedLoading.value=false}
}
async function loadHistory(version=pageVersion,topicId=id.value){
 const request=++historyVersion,revision=chatRevision
 historyLoading.value=true;historyError.value='';historyNotice.value=''
 try{
  const res=await api<{items:ChatItem[]}>(`/ai/chat?topic_id=${topicId}`)
  if(version===pageVersion&&request===historyVersion){
   if(revision===chatRevision)chat.value=res.items
   else historyNotice.value='讨论已更新，重新读取可查看完整历史。'
  }
 }catch(e){if(version===pageVersion&&request===historyVersion)historyError.value=messageOf(e)}
 finally{if(version===pageVersion&&request===historyVersion)historyLoading.value=false}
}
async function load(){
 const version=++pageVersion,topicId=id.value
 ++explainVersion;++historyVersion;chatRevision=0
 loading.value=true;error.value='';topic.value=null;related.value=[];explanation.value=null;chat.value=[];chatSources.value=[]
 aiError.value='';chatError.value='';historyError.value='';historyNotice.value='';relatedError.value='';message.value='';originalOpen.value=false
 busy.value=false;aiLoading.value=false;chatLoading.value=false;relatedLoading.value=false;historyLoading.value=false
 try{
  const result=await api<Topic>(`/topics/${topicId}`)
  if(version!==pageVersion)return
  topic.value=result;loading.value=false
  void loadRelated(version,topicId);void loadHistory(version,topicId)
 }catch(e){if(version===pageVersion)error.value=messageOf(e)}
 finally{if(version===pageVersion)loading.value=false}
}
async function bookmark(){
 if(!topic.value||busy.value)return
 const version=pageVersion,target=topic.value
 busy.value=true
 try{
  const result=target.state.bookmarked?await api<{state:State}>(`/bookmarks/${target.id}`,{method:'DELETE'}):await post<{state:State}>('/bookmarks',{topic_id:target.id})
  if(version!==pageVersion)return
  target.state=result.state;app.notify(target.state.bookmarked?'已收藏这条线索':'已取消收藏')
 }catch(e){if(version===pageVersion)app.notify(messageOf(e))}
 finally{if(version===pageVersion)busy.value=false}
}
async function feedback(action:string){
 if(!topic.value||busy.value)return
 const version=pageVersion,topicId=id.value
 busy.value=true
 try{
  const result=await post<{state:State}>(`/topics/${topicId}/feedback`,{action,idempotency_key:key()})
  if(version!==pageVersion)return
  if(topic.value)topic.value.state=result.state
  app.notify('已保存。学习状态来自你的主动标记。')
 }catch(e){if(version===pageVersion)app.notify(messageOf(e))}
 finally{if(version===pageVersion)busy.value=false}
}
async function explain(){
 if(aiLoading.value)return
 const version=pageVersion,request=++explainVersion,topicId=id.value,requestedDepth=depth.value
 aiLoading.value=true;aiError.value=''
 try{
  const result=await post<Explain>('/ai/explain',{topic_id:topicId,depth:requestedDepth,language:'zh'})
  if(version===pageVersion&&request===explainVersion)explanation.value=result
 }catch(e){if(version===pageVersion&&request===explainVersion)aiError.value=messageOf(e)}
 finally{if(version===pageVersion&&request===explainVersion)aiLoading.value=false}
}
async function send(){
 if(!message.value.trim()||chatLoading.value)return
 const version=pageVersion,topicId=id.value,content=message.value.trim(),requestedDepth=depth.value
 ++chatRevision
 chatLoading.value=true;chatError.value=''
 try{
  const res=await post<{status:string;message:string;answer:string;source_ids:string[];sources:Source[]}>('/ai/chat',{topic_id:topicId,message:content,depth:requestedDepth})
  if(version!==pageVersion)return
  if(res.status==='unavailable'){chatError.value=res.message;return}
  chat.value.push({role:'user',content},{role:'assistant',content:res.answer,source_ids:res.source_ids});chatSources.value.push(...res.sources)
  if(message.value.trim()===content)message.value=''
 }catch(e){if(version===pageVersion)chatError.value=messageOf(e)}
 finally{if(version===pageVersion)chatLoading.value=false}
}
watch(id,load,{flush:'sync'})
watch(depth,()=>{++explainVersion;explanation.value=null;aiError.value='';aiLoading.value=false},{flush:'sync'})
onMounted(load)
onBeforeUnmount(()=>{++pageVersion;++explainVersion;++historyVersion})
</script>
<template><div class="detail-page"><RouterLink to="/" class="back-link"><ArrowLeft :size="16"/>回到今日探索</RouterLink><Notice :loading="loading" :error="error" @retry="load"/><template v-if="topic&&!loading"><header class="topic-header"><div class="topic-breadcrumb"><span class="discipline-label" :style="{'--discipline':topic.primary_discipline.color}"><i/>{{topic.primary_discipline.name}}</span><span>/</span><span>{{topic.subfield}}</span><span class="tiny-label">KNOWLEDGE NOTE</span></div><h1>{{topic.title}}<span v-if="topic.original_title!==topic.title">{{topic.original_title}}</span></h1><p class="detail-question">{{topic.question}}</p><div class="detail-metadata"><span><Clock3 :size="15"/>约 {{topic.reading_minutes}} 分钟</span><span>{{topic.sources.length}} 个可追溯来源</span><span v-if="topic.state.explored"><Check :size="15"/>已留下探索足迹</span></div></header><div class="detail-layout"><div class="detail-main"><section class="content-section summary-section"><div class="section-heading"><span class="section-index">01</span><h2>先认识它</h2><span class="tiny-label">SOURCE SUMMARY</span></div><p class="source-tag">{{topic.quality_features?.summary_label||(topic.language==='zh'?'来源中文摘要':'来源原始摘要 · '+topic.language)}}<span>原始资料始终独立于 AI 解释</span></p><p v-if="topic.quality_features?.source_notice" class="soft-notice">{{topic.quality_features.source_notice}}</p><div class="prose summary-prose">{{topic.summary||topic.original_summary}}</div><div v-if="topic.value" class="value-callout"><BookOpen :size="20"/><div><h3>为什么值得了解？</h3><p>{{topic.value}}</p></div></div><button v-if="topic.original_summary" class="text-button" @click="originalOpen=!originalOpen" :aria-expanded="originalOpen"><ChevronDown :size="15" :class="{rotate:originalOpen}"/>{{originalOpen?'收起原始摘要':'查看原始摘要与语言'}}</button><div v-if="originalOpen" class="original-text"><span class="tiny-label">ORIGINAL · {{topic.language}}</span><p>{{topic.original_summary}}</p></div></section><section class="content-section ai-section"><div class="section-heading"><span class="section-index">02</span><h2>把知识读懂</h2><span class="ai-badge"><Sparkles :size="12"/>AI 导师</span></div><div class="ai-controls"><div class="depth-tabs" role="group" aria-label="解释深度"><button v-for="d in [{id:'beginner' as Depth,name:'一分钟看懂'},{id:'intermediate' as Depth,name:'进阶探索'},{id:'deep' as Depth,name:'深入理解'}]" :key="d.id" :class="{selected:depth===d.id}" :aria-pressed="depth===d.id" @click="depth=d.id">{{d.name}}</button></div><button class="button primary small" @click="explain" :disabled="aiLoading||!app.profile?.ai.configured"><Sparkles :size="14"/>{{aiLoading?'正在查阅证据…':explanation?.content?'重新读取解释':'生成解释'}}</button></div><div v-if="!app.profile?.ai.configured" class="ai-offline"><BookOpen :size="25"/><h3>先从真实资料开始。</h3><p>服务端尚未配置 AI。原始摘要、来源、收藏和认知地图都可以正常使用。</p><RouterLink to="/settings" class="text-button">查看 AI 配置说明 <ArrowUpRight :size="14"/></RouterLink></div><Notice v-if="aiLoading" loading/><div v-if="aiError" class="soft-notice inline-error" role="alert">{{aiError}} <button class="text-button" @click="explain">重试</button></div><p v-if="explanation&&!explanation.content" class="soft-notice">{{explanation.message||'当前资料不足，暂时无法提供合格的解释。'}}</p><div v-if="explanation?.content" class="ai-content"><p class="evidence-note"><ShieldCheck :size="14"/>{{explanation.cached?'读取已缓存解释':'基于当前来源生成'}} · 引用有效不代表每句话都已核实，请结合原始来源判断。</p><div v-for="part in [{title:'这是什么',text:explanation.content.overview},{title:'核心原理',text:explanation.content.principle},{title:'一个例子',text:explanation.content.example},{title:'背景与来路',text:explanation.content.background}]" :key="part.title" class="explanation-part"><template v-if="part.text"><h3>{{part.title}}</h3><p>{{part.text}}</p></template></div><div v-if="explanation.content.analogy" class="analogy-note"><span class="tiny-label">教学类比 · 帮助理解</span><p>{{explanation.content.analogy.text}}</p><small>适用边界：{{explanation.content.analogy.limits}}</small></div><div v-for="part in [{title:'真实应用',list:explanation.content.applications},{title:'常见误解',list:explanation.content.misconceptions},{title:'前沿与开放问题',list:explanation.content.open_questions}]" :key="part.title" class="explanation-part"><template v-if="part.list?.length"><h3>{{part.title}}</h3><ul><li v-for="(line,i) in part.list" :key="i">{{line}}</li></ul></template></div><p v-if="!explanation.content.open_questions?.length" class="muted">现有资料不足以支持前沿或开放问题，暂不扩展。</p><div v-if="explanation.content.claims?.length" class="claims"><h3>关键陈述与引用</h3><div v-for="(claim,i) in explanation.content.claims" :key="i" class="claim"><span class="claim-type">{{claim.kind==='fact'?'事实说明':claim.kind==='analogy'?'教学类比':'待核实'}}</span><p>{{claim.text}}</p><template v-for="sid in claim.source_ids" :key="sid"><a v-if="sourceFor(sid)" :href="safeUrl(sourceFor(sid)?.url)" target="_blank" rel="noopener noreferrer" class="source-chip">{{sourceFor(sid)?.platform}} [{{sid}}]<ArrowUpRight :size="11"/></a></template></div></div><div v-if="explanation.content.questions?.length" class="thinking-questions"><span class="tiny-label">THINK A LITTLE FURTHER</span><h3>带着问题再往前一步</h3><p v-for="(question,i) in explanation.content.questions" :key="i">0{{i+1}} — {{question}}</p></div><p class="usage-note" v-if="explanation.usage">供应商 usage：输入 {{explanation.usage.input_tokens??'未知'}} / 输出 {{explanation.usage.output_tokens??'未知'}} Token · 未配置价格不估算费用</p></div><p v-else-if="app.profile?.ai.configured&&!aiLoading&&!aiError&&!explanation" class="muted ai-prompt">选择深度，再按需生成。刷新页面不会自动调用模型。</p></section><section id="sources" class="content-section"><div class="section-heading"><span class="section-index">03</span><h2>沿着来源查证</h2><span class="tiny-label">FOLLOW THE EVIDENCE</span></div><div class="source-list"><article v-for="(source,i) in topic.sources" :key="source.id"><span class="source-number">[{{i+1}}]</span><div><span class="tiny-label">{{source.platform}} · {{source.language}}</span><h3><a :href="safeUrl(source.url)" target="_blank" rel="noopener noreferrer">{{source.title||topic.original_title}}<ArrowUpRight :size="16"/></a></h3><p>{{source.license||'许可信息未提供，请查看原始来源。'}}</p><small>采集于 {{source.fetched_at?new Date(source.fetched_at).toLocaleDateString('zh-CN'):'未记录'}}<span v-if="source.updated_at"> · 来源更新于 {{new Date(source.updated_at).toLocaleDateString('zh-CN')}}</span></small><details v-if="source.excerpt"><summary>查看允许用于解释的来源片段</summary><p class="source-excerpt">{{source.excerpt}}</p></details></div></article></div></section><section class="content-section discussion"><div class="section-heading"><span class="section-index">04</span><h2>继续追问</h2><span class="tiny-label">A TOPIC-FOCUSED DIALOGUE</span></div><p class="muted">围绕这个主题和相关知识讨论。聊天按当前匿名档案隔离。</p><p v-if="historyLoading" class="muted" role="status">正在读取历史讨论…</p><p v-if="historyError" class="inline-error" role="alert">历史讨论读取失败：{{historyError}} <button class="text-button" :disabled="chatLoading||historyLoading" @click="loadHistory()">重试读取历史</button></p><p v-if="historyNotice" class="muted">{{historyNotice}} <button class="text-button" :disabled="chatLoading||historyLoading" @click="loadHistory()">重新读取完整历史</button></p><div v-if="chat.length" class="chat-history" aria-live="polite"><article v-for="(item,i) in chat" :key="i" :class="['chat-message',item.role]"><span class="tiny-label">{{item.role==='user'?'你的问题':'AI 导师 · 基于来源的讨论'}}</span><p>{{item.content}}</p><template v-for="sid in item.source_ids" :key="sid"><a v-if="sourceFor(sid)" :href="safeUrl(sourceFor(sid)?.url)" target="_blank" rel="noopener noreferrer" class="source-chip">来源 {{sid}}<ArrowUpRight :size="11"/></a></template></article></div><form class="chat-form" @submit.prevent="send"><label class="sr-only" for="chat-input">针对当前主题提问</label><textarea id="chat-input" v-model="message" rows="3" maxlength="2000" :disabled="!app.profile?.ai.configured||chatLoading" :placeholder="app.profile?.ai.configured?'这个概念和生活中的哪些现象有关？':'配置服务端 AI 后，可以围绕这个主题继续提问。'"/><div><span>最多 2,000 字 · 只使用允许的证据</span><button class="button primary small" type="submit" :disabled="!message.trim()||!app.profile?.ai.configured||chatLoading">{{chatLoading?'正在思考…':'发送问题'}}<Send :size="14"/></button></div></form><p v-if="chatError" class="inline-error" role="alert">{{chatError}}</p></section></div><aside class="detail-aside"><div class="aside-panel learning-panel"><span class="tiny-label">YOUR EXPLORATION</span><h3>把这条线索留下。</h3><button class="button full" :class="topic.state.bookmarked?'primary':'outline'" @click="bookmark" :disabled="busy"><Bookmark :size="17" :fill="topic.state.bookmarked?'currentColor':'none'"/>{{topic.state.bookmarked?'已收藏 · 点击取消':'收藏这个主题'}}</button><div class="aside-divider"/><p class="field-label">之前，你了解它吗？</p><div class="feedback-options"><button :class="{selected:topic.state.familiarity==='known'}" :aria-pressed="topic.state.familiarity==='known'" @click="feedback('known')" :disabled="busy"><Check :size="15"/>已了解</button><button :class="{selected:topic.state.familiarity==='unfamiliar'}" :aria-pressed="topic.state.familiarity==='unfamiliar'" @click="feedback('unfamiliar')" :disabled="busy"><HelpCircle :size="15"/>完全陌生</button></div><label class="field-label" for="learning-status">现在的学习状态</label><select id="learning-status" :value="topic.state.learning" @change="feedback(($event.target as HTMLSelectElement).value)" :disabled="busy"><option value="none">尚未标记</option><option value="learning">正在学习</option><option value="understood">自述已理解</option></select><p class="privacy-note">访问只记录“探索”，不会自动判定你已经理解。收藏与学习状态独立保存。</p></div><div class="aside-panel related-panel"><span class="tiny-label">CONNECTED IDEAS</span><h3>知识从不孤立。</h3><p v-if="relatedLoading" class="muted" role="status">正在读取关联…</p><p v-else-if="relatedError" class="inline-error" role="alert">{{relatedError}} <button class="text-button" @click="loadRelated()">重试关联</button></p><div v-else-if="!related.length" class="muted">暂未找到有依据的关联。不会为凑数生成连线。</div><article v-for="item in related" :key="item.relation.id" class="related-topic"><span class="relation-label"><Link2 :size="12"/>{{item.relation.label||item.relation.type}} · {{item.relation.type}}</span><RouterLink :to="`/topics/${item.topic.id}`"><h4>{{item.topic.title}}<ArrowUpRight :size="15"/></h4></RouterLink><p class="relation-endpoints">{{item.relation.source_title}} {{item.relation.direction==='both'?'↔':'→'}} {{item.relation.target_title}}</p><p>{{item.relation.explanation}}</p><a :href="safeUrl(item.relation.source_url)" target="_blank" rel="noopener noreferrer" class="text-button">查看关系依据<ArrowUpRight :size="13"/></a></article><RouterLink :to="{path:'/map',query:{root:'topic:'+id}}" class="text-button">在认知地图中探索<ArrowUpRight :size="14"/></RouterLink></div></aside></div></template></div></template>
