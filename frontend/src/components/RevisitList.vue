<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from 'vue'
import {api,post,key} from '../api'
import type {Topic} from '../types'
const props=withDefaults(defineProps<{dueOnly?:boolean}>(),{dueOnly:false}),items=ref<Topic[]>([]),total=ref(0),error=ref(''),busy=ref(''),loading=ref(false)
let active=true
async function load(more=false){
 loading.value=true;error.value=''
 try{const result=await api<{items:Topic[];total:number}>(`/revisits?due_only=${props.dueOnly}&limit=20&offset=${more?items.value.length:0}`);if(active){items.value=more?[...items.value,...result.items]:result.items;total.value=result.total}}
 catch(e){if(active)error.value=e instanceof Error?e.message:'回访读取失败。'}finally{if(active)loading.value=false}
}
async function cancel(t:Topic){
 if(busy.value)return;busy.value=t.id
 try{await post(`/topics/${t.id}/feedback`,{action:'cancel_revisit',idempotency_key:key()});if(active)await load()}
 catch(e){if(active)error.value=e instanceof Error?e.message:'回访设置未更新。'}finally{if(active)busy.value=''}
}
onMounted(()=>void load());onBeforeUnmount(()=>{active=false})
</script>
<template><section v-if="items.length||!dueOnly||error" class="revisit-list" aria-label="自愿回访"><h2>{{dueOnly?'你希望回访的知识':'我的回访意愿'}}</h2><p class="muted">这是你主动留下的回访入口，随时可以取消。</p><p v-if="error" role="alert">{{error}} <button class="text-button" @click="load()">重试</button></p><article v-for="t in items" :key="t.id"><div><RouterLink :to="`/topics/${t.id}`"><h3>{{t.title}} ↗</h3></RouterLink><small>希望 {{new Date(t.state.revisit_at!).toLocaleDateString('zh-CN')}} 回访 · {{t.primary_discipline.name}}</small></div><button class="text-button" :disabled="!!busy" @click="cancel(t)">取消回访</button></article><p v-if="!items.length&&!error&&!loading" class="muted">暂无回访意愿。可以在主题详情选择“一周后回访”。</p><button v-if="items.length<total" class="button outline small" :disabled="loading" @click="load(true)">加载更多回访</button></section></template>
<style scoped>.revisit-list{padding:24px 0;line-height:1.8}.revisit-list h2{font-size:22px}.revisit-list article{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 0;border-bottom:1px solid var(--border)}.revisit-list h3{font-size:19px}</style>
