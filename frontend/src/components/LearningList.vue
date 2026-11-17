<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {ArrowUpRight} from 'lucide-vue-next'
import {api,post,key} from '../api'
import type {Topic} from '../types'
import {useApp} from '../stores/app'
import Notice from './Notice.vue'
const route=useRoute(),router=useRouter(),app=useApp()
const status=ref(route.query.status==='understood'?'understood':'learning'),items=ref<Topic[]>([]),total=ref(0),loading=ref(false),error=ref(''),busy=ref(new Set<string>())
let version=0,active=true
async function load(more=false){
 const request=++version,filter=status.value,offset=more?items.value.length:0
 loading.value=true;error.value=''
 if(!more){items.value=[];total.value=0}
 try{
  const res=await api<{items:Topic[];total:number}>(`/learning?status=${filter}&limit=20&offset=${offset}`)
  if(request!==version)return
  items.value=more?[...items.value,...res.items]:res.items;total.value=res.total
 }catch(e){if(request===version)error.value=e instanceof Error?e.message:'学习列表读取失败'}
 finally{if(request===version)loading.value=false}
}
async function update(topic:Topic,action:string){
 if(busy.value.has(topic.id))return
 busy.value.add(topic.id)
 try{
  await post(`/topics/${topic.id}/feedback`,{action,idempotency_key:key()})
  if(active){app.notify('学习状态已更新；这是你的主动标记。');await load()}
 }catch(e){if(active)app.notify(e instanceof Error?e.message:'状态未能保存')}
 finally{busy.value.delete(topic.id)}
}
watch(status,()=>{void router.replace({query:{...route.query,tab:'learning',status:status.value}});void load()})
onMounted(()=>void load());onBeforeUnmount(()=>{active=false;++version})
</script>
<template><section class="learning-list" aria-label="我的学习列表"><div class="learning-toolbar"><label for="learning-filter">学习状态</label><select id="learning-filter" v-model="status"><option value="learning">正在学习</option><option value="understood">自述已理解</option></select><span v-if="!loading&&!error">共 {{total}} 个主题</span></div><p class="privacy-note">按主题标题排序。学习状态来自主动标记，与收藏独立；自述已理解不代表经过测验。</p><Notice :loading="loading&&!items.length" :error="error" @retry="load()"/><div v-if="items.length" class="bookmark-list"><article v-for="topic in items" :key="topic.id" class="bookmark-item learning-item"><div><span class="discipline-label" :style="{'--discipline':topic.primary_discipline.color}"><i/>{{topic.primary_discipline.name}}</span><RouterLink :to="`/topics/${topic.id}`"><h3>{{topic.title}}<ArrowUpRight :size="16"/></h3></RouterLink><p>{{topic.summary||topic.original_summary}}</p><small v-if="topic.quality_features?.summary_label" class="summary-origin">{{topic.quality_features.summary_label}}</small><span class="visited-label">{{topic.state.learning==='learning'?'正在学习':'自述已理解'}}<span v-if="topic.state.bookmarked"> · 已收藏</span></span></div><label class="learning-action">更新学习状态<select :value="topic.state.learning" :disabled="busy.has(topic.id)||loading" :aria-label="`更新 ${topic.title} 的学习状态`" @change="update(topic,($event.target as HTMLSelectElement).value)"><option value="learning">正在学习</option><option value="understood">自述已理解</option><option value="none">移出学习列表</option></select><span v-if="busy.has(topic.id)" role="status">正在保存…</span></label></article></div><Notice v-else-if="!loading&&!error" :empty="status==='learning'?'还没有正在学习的主题。在详情页标记“正在学习”，就能从这里继续。':'还没有自述已理解的主题。可以在详情页主动标记。'"/><button v-if="items.length<total&&!error" class="button outline" :disabled="loading" @click="load(true)">{{loading?'正在加载…':'加载更多学习主题'}}</button></section></template>
