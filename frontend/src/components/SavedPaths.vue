<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from 'vue'
import {api} from '../api'
import type {ExplorationPath} from '../types'
const items=ref<ExplorationPath[]>([]),total=ref(0),loading=ref(false),error=ref(''),busy=ref('')
let active=true
async function load(more=false){
 loading.value=true;error.value=''
 try{const result=await api<{items:ExplorationPath[];total:number}>(`/paths?limit=20&offset=${more?items.value.length:0}`);if(active){items.value=more?[...items.value,...result.items]:result.items;total.value=result.total}}
 catch(e){if(active)error.value=e instanceof Error?e.message:'路径读取失败。'}finally{if(active)loading.value=false}
}
async function remove(id:string){
 if(busy.value)return;busy.value=id;error.value=''
 try{await api(`/paths/${id}`,{method:'DELETE'});if(active)await load()}
 catch(e){if(active)error.value=e instanceof Error?e.message:'路径未删除。'}finally{if(active)busy.value=''}
}
onMounted(()=>void load());onBeforeUnmount(()=>{active=false})
</script>
<template><section class="saved-paths" aria-label="已保存路径"><p class="privacy-note">只有你主动保存的路径出现在这里。连续点击不会自动变成学习路径。</p><p v-if="error" role="alert">{{error}} <button class="text-button" @click="load()">重试</button></p><p v-if="loading" role="status">正在读取路径…</p><article v-for="p in items" :key="p.id" class="saved-path-card"><h3>{{p.title}}</h3><p>{{p.hops.length}} 步联系 · 当前在第 {{(p.position||0)+1}} 个概念</p><p v-if="p.evidence_changed" class="muted">关系材料已变化，请重新核对来源。</p><RouterLink :to="{path:`/topics/${p.topic_ids[p.position||0]}`,query:{path:p.id}}" class="button outline small">重新打开路径</RouterLink><button class="text-button" @click="remove(p.id!)" :disabled="!!busy">删除保存</button></article><p v-if="!loading&&!items.length&&!error" class="muted">还没有主动保存的路径。可在主题详情的“从这个知识继续探索”中保存。</p><button v-if="items.length<total" class="button outline" :disabled="loading" @click="load(true)">加载更多路径</button></section></template>
<style scoped>.saved-path-card{padding:20px 0;border-bottom:1px solid var(--border);line-height:1.8}.saved-path-card h3{font-size:21px}.saved-path-card .text-button{margin-left:20px}</style>
