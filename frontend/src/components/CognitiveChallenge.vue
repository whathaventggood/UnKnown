<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue'
import {api,post,key,safeUrl} from '../api'
type Challenge={id:string;prompt:string;reference_answer:string|null;key_points:string[];sources:{id:string;url:string;title:string}[];limits:string}
type Attempt={id:string;answer:string;self_assessment:string|null;feedback:{message:string;reference:Challenge;lexical_cues:{terms:string[];mentioned:boolean}[]};created_at:string}
const props=defineProps<{topicId:string}>()
const challenge=ref<Challenge|null>(null),attempt=ref<Attempt|null>(null),answer=ref(''),open=ref(false),busy=ref(false),loading=ref(false),error=ref(''),notice=ref(''),assessmentBusy=ref(false)
let version=0,pending='',lastTopic=''
async function load(){
 const v=++version;challenge.value=null;attempt.value=null;if(lastTopic!==props.topicId)answer.value='';lastTopic=props.topicId;open.value=false;error.value='';notice.value='';pending='';loading.value=true
 try{
  const [result,history]=await Promise.all([api<{status:string;message:string;challenge:Challenge|null}>(`/topics/${props.topicId}/challenge`),api<{items:Attempt[]}>(`/topics/${props.topicId}/challenge/attempts`)])
  if(v!==version)return
  challenge.value=result.challenge;notice.value=result.message;attempt.value=history.items[0]||null
 }catch(e){if(v===version)error.value=e instanceof Error?e.message:'挑战读取失败。'}
 finally{if(v===version)loading.value=false}
}
async function submit(){
 if(!challenge.value||!answer.value.trim()||busy.value)return
 const v=version;busy.value=true;error.value='';pending||=key()
 try{
  const saved=await post<Attempt>(`/topics/${props.topicId}/challenge`,{challenge_id:challenge.value.id,answer:answer.value,idempotency_key:pending})
  if(v===version){attempt.value=saved;pending=''}
 }catch(e){if(v===version)error.value=e instanceof Error?e.message:'作答未保存。'}
 finally{if(v===version)busy.value=false}
}
async function reveal(){
 const v=version;busy.value=true;error.value=''
 try{const result=await api<{challenge:Challenge}>(`/topics/${props.topicId}/challenge?reveal=true`);if(v===version)challenge.value=result.challenge}
 catch(e){if(v===version)error.value=e instanceof Error?e.message:'参考读取失败。'}
 finally{if(v===version)busy.value=false}
}
async function assess(value:string){
 if(!attempt.value||assessmentBusy.value)return
 const v=version;assessmentBusy.value=true
 try{const result=await api<Attempt>(`/challenge-attempts/${attempt.value.id}`,{method:'PATCH',body:JSON.stringify({self_assessment:value})});if(v===version)attempt.value=result}
 catch(e){if(v===version)error.value=e instanceof Error?e.message:'自评未保存。'}
 finally{if(v===version)assessmentBusy.value=false}
}
watch(answer,()=>{pending=''})
watch(()=>props.topicId,load,{immediate:true})
onBeforeUnmount(()=>{++version})
</script>
<template><section class="content-section cognitive-challenge" aria-label="认知挑战">
 <div class="section-heading"><h2>认知挑战 · 检查自己的理解</h2></div><p class="muted">自愿作答。参考对照不等于掌握程度，无惩罚或分数。</p>
 <p v-if="loading" role="status">正在读取挑战与作答记录…</p><p v-if="error" role="alert" class="inline-error">{{error}} <button class="text-button" @click="load">重新读取挑战</button></p>
 <button v-if="challenge&&!open" class="button outline" @click="open=true">开始认知挑战</button><p v-else-if="!challenge&&!loading" class="muted">{{notice}}</p>
 <form v-if="challenge&&open" @submit.prevent="submit"><h3>{{challenge.prompt}}</h3><label for="challenge-answer">用自己的话回答</label><textarea id="challenge-answer" v-model="answer" rows="5" maxlength="2000" :disabled="busy"/><div class="challenge-actions"><button class="button primary small" :disabled="busy||!answer.trim()">{{busy?'正在保存…':'保存回答并对照'}}</button><button type="button" class="text-button" :disabled="busy" @click="reveal">先查看参考答案</button></div><div v-if="challenge.reference_answer" class="reference-answer"><h4>参考 · 现有中文整理材料</h4><p>{{challenge.reference_answer}}</p><p>{{challenge.limits}}</p></div></form>
 <article v-if="attempt" class="saved-attempt" aria-live="polite"><span class="tiny-label">已保存的作答 · {{new Date(attempt.created_at).toLocaleDateString('zh-CN')}}</span><h3>你的回答</h3><p class="own-answer">{{attempt.answer}}</p><p>{{attempt.feedback.message}}</p><h4>参考要点 · 入门整理，未经专家审阅</h4><ul><li v-for="point in attempt.feedback.reference.key_points" :key="point">{{point}}</li></ul><p v-if="attempt.feedback.lexical_cues.length" class="muted">字词线索（不判断推理）：{{attempt.feedback.lexical_cues.map(c=>(c.mentioned?'出现':'未识别')+'「'+c.terms.join('/')+'」').join('；')}}</p><div class="reference-sources"><a v-for="source in attempt.feedback.reference.sources" :key="source.id" :href="safeUrl(source.url)" target="_blank" rel="noopener noreferrer" class="text-button">核对来源：{{source.title}} ↗</a></div><label>对照后，你现在的感觉<select :value="attempt.self_assessment||''" :disabled="assessmentBusy" @change="assess(($event.target as HTMLSelectElement).value)"><option value="" disabled>可选自评</option><option value="not_yet">还没抓住关键</option><option value="partial">理解了一部分</option><option value="got_it">自述抓住关键</option></select></label><p class="privacy-note">自评独立保存，不会自动把学习状态改成“已理解”。</p></article>
</section></template>
<style scoped>
.cognitive-challenge form{display:grid;gap:12px;margin-top:20px}.cognitive-challenge h3{line-height:1.7}.cognitive-challenge textarea{width:100%;box-sizing:border-box;border:1px solid var(--border);border-radius:8px;padding:12px;background:transparent;color:inherit;font:inherit;resize:vertical}.challenge-actions{display:flex;gap:15px;flex-wrap:wrap}.reference-answer,.saved-attempt{margin-top:20px;padding:18px;border:1px solid var(--border);border-radius:10px;line-height:1.9;overflow-wrap:anywhere}.own-answer{white-space:pre-wrap}.saved-attempt h4{margin-top:20px}.saved-attempt select{display:block;max-width:100%;margin:8px 0}.reference-sources{display:grid;margin-bottom:20px}
</style>
