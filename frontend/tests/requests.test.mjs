// Runs real SFC setup/lifecycle/watch logic without a browser. DOM/layout is covered by e2e.
import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
const require=createRequire(import.meta.url)
const Vue=require('vue'),{parse,compileScript}=require('@vue/compiler-sfc'),ts=require('typescript')
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
const tick=async()=>{for(let i=0;i<12;i++)await Promise.resolve();await Vue.nextTick()}
const state=()=>({bookmarked:false,familiarity:'unknown',learning:'none',explored:true,skipped_until:null})
const topic=id=>({id,title:id,state:state(),sources:[]})
const batch=mode=>({id:mode,mode,items:[],constraints:{},batch_number:1})
const renderer=Vue.createRenderer({createComment:()=>({}),createText:()=>({}),createElement:()=>({}),insert(){},remove(){},setText(){},setElementText(){},patchProp(){},parentNode(){return null},nextSibling(){return null}})

function mount(name,handle,query={},props={}){
 const calls=[],route=Vue.reactive({params:{id:'A'},query}),notices=[]
 const app=Vue.reactive({profile:{depth:'beginner',intensity:.65,ai:{configured:true}},notify:text=>notices.push(text),update:async()=>{}})
 const api=async(path,options={})=>{
  const request={path,method:options.method||'GET',body:options.body?JSON.parse(options.body):undefined};calls.push(request)
  const handled=handle?.(request)
  if(handled!==undefined)return handled
  if(path.includes('/related')||path.startsWith('/ai/chat?'))return {items:[]}
  if(path.startsWith('/topics/'))return topic(path.split('/')[2])
  if(path.startsWith('/discover/today'))return batch(new URLSearchParams(path.split('?')[1]).get('mode'))
  if(path==='/stats')return {timeline:[]}
  return {}
 }
 const modules={vue:Vue,'vue-router':{useRoute:()=>route,useRouter:()=>({replace:async({query})=>route.query=query}),onBeforeRouteLeave:()=>{}},'../api':{api,post:(path,body)=>api(path,{method:'POST',body:JSON.stringify(body)}),key:()=>crypto.randomUUID()},'../stores/app':{useApp:()=>app},'../utils/exploration':{savedMode:()=> 'unknown',saveMode:()=>{},exploration:{scroll:0,pendingRefresh:Vue.reactive(new Map())}}}
 const source=readFileSync(new URL(`../src/${name}`,import.meta.url),'utf8')
 const script=compileScript(parse(source).descriptor,{id:'request-test'})
 const code=ts.transpileModule(script.content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
 const module={exports:{}}
 new Function('require','module','exports',code)(id=>modules[id]||new Proxy({},{get:()=>()=>null}),module,module.exports)
 const component=module.exports.default;component.render=()=>null
 const mounted=renderer.createApp(component,props);mounted.config.warnHandler=()=>{}
 const vm=mounted.mount({})
 return {s:vm.$.setupState,route,calls,notices,unmount:()=>mounted.unmount()}
}

test('A → B → A uses navigation generations, not just topic ids',async()=>{
 const a1=deferred(),b=deferred();let count=0
 const h=mount('views/Topic.vue',r=>r.path==='/topics/A'?(++count===1?a1.promise:topic('current A')):r.path==='/topics/B'?b.promise:undefined)
 h.route.params.id='B';h.route.params.id='A';await tick();assert.equal(h.s.topic.title,'current A')
 a1.resolve(topic('stale A'));b.resolve(topic('stale B'));await tick();assert.equal(h.s.topic.title,'current A');assert.equal(h.s.loading,false);h.unmount()
})

test('old detail errors and finally cannot change new navigation loading',async()=>{
 const a=deferred(),b=deferred();const h=mount('views/Topic.vue',r=>r.path==='/topics/A'?a.promise:r.path==='/topics/B'?b.promise:undefined)
 h.route.params.id='B';a.reject(new Error('old error'));await tick();assert.equal(h.s.error,'');assert.equal(h.s.loading,true)
 b.resolve(topic('B'));await tick();assert.equal(h.s.topic.id,'B');h.unmount()
})

for(const action of ['feedback','bookmark'])test(`${action} returning from A cannot mutate B`,async()=>{
 const result=deferred();const h=mount('views/Topic.vue',r=>r.method==='POST'?result.promise:undefined)
 await tick();const request=action==='feedback'?h.s.feedback('unfamiliar'):h.s.bookmark()
 h.route.params.id='B';await tick();result.resolve({state:{...state(),bookmarked:true,familiarity:'unfamiliar'}});await request
 assert.equal(h.s.topic.id,'B');assert.equal(h.s.topic.state.bookmarked,false);assert.equal(h.s.topic.state.familiarity,'unknown');assert.equal(h.s.busy,false);h.unmount()
})

test('independent A relationships and history cannot replace B data',async()=>{
 const rel=deferred(),history=deferred();const h=mount('views/Topic.vue',r=>r.path==='/topics/A/related'?rel.promise:r.path==='/ai/chat?topic_id=A'?history.promise:undefined)
 await tick();assert.equal(h.s.loading,false);assert.equal(h.s.relatedLoading,true)
 h.route.params.id='B';await tick();rel.resolve({items:[{topic:topic('stale')}]});history.resolve({items:[{role:'assistant',content:'stale'}]});await tick()
 assert.deepEqual(h.s.related,[]);assert.deepEqual(h.s.chat,[]);h.unmount()
})

test('new depth explanation wins; leaving invalidates pending AI and chat',async()=>{
 const old=deferred(),chat=deferred();const h=mount('views/Topic.vue',r=>r.path==='/ai/explain'?(r.body.depth==='beginner'?old.promise:{content:{overview:'deep'},sources:[]}):r.path==='/ai/chat'?chat.promise:undefined)
 await tick();const oldRequest=h.s.explain();h.s.depth='deep';await h.s.explain();old.resolve({content:{overview:'stale'},sources:[]});await oldRequest;assert.equal(h.s.explanation.content.overview,'deep')
 h.s.message='question';const chatRequest=h.s.send();h.route.params.id='B';await tick();chat.resolve({status:'ready',answer:'stale',sources:[],source_ids:[]});await chatRequest
 assert.equal(h.s.explanation,null);assert.deepEqual(h.s.chat,[]);assert.equal(h.s.message,'');h.unmount()
})

test('late history snapshot does not overwrite a new question and answer',async()=>{
 const history=deferred();const h=mount('views/Topic.vue',r=>r.path.startsWith('/ai/chat?')?history.promise:r.path==='/ai/chat'?{status:'ready',answer:'new answer',source_ids:[],sources:[]}:undefined)
 await tick();h.s.message='new question';await h.s.send();history.resolve({items:[]});await tick()
 assert.deepEqual(h.s.chat.map(m=>m.content),['new question','new answer']);h.unmount()
})

test('late mode response cannot replace current batch',async()=>{
 globalThis.window={scrollTo(){},scrollY:0}
 const bridge=deferred();const h=mount('views/Discover.vue',r=>r.path.endsWith('mode=bridge')?bridge.promise:undefined)
 await tick();h.s.mode='bridge';h.s.mode='broad';await tick();bridge.resolve(batch('bridge'));await tick();assert.equal(h.s.batch.mode,'broad');h.unmount()
})

test('failed refresh retry reuses key and successful next refresh uses a new key',async()=>{
 globalThis.window={scrollTo(){},scrollY:0}
 let requests=0;const h=mount('views/Discover.vue',r=>r.path==='/discover/refresh'?(++requests===1?Promise.reject(new Error('lost response')):batch(r.body.mode)):undefined)
 await tick();await h.s.refresh();await h.s.refresh();await h.s.refresh()
 const keys=h.calls.filter(r=>r.path==='/discover/refresh').map(r=>r.body.idempotency_key)
 assert.equal(keys[0],keys[1]);assert.notEqual(keys[1],keys[2]);h.unmount()
})

test('impression retry remains tied to original batch after mode change',async()=>{
 globalThis.window={scrollTo(){},scrollY:0}
 let requests=0;const h=mount('views/Discover.vue',r=>r.path==='/discover/impressions'?(++requests===1?Promise.reject(new Error('temporary')):{recorded:1}):undefined)
 await tick();h.s.impression('A','original');const request=h.s.flush();h.s.mode='broad';await request;await tick()
 const sent=h.calls.filter(r=>r.path==='/discover/impressions')
 assert.equal(sent.length,2);assert.deepEqual(sent[0].body,sent[1].body);assert.equal(sent[1].body.batch_id,'original');h.unmount()
})

test('learning filter responses are isolated and status mutation reloads current filter',async()=>{
 const old=deferred();let learningRequests=0
 const h=mount('components/LearningList.vue',r=>r.path.startsWith('/learning')?(r.path.includes('status=learning')&&++learningRequests===1?old.promise:{items:[{...topic('understood'),state:{...state(),learning:'understood'}}],total:1}):r.method==='POST'?{state:state()}:undefined)
 h.s.status='understood';await tick();old.resolve({items:[topic('stale learning')],total:99});await tick()
 assert.equal(h.s.total,1);assert.equal(h.s.items[0].id,'understood')
 await h.s.update(h.s.items[0],'none');assert.equal(h.calls.at(-1).path,'/learning?status=understood&limit=20&offset=0');h.unmount()
})

test('learning pagination uses server offset and appends only the requested page',async()=>{
 const h=mount('components/LearningList.vue',r=>r.path.startsWith('/learning')?(r.path.includes('offset=0')?{items:[topic('one'),topic('two')],total:3}:{items:[topic('three')],total:3}):undefined)
 await tick();await h.s.load(true);assert.deepEqual(h.s.items.map(t=>t.id),['one','two','three']);assert.match(h.calls.at(-1).path,/offset=2$/);h.unmount()
})

test('skip is visible from server expiry, can be undone, and expired state is inactive',async()=>{
 const item=Vue.reactive({topic:{...topic('A'),state:{...state(),skipped_until:'2000-01-01T00:00:00Z'}}})
 const h=mount('components/TopicCard.vue',r=>r.method==='POST'?{state:{...state(),skipped_until:r.body.action==='skip'?new Date(Date.now()+50000).toISOString():null}}:undefined,{}, {item,index:0,batchId:'original'})
 assert.equal(h.s.skipped,false);await h.s.mark('skip');await tick();assert.equal(h.s.skipped,true)
 await h.s.mark('unskip');await tick();assert.equal(h.s.skipped,false);assert.equal(item.topic.state.skipped_until,null);h.unmount()
})

test('map uses requested topic as root and displays explicit fallback when missing',async()=>{
 globalThis.window={matchMedia:()=>({matches:true})};globalThis.document={documentElement:{}}
 globalThis.MutationObserver=class{observe(){}disconnect(){}}
 const data={nodes:[{id:'topic:A',name:'A',type:'topic'}],edges:[],truncated:false}
 const h=mount('views/Map.vue',r=>r.path.startsWith('/map?')?(r.path.includes('root=topic%3Amissing')?{...data,nodes:[]}:data):undefined,{root:'topic:A'})
 await tick();assert.equal(h.s.selected.id,'topic:A');assert.match(h.calls[0].path,/root=topic%3AA/)
 h.route.query.root='topic:missing';await tick();assert.match(h.s.rootNotice,/未找到指定主题/);assert.equal(h.s.data.nodes.length,1);h.unmount()
})
