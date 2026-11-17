<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,watch,computed} from 'vue'
import {useRoute} from 'vue-router'
import {ArrowLeft,ArrowUpRight,Bookmark,Check,BookOpen,HelpCircle,Clock3,Link2,Sparkles,Send,ChevronDown} from 'lucide-vue-next'
import {api,post,key,safeUrl} from '../api'
import type {Topic,Relation,Depth,State,Explain,ChatItem,Source} from '../types'
import {useApp} from '../stores/app'
import Notice from '../components/Notice.vue'
import SourceList from '../components/SourceList.vue'
import AIExplanation from '../components/AIExplanation.vue'
import GraphConceptDemo from '../components/GraphConceptDemo.vue'
import ExplorationPath from '../components/ExplorationPath.vue'
import CognitiveChallenge from '../components/CognitiveChallenge.vue'
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
  const res=await post<{status:string;message:string;answer:string;source_ids:string[];sources:Source[];evidence_refs?:{source_id:string;quote:string;evidence_type:string}[]}>('/ai/chat',{topic_id:topicId,message:content,depth:requestedDepth})
  if(version!==pageVersion)return
  if(res.status==='unavailable'){chatError.value=res.message;return}
  chat.value.push({role:'user',content},{role:'assistant',content:res.answer,source_ids:res.source_ids,evidence_refs:res.evidence_refs});chatSources.value.push(...res.sources)
  if(message.value.trim()===content)message.value=''
 }catch(e){if(version===pageVersion)chatError.value=messageOf(e)}
 finally{if(version===pageVersion)chatLoading.value=false}
}
watch(id,load,{flush:'sync'})
watch(depth,()=>{++explainVersion;explanation.value=null;aiError.value='';aiLoading.value=false},{flush:'sync'})
onMounted(load)
onBeforeUnmount(()=>{++pageVersion;++explainVersion;++historyVersion})
</script>
<template><div class="detail-page"><RouterLink to="/" class="back-link"><ArrowLeft :size="16"/>回到今日探索</RouterLink><Notice :loading="loading" :error="error" @retry="load"/><template v-if="topic&&!loading"><header class="topic-header"><div class="topic-breadcrumb"><span class="discipline-label" :style="{'--discipline':topic.primary_discipline.color}"><i/>{{topic.primary_discipline.name}}</span><span>/</span><span>{{topic.subfield}}</span><span class="tiny-label">KNOWLEDGE NOTE</span></div><h1>{{topic.title}}<span v-if="topic.original_title!==topic.title">{{topic.original_title}}</span></h1><p class="detail-question">{{topic.question}}</p><div class="detail-metadata"><span><Clock3 :size="15"/>约 {{topic.reading_minutes}} 分钟</span><span>{{topic.sources.length}} 个可追溯来源</span><span v-if="topic.state.explored"><Check :size="15"/>已留下探索足迹</span></div></header><div class="detail-layout"><div class="detail-main"><section class="content-section summary-section"><div class="section-heading"><span class="section-index">01</span><h2>先认识它</h2><span class="tiny-label">SOURCE SUMMARY</span></div><p class="source-tag">{{topic.quality_features?.summary_label||(topic.language==='zh'?'来源中文摘要':'来源原始摘要 · '+topic.language)}}<span>原始资料始终独立于 AI 解释</span></p><p v-if="topic.quality_features?.source_notice" class="soft-notice">{{topic.quality_features.source_notice}}</p><div class="prose summary-prose">{{topic.summary||topic.original_summary}}</div><div v-if="topic.content_intro?.entry_example" class="value-callout"><div><h3>理解入口 · 教学例子</h3><p>{{topic.content_intro.entry_example}}</p></div></div><div v-if="topic.value" class="value-callout"><BookOpen :size="20"/><div><h3>为什么值得了解？</h3><p>{{topic.value}}</p></div></div><button v-if="topic.original_summary" class="text-button" @click="originalOpen=!originalOpen" :aria-expanded="originalOpen"><ChevronDown :size="15" :class="{rotate:originalOpen}"/>{{originalOpen?'收起原始摘要':'查看原始摘要与语言'}}</button><div v-if="originalOpen" class="original-text"><span class="tiny-label">ORIGINAL · {{topic.language}}</span><p>{{topic.original_summary}}</p></div></section><section id="sources" class="content-section"><div class="section-heading"><span class="section-index">02</span><h2>沿着来源查证</h2><span class="tiny-label">FOLLOW THE EVIDENCE</span></div><SourceList :sources="topic.sources"/></section><GraphConceptDemo v-if="id==='graph-theory'"/><p v-if="topic.content_status!=='PUBLISHED'" class="soft-notice">材料状态：{{topic.content_status}}。{{topic.content_checks?.reasons?.join(' ')}} 这类条目暂不进入新推荐。</p><section class="content-section ai-section"><div class="section-heading"><span class="section-index">03</span><h2>把知识读懂</h2><span class="ai-badge"><Sparkles :size="12"/>AI 导师</span></div><div class="ai-controls"><div class="depth-tabs" role="group" aria-label="解释深度"><button v-for="d in [{id:'beginner' as Depth,name:'一分钟看懂'},{id:'intermediate' as Depth,name:'进阶探索'},{id:'deep' as Depth,name:'深入理解'}]" :key="d.id" :class="{selected:depth===d.id}" :aria-pressed="depth===d.id" @click="depth=d.id">{{d.name}}</button></div><button class="button primary small" @click="explain" :disabled="aiLoading||!app.profile?.ai.configured"><Sparkles :size="14"/>{{aiLoading?'正在查阅证据…':explanation?.content?'重新读取解释':'生成解释'}}</button></div><div v-if="!app.profile?.ai.configured" class="ai-offline"><BookOpen :size="25"/><h3>先从真实资料开始。</h3><p>服务端尚未配置 AI。原始摘要、来源、收藏和认知地图都可以正常使用。</p><RouterLink to="/settings" class="text-button">查看 AI 配置说明 <ArrowUpRight :size="14"/></RouterLink></div><Notice v-if="aiLoading" loading/><div v-if="aiError" class="soft-notice inline-error" role="alert">{{aiError}} <button class="text-button" @click="explain">重试</button></div><p v-if="explanation&&!explanation.content" class="soft-notice">{{explanation.message||'当前资料不足，暂时无法提供合格的解释。'}}</p><AIExplanation v-if="explanation?.content" :explanation="explanation" :sources="allSources"/><p v-else-if="app.profile?.ai.configured&&!aiLoading&&!aiError&&!explanation" class="muted ai-prompt">选择深度，再按需生成。刷新页面不会自动调用模型。</p></section><ExplorationPath :key="'path-'+id" :topic-id="id"/><CognitiveChallenge :key="'challenge-'+id" :topic-id="id"/><section class="content-section discussion"><div class="section-heading"><span class="section-index">04</span><h2>继续追问</h2><span class="tiny-label">A TOPIC-FOCUSED DIALOGUE</span></div><p class="muted">围绕这个主题和相关知识讨论。聊天按当前匿名档案隔离。</p><p v-if="historyLoading" class="muted" role="status">正在读取历史讨论…</p><p v-if="historyError" class="inline-error" role="alert">历史讨论读取失败：{{historyError}} <button class="text-button" :disabled="chatLoading||historyLoading" @click="loadHistory()">重试读取历史</button></p><p v-if="historyNotice" class="muted">{{historyNotice}} <button class="text-button" :disabled="chatLoading||historyLoading" @click="loadHistory()">重新读取完整历史</button></p><div v-if="chat.length" class="chat-history" aria-live="polite"><article v-for="(item,i) in chat" :key="i" :class="['chat-message',item.role]"><span class="tiny-label">{{item.role==='user'?'你的问题':'AI 导师 · 基于来源的讨论'}}</span><p>{{item.content}}</p><blockquote v-for="(ref,j) in item.evidence_refs||[]" :key="j" class="located-quote">保存时的引用片段：{{ref.quote}}</blockquote><template v-for="sid in item.source_ids" :key="sid"><a v-if="sourceFor(sid)" :href="safeUrl(sourceFor(sid)?.url)" target="_blank" rel="noopener noreferrer" class="source-chip">来源 {{sid}}<ArrowUpRight :size="11"/></a></template></article></div><form class="chat-form" @submit.prevent="send"><label class="sr-only" for="chat-input">针对当前主题提问</label><textarea id="chat-input" v-model="message" rows="3" maxlength="2000" :disabled="!app.profile?.ai.configured||chatLoading" :placeholder="app.profile?.ai.configured?'这个概念和生活中的哪些现象有关？':'配置服务端 AI 后，可以围绕这个主题继续提问。'"/><div><span>最多 2,000 字 · 只使用允许的证据</span><button class="button primary small" type="submit" :disabled="!message.trim()||!app.profile?.ai.configured||chatLoading">{{chatLoading?'正在思考…':'发送问题'}}<Send :size="14"/></button></div></form><p v-if="chatError" class="inline-error" role="alert">{{chatError}}</p></section></div><aside class="detail-aside"><div class="aside-panel learning-panel"><span class="tiny-label">YOUR EXPLORATION</span><h3>把这条线索留下。</h3><button class="button full" :class="topic.state.bookmarked?'primary':'outline'" @click="bookmark" :disabled="busy"><Bookmark :size="17" :fill="topic.state.bookmarked?'currentColor':'none'"/>{{topic.state.bookmarked?'已收藏 · 点击取消':'收藏这个主题'}}</button><div class="aside-divider"/><p class="field-label">之前，你了解它吗？</p><div class="feedback-options"><button :class="{selected:topic.state.familiarity==='known'}" :aria-pressed="topic.state.familiarity==='known'" @click="feedback('known')" :disabled="busy"><Check :size="15"/>已了解</button><button :class="{selected:topic.state.familiarity==='unfamiliar'}" :aria-pressed="topic.state.familiarity==='unfamiliar'" @click="feedback('unfamiliar')" :disabled="busy"><HelpCircle :size="15"/>完全陌生</button></div><label class="field-label" for="familiarity-gap">更具体的认知状态</label><select id="familiarity-gap" :value="topic.state.familiarity" @change="feedback(($event.target as HTMLSelectElement).value)" :disabled="busy"><option value="unknown" disabled>尚未主动标记</option><option value="unfamiliar">自述完全陌生</option><option value="name_only">听过名称，不懂含义</option><option value="concept_only">了解概念，想了解应用</option><option value="connections_unknown">想了解跨学科联系</option><option value="forgotten">以前接触过，已经忘记</option><option value="known">自述已了解</option></select><label class="field-label" for="learning-status">现在的学习状态</label><select id="learning-status" :value="topic.state.learning" @change="feedback(($event.target as HTMLSelectElement).value)" :disabled="busy"><option value="none">尚未标记</option><option value="learning">正在学习</option><option value="understood">自述已理解</option></select><button class="button outline full" :disabled="busy" @click="feedback(topic.state.revisit_at?'cancel_revisit':'revisit')">{{topic.state.revisit_at?'取消回访意愿':'希望一周后回访'}}</button><p v-if="topic.state.revisit_at" class="privacy-note">回访入口将于 {{new Date(topic.state.revisit_at).toLocaleDateString('zh-CN')}} 在首页出现。</p><p class="field-label">这次是否值得了解？</p><div class="feedback-options"><button :aria-pressed="topic.state.worthwhile===true" :class="{selected:topic.state.worthwhile===true}" :disabled="busy" @click="feedback('worthwhile')">值得了解</button><button :aria-pressed="topic.state.worthwhile===false" :class="{selected:topic.state.worthwhile===false}" :disabled="busy" @click="feedback('not_worthwhile')">暂时不值得</button></div><p class="privacy-note">访问只记录“探索”，不会自动判定你已经理解。收藏与学习状态独立保存。</p></div><div class="aside-panel related-panel"><span class="tiny-label">CONNECTED IDEAS</span><h3>知识从不孤立。</h3><p v-if="relatedLoading" class="muted" role="status">正在读取关联…</p><p v-else-if="relatedError" class="inline-error" role="alert">{{relatedError}} <button class="text-button" @click="loadRelated()">重试关联</button></p><div v-else-if="!related.length" class="muted">暂未找到有依据的关联。不会为凑数生成连线。</div><article v-for="item in related" :key="item.relation.id" class="related-topic"><span class="relation-label"><Link2 :size="12"/>{{item.relation.label||item.relation.type}} · {{item.relation.type}}</span><RouterLink :to="`/topics/${item.topic.id}`"><h4>{{item.topic.title}}<ArrowUpRight :size="15"/></h4></RouterLink><p class="relation-endpoints">{{item.relation.source_title}} {{item.relation.direction==='both'?'↔':'→'}} {{item.relation.target_title}}</p><p>{{item.relation.explanation}}</p><a :href="safeUrl(item.relation.source_url)" target="_blank" rel="noopener noreferrer" class="text-button">查看关系依据<ArrowUpRight :size="13"/></a></article><RouterLink :to="{path:'/map',query:{root:'topic:'+id}}" class="text-button">在认知地图中探索<ArrowUpRight :size="14"/></RouterLink></div></aside></div></template></div></template>
