<script setup lang="ts">
import {ref,nextTick,onBeforeUnmount} from 'vue'
import {post,key,safeUrl} from '../api'
import type {Recommendation} from '../types'
const strength=ref('cross'),historyFree=ref(false),busy=ref(false),error=ref('')
const result=ref<{id:string;item:Recommendation|null;constraints:{message:string}}|null>(null),card=ref<HTMLElement|null>(null)
let pending='',observer:IntersectionObserver|null=null,active=true
async function discover(){
 if(busy.value)return
 busy.value=true;error.value='';pending||=key()
 try{
  const response=await post<{id:string;item:Recommendation|null;constraints:{message:string}}>('/discover/surprise',{strength:strength.value,history_free:historyFree.value,idempotency_key:pending})
  if(!active)return
  result.value=response;pending='';await nextTick();observer?.disconnect()
  if(card.value&&response.item){
   const report=()=>post('/discover/impressions',{batch_id:response.id,topic_ids:[response.item!.topic.id]}).catch(()=>{})
   observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){observer?.disconnect();void report()}},{threshold:.4})
   observer.observe(card.value)
  }
 }catch(e){if(active)error.value=e instanceof Error?e.message:'探索暂时不可用。'}
 finally{if(active)busy.value=false}
}
function cancel(){pending='';error.value=''}
onBeforeUnmount(()=>{active=false;observer?.disconnect()})
</script>
<template>
 <section class="surprise-discover" aria-label="随机破壁">
  <div><span class="tiny-label">ONE UNEXPECTED DOOR</span><h2>给我一个我从没想到过的知识</h2><p class="muted">主动打开一个入口。陌生程度是估计，选择权在你。</p></div>
  <div class="surprise-controls">
   <label>探索强度<select v-model="strength" :disabled="busy||!!pending"><option value="gentle">温和探索</option><option value="cross">跨界探索</option><option value="far">完全陌生</option></select></label>
   <label class="history-free"><input type="checkbox" v-model="historyFree" :disabled="busy||!!pending">不按个人历史探索</label>
   <button class="button primary" @click="discover" :disabled="busy">{{busy?'正在选择…':pending?'重试本次探索':'随机破壁'}}</button>
  </div>
  <p v-if="error" role="alert" class="inline-error">{{error}} <button class="text-button" @click="cancel">取消重试，重新选择</button></p>
  <article v-if="result?.item" ref="card" class="surprise-result" aria-live="polite">
   <span class="tiny-label">{{result.item.topic.primary_discipline.name}} / {{result.item.topic.subfield}}</span>
   <h3><RouterLink :to="`/topics/${result.item.topic.id}`">{{result.item.topic.title}} ↗</RouterLink></h3>
   <p>{{result.item.topic.content_intro?.one_sentence||result.item.topic.summary}}</p><p class="muted">{{result.item.reason}}</p>
   <a v-if="result.item.topic.sources[0]" :href="safeUrl(result.item.topic.sources[0].url)" target="_blank" rel="noopener noreferrer" class="text-button">原始来源 · {{result.item.topic.sources[0].platform}}</a>
   <RouterLink class="button outline small" :to="`/topics/${result.item.topic.id}`">开始理解</RouterLink>
  </article>
  <p v-else-if="result" role="status">{{result.constraints.message}}</p>
 </section>
</template>
<style scoped>
.surprise-discover{border-block:1px solid var(--border);padding:28px 0;margin:24px 0 36px}.surprise-discover h2{font-size:22px;margin:8px 0}.surprise-controls{display:flex;gap:18px;align-items:end;flex-wrap:wrap;margin-top:18px}.surprise-controls label{display:grid;gap:7px;font-size:13px}.surprise-controls select{min-width:150px}.surprise-controls .history-free{display:flex;align-items:center;align-self:center}.surprise-result{margin-top:22px;padding:20px;border:1px solid var(--border);border-radius:12px;overflow-wrap:anywhere}.surprise-result h3{font-size:24px;margin:12px 0}.surprise-result p{line-height:1.8}.surprise-result .button{margin-left:18px}@media(max-width:600px){.surprise-controls{align-items:stretch;gap:12px}.surprise-controls label:first-child{width:100%}.surprise-controls button{width:100%}.surprise-result .button{margin:12px 0 0;display:flex}}
</style>
