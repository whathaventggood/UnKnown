<script setup lang="ts">
import {ref,computed,watch,onBeforeUnmount} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api,post,key,safeUrl} from '../api'
import type {ExplorationPath} from '../types'
const props=defineProps<{topicId:string}>(),route=useRoute(),router=useRouter()
const paths=ref<ExplorationPath[]>([]),selected=ref(0),loading=ref(false),busy=ref(false),error=ref(''),notice=ref('')
const current=computed(()=>paths.value[selected.value]),position=computed(()=>Math.max(0,current.value?.topic_ids.indexOf(props.topicId)??0))
const hop=computed(()=>current.value?.hops[position.value]),previous=computed(()=>current.value?.topic_ids[position.value-1])
let version=0,pending=''
async function load(){
 const v=++version;loading.value=true;busy.value=false;error.value='';paths.value=[];selected.value=0;notice.value='';pending=''
 try{
  if(typeof route.query.path==='string'){
   const result=await api<ExplorationPath>(`/paths/${encodeURIComponent(route.query.path)}`)
   if(v!==version)return
   if(result.topic_ids.includes(props.topicId)){paths.value=[result];notice.value=result.evidence_changed?'保存后的关系依据已变化，请重新核对来源。':'正在继续你主动保存的路径。';return}
   notice.value='当前主题不在指定路径中，已读取此主题的可用路径。'
  }
  const root=typeof route.query.path_root==='string'?route.query.path_root:props.topicId
  const result=await api<{items:ExplorationPath[];message:string}>(`/topics/${encodeURIComponent(root)}/paths`)
  if(v!==version)return
  paths.value=result.items;notice.value=result.message
  const relations=route.query.path_relations
  const index=paths.value.findIndex(p=>p.relation_ids.join('|')===relations&&p.topic_ids.includes(props.topicId))
  if(index>=0)selected.value=index
  else if(root!==props.topicId){
   const fallback=await api<{items:ExplorationPath[];message:string}>(`/topics/${encodeURIComponent(props.topicId)}/paths`)
   if(v!==version)return
   paths.value=fallback.items;notice.value='此前预览路径已变化。'+fallback.message
  }
 }catch(e){if(v===version)error.value=e instanceof Error?e.message:'路径读取失败。'}
 finally{if(v===version)loading.value=false}
}
function target(topicId:string){
 const p=current.value
 return {path:`/topics/${topicId}`,query:p?.id?{path:p.id}:{path_root:p?.topic_ids[0],path_relations:p?.relation_ids.join('|')}}
}
async function save(){
 const path=current.value;if(!path||busy.value)return
 const v=version;busy.value=true;error.value='';pending||=key()
 try{
  const saved=await post<ExplorationPath>('/paths',{topic_ids:path.topic_ids,relation_ids:path.relation_ids,idempotency_key:pending})
  if(v!==version)return
  paths.value=[saved];selected.value=0;pending='';notice.value='路径已保存，可在“我的探索 → 已保存路径”重新打开。'
  void router.replace({query:{path:saved.id}})
 }catch(e){if(v===version)error.value=e instanceof Error?e.message:'路径保存失败。'}
 finally{if(v===version)busy.value=false}
}
async function rememberPosition(){
 const p=current.value
 if(p?.id&&p.available!==false&&p.position!==position.value){
  try{await api(`/paths/${p.id}`,{method:'PATCH',body:JSON.stringify({position:position.value})})}catch{/* Reading remains available if progress could not be saved. */}
 }
}
watch(()=>[props.topicId,route.query.path,route.query.path_root,route.query.path_relations],()=>void load().then(rememberPosition),{immediate:true})
watch(selected,()=>{pending='';error.value=''})
onBeforeUnmount(()=>{++version})
</script>
<template><section class="content-section path-explorer" aria-label="从这个知识继续探索">
 <div class="section-heading"><h2>从这个知识继续探索</h2></div>
 <p v-if="loading" role="status">正在寻找有依据的联系…</p><p v-if="error" role="alert" class="inline-error">{{error}} <button class="text-button" @click="load">重试路径</button></p><p v-if="notice" class="muted">{{notice}}</p>
 <template v-if="current&&!loading">
  <label v-if="paths.length>1">探索方向<select v-model="selected" :disabled="busy"><option v-for="(p,i) in paths" :key="i" :value="i">{{p.hops[p.hops.length-1]?.to_title}} · {{p.hops.length}} 步</option></select></label>
  <ol class="path-nodes"><li v-for="(topicId,i) in current.topic_ids" :key="topicId" :class="{current:i===position}"><RouterLink :to="target(topicId)" :aria-current="i===position?'step':undefined">{{i===0?current.hops[0]?.from_title:current.hops[i-1]?.to_title}}</RouterLink></li></ol>
  <p v-if="current.available===false" role="status">保存的路径依据已不可用。下面保留保存时的记录，请重新检查资料。</p>
  <article v-if="hop" class="path-hop"><span class="source-chip">{{hop.type==='teaching'?'编辑教学联系':'事实关系'}} · {{hop.cross_discipline?'跨越学科':'同学科延伸'}}</span><h3>{{hop.from_title}} → {{hop.to_title}}</h3><p>{{hop.explanation}}</p><p class="muted">{{hop.evidence_note}}</p><blockquote v-if="hop.evidence_excerpt">{{hop.evidence_excerpt}}</blockquote><p v-else class="privacy-note">关系保留核对链接，未保存完整原文片段。</p><a :href="safeUrl(hop.source_url)" target="_blank" rel="noopener noreferrer" class="text-button">原始关系来源 ↗</a></article>
  <p v-else class="muted">已走到这条路径的末尾。你可以返回上一节点，或从当前主题另选方向。</p>
  <div class="path-actions"><RouterLink v-if="previous" :to="target(previous)" class="button outline small">返回上一节点</RouterLink><RouterLink v-if="hop&&current.available!==false" :to="target(hop.to_id)" class="button primary small">继续探索：{{hop.to_title}}</RouterLink><button v-if="!current.id" class="button outline small" @click="save" :disabled="busy">{{busy?'正在保存…':'保存这条路径'}}</button><RouterLink v-else to="/journey?tab=paths" class="text-button">查看已保存路径</RouterLink></div>
 </template>
</section></template>
<style scoped>
.path-nodes{display:flex;gap:8px;flex-wrap:wrap;list-style:decimal;padding-left:22px;line-height:2}.path-nodes li{padding-right:20px}.path-nodes .current{font-weight:700;text-decoration:underline}.path-hop{padding:16px 0;line-height:1.8}.path-hop h3{font-size:20px;margin:12px 0}.path-actions{display:flex;flex-wrap:wrap;gap:12px}.path-actions a{white-space:normal}.path-explorer select{display:block;margin-top:8px;max-width:100%}
</style>
