<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,computed,watch,nextTick} from 'vue'
import {ArrowRight,RefreshCw,Sparkles,Route,Globe2,ArrowUpRight,SlidersHorizontal} from 'lucide-vue-next'
import {onBeforeRouteLeave} from 'vue-router'
import {savedMode,saveMode,exploration} from '../utils/exploration'
import {api,post,key,dateLabel} from '../api'
import type {Batch,Mode,Stats} from '../types'
import {useApp} from '../stores/app'
import Notice from '../components/Notice.vue'
import SurpriseDiscover from '../components/SurpriseDiscover.vue'
import RevisitList from '../components/RevisitList.vue'
import TopicCard from '../components/TopicCard.vue'
const app=useApp(),mode=ref<Mode>(savedMode()),batch=ref<Batch|null>(null),stats=ref<Stats|null>(null),loading=ref(true),error=ref(''),refreshing=ref(false),showConfig=ref(false),intensity=ref(app.profile?.intensity??.65),saving=ref(false)
const modes=[{id:'unknown' as Mode,label:'完全陌生',icon:Sparkles,caption:'给尚未探索的领域，一个被发现的机会。'},{id:'bridge' as Mode,label:'跨领域桥梁',icon:Route,caption:'从熟悉的概念出发，走进另一个领域。'},{id:'broad' as Mode,label:'广域探索',icon:Globe2,caption:'不按兴趣排序，让学科分层带你看更宽的世界。'}]
const currentMode=computed(()=>modes.find(m=>m.id===mode.value)!),coverage=computed(()=>new Set(batch.value?.items.map(x=>x.topic.primary_discipline.id)).size)
let sequence=0,timer:ReturnType<typeof setTimeout>|undefined,active=true
const pendingRefresh=computed(()=>exploration.pendingRefresh.has(mode.value))
// Snapshot each batch before sending; retry once without blocking mode changes.
const pendingImpressions=new Map<string,Set<string>>()
async function load(restore=false){
 const seq=++sequence,requestedMode=mode.value
 loading.value=true;error.value=''
 try{
  const result=await api<Batch>(`/discover/today?mode=${requestedMode}`)
  if(seq!==sequence)return
  batch.value=result;loading.value=false
  if(restore){await nextTick();if(seq===sequence)window.scrollTo({top:exploration.scroll,behavior:'instant'})}
 }catch(e){if(seq===sequence)error.value=e instanceof Error?e.message:'加载失败'}
 finally{if(seq===sequence)loading.value=false}
}
async function refresh(){
 if(refreshing.value||loading.value)return
 const seq=++sequence,requestedMode=mode.value
 const operation=exploration.pendingRefresh.get(requestedMode)||key()
 exploration.pendingRefresh.set(requestedMode,operation)
 refreshing.value=true;error.value='';void flush()
 try{
  const result=await post<Batch>('/discover/refresh',{mode:requestedMode,idempotency_key:operation})
  if(exploration.pendingRefresh.get(requestedMode)===operation)exploration.pendingRefresh.delete(requestedMode)
  if(seq===sequence){batch.value=result;app.notify('新的一组探索已准备好')}
 }catch(e){if(seq===sequence)error.value=e instanceof Error?e.message:'换组失败'}
 finally{if(seq===sequence)refreshing.value=false}
}
function impression(id:string,batchId:string){
 const ids=pendingImpressions.get(batchId)||new Set<string>();ids.add(id);pendingImpressions.set(batchId,ids)
 clearTimeout(timer);timer=setTimeout(()=>void flush(),350)
}
async function flush(){
 clearTimeout(timer)
 const pending=[...pendingImpressions.entries()];pendingImpressions.clear()
 await Promise.all(pending.map(async([batchId,ids])=>{
  for(let attempt=0;attempt<2;attempt++){
   try{await post('/discover/impressions',{batch_id:batchId,topic_ids:[...ids]});return}
   catch{if(attempt===1&&active)app.notify('部分曝光记录未保存，不影响阅读；下次展示时会再次尝试。')}
  }
 }))
}
async function saveConfig(){saving.value=true;try{await app.update({intensity:Number(intensity.value)});if(batch.value)batch.value.settings_changed=true;showConfig.value=false;app.notify('设置已保存；点击“换一组”应用到新批次。')}catch(e){app.notify(e instanceof Error?e.message:'保存失败')}finally{saving.value=false}}
watch(mode,()=>{saveMode(mode.value);exploration.scroll=0;void flush();void load()},{flush:'sync'})
onMounted(async()=>{await load(true);try{stats.value=await api<Stats>('/stats')}catch{/* stats is independent */}})
onBeforeRouteLeave(()=>{exploration.scroll=window.scrollY})
onBeforeUnmount(()=>{active=false;++sequence;clearTimeout(timer);void flush()})
</script>
<template><div class="discover-page"><section class="discover-hero"><div class="hero-main"><p class="eyebrow"><span class="line"/> THE ART OF NOT KNOWING</p><h1>在已知的边界外，<br>遇见<span class="serif-accent">新的可能。</span></h1><p class="hero-description">好奇心不需要搜索关键词。<br>每天五个有来源的知识入口，走向你还不知道的世界。</p><RouterLink to="/map" class="text-button hero-link">看看你的认知地图 <ArrowUpRight :size="17"/></RouterLink></div><div class="hero-side"><div class="edition-top"><span>DAILY EXPLORATION</span><span>{{batch?dateLabel(batch.date):'今日'}}</span></div><div class="edition-number"><span>{{String(batch?.items.length??5).padStart(2,'0')}}</span><i>个通向未知的入口</i></div><div class="edition-bottom"><span class="dot-pulse"/>带着问题出发，带着联系回来。<span>↗</span></div></div></section><SurpriseDiscover/><RevisitList due-only/><section class="exploration-toolbar" aria-label="推荐设置"><div class="mode-tabs" role="group" aria-label="探索模式"><button v-for="m in modes" :key="m.id" :class="{selected:mode===m.id}" @click="mode=m.id" :aria-pressed="mode===m.id" :disabled="refreshing"><component :is="m.icon" :size="17"/>{{m.label}}</button></div><div class="toolbar-actions"><button class="icon-button settings-toggle" aria-label="调整探索强度" :aria-expanded="showConfig" @click="showConfig=!showConfig"><SlidersHorizontal :size="18"/></button><button class="button outline refresh-button" :disabled="loading||refreshing" @click="refresh"><RefreshCw :size="15" :class="{spin:refreshing}"/>{{refreshing?'正在准备…':pendingRefresh?'重试换组':'换一组'}}</button></div></section><div v-if="showConfig" class="inline-config"><label for="explore-intensity">探索强度 <span>{{Number(intensity).toFixed(2)}}</span></label><input id="explore-intensity" type="range" min="0" max="1" step=".05" v-model="intensity"><span>更高强度会增加陌生领域的权重。</span><button class="button small primary" :disabled="saving" @click="saveConfig">保存设置</button></div><div class="section-caption"><p>{{currentMode.caption}}<span v-if="mode==='broad'"> {{app.profile?.broad_use_history?'用近期曝光减少重复。':'完全不使用个人历史。'}}</span></p><span v-if="batch&&!loading&&batch.mode===mode">{{coverage}} 个主学科 · 第 {{batch.batch_number}} 组</span></div><p v-if="pendingRefresh&&!refreshing" class="soft-notice">上次换组尚未确认。点击“重试换组”继续同一次操作，不会额外创建批次。</p><div v-if="batch?.settings_changed" class="soft-notice">推荐设置已更新。当前推荐保持稳定，点击“换一组”按新设置生成。</div><Notice :loading="loading" :error="error" @retry="pendingRefresh?refresh():load()"/><template v-if="batch&&!loading&&!error"><div v-if="batch.constraints.relaxed.length||batch.constraints.reason_codes.length" class="soft-notice">{{batch.constraints.message||'受候选库或关系数量限制，本批部分约束已放宽。'}}<span v-if="batch.items.length<5"> 本次提供 {{batch.items.length}} 条真实主题。</span></div><div v-if="batch.items.length" class="topic-grid"><TopicCard v-for="(item,index) in batch.items" :key="`${batch.id}-${item.topic.id}`" :item="item" :index="index" :batch-id="batch.id" @impression="impression"/></div><Notice v-else empty="当前没有满足来源要求的候选主题。请检查知识库初始化状态。"/><div class="batch-footnote"><span>✓ 每条推荐都有真实来源</span><span>可能陌生 ≠ 已证明不了解 · 同日刷新页面保留当前批次</span></div></template><section v-if="stats" class="journey-preview"><div class="journey-preview-title"><span class="eyebrow">YOUR EXPANDING WORLD</span><h2>好奇心，正在留下足迹。</h2><RouterLink to="/journey" class="text-button">查看我的探索 <ArrowRight :size="16"/></RouterLink></div><div class="preview-stats"><div><strong>{{stats.explored_count}}</strong><span>已探索主题</span></div><div><strong>{{stats.discipline_count}}</strong><span>已接触主学科</span></div><div><strong>{{stats.bookmark_count}}</strong><span>收藏的线索</span></div></div><div v-if="stats.timeline.length" class="recent-exploration"><span class="tiny-label">RECENTLY EXPLORED</span><RouterLink v-for="t in stats.timeline.slice(0,3)" :key="`${t.topic_id}-${t.at}`" :to="`/topics/${t.topic_id}`"><span>{{t.title}}</span><ArrowUpRight :size="14"/></RouterLink></div><p v-else class="muted">从上方任意一个主题开始。第一次成功打开详情，会留下你的第一步足迹。</p></section><div class="closing-note"><span>STAY CURIOUS.</span><p>世界远比我们已经知道的，更辽阔。</p><span>∞</span></div></div></template>
