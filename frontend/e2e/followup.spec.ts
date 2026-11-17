import {test,expect,type Page} from '@playwright/test'

const a='graph-theory',b='social-network'
const gate=()=>{let release!:()=>void;const promise=new Promise<void>(resolve=>release=resolve);return {promise,release}}
async function start(page:Page,path='/'){
 await page.goto(path)
 await page.getByRole('button',{name:'跳过，直接探索'}).click()
}
async function relatedB(page:Page){await page.locator('.related-topic').getByRole('link',{name:'社会网络',exact:false}).click();await expect(page.locator('.topic-header h1')).toContainText('社会网络')}
async function settle(page:Page){await page.evaluate(()=>new Promise<void>(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r()))))}
async function enableMockAI(page:Page){await page.route('**/api/profile',async route=>{const response=await route.fetch();const body=await response.json();body.ai={configured:true,model:'controlled-ui-fixture'};await route.fulfill({response,json:body})})}
const explanation=(text:string)=>({status:'ready',message:'',cached:false,content:{overview:text,principle:'受控测试',applications:[],misconceptions:[],open_questions:[],questions:[],claims:[]},sources:[],usage:null})

test('模式、稳定批次和返回位置保留，存储不可用时正常降级',async({page})=>{
 await start(page)
 await page.getByRole('button',{name:'广域探索',exact:true}).click()
 await expect(page.locator('.topic-card')).toHaveCount(5)
 const batch=await page.request.get('/api/discover/today?mode=broad').then(r=>r.json())
 const link=page.locator('.topic-card').nth(2).getByRole('link',{name:'开始探索'})
 await link.scrollIntoViewIfNeeded();const scroll=await page.evaluate(()=>scrollY)
 await link.click();await expect(page.locator('.topic-header')).toBeVisible()
 await page.getByRole('link',{name:'回到今日探索'}).click()
 await expect(page.getByRole('button',{name:'广域探索',exact:true})).toHaveAttribute('aria-pressed','true')
 await expect(page.locator('.topic-card')).toHaveCount(5)
 await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(Math.max(0,scroll-100))
 await page.reload()
 await expect(page.getByRole('button',{name:'广域探索',exact:true})).toHaveAttribute('aria-pressed','true')
 expect((await page.request.get('/api/discover/today?mode=broad').then(r=>r.json())).id).toBe(batch.id)
 await page.addInitScript(()=>{Storage.prototype.getItem=()=>{throw new Error('storage disabled')};Storage.prototype.setItem=()=>{throw new Error('storage disabled')}})
 await page.reload();await expect(page.locator('.topic-card')).toHaveCount(5)
 await page.getByRole('button',{name:'跨领域桥梁',exact:true}).click();await expect(page.locator('.topic-card')).toHaveCount(5)
})

test('快速切换模式时旧响应不会覆盖当前模式',async({page})=>{
 await start(page);await expect(page.locator('.topic-card')).toHaveCount(5)
 const delayed=gate();let received=false
 await page.route('**/api/discover/today?mode=bridge',async route=>{const response=await route.fetch();received=true;await delayed.promise;await route.fulfill({response})})
 await page.getByRole('button',{name:'跨领域桥梁',exact:true}).click();await expect.poll(()=>received).toBe(true)
 await page.getByRole('button',{name:'广域探索',exact:true}).click();await expect(page.locator('.topic-card')).toHaveCount(5)
 const titles=await page.locator('.topic-title').allTextContents()
 const response=page.waitForResponse('**/api/discover/today?mode=bridge');delayed.release();await response;await settle(page)
 expect(await page.locator('.topic-title').allTextContents()).toEqual(titles)
 await expect(page.getByRole('button',{name:'广域探索',exact:true})).toHaveAttribute('aria-pressed','true')
})

test('换组响应丢失后重试同一幂等操作',async({page})=>{
 await start(page);await expect(page.locator('.topic-card')).toHaveCount(5)
 const before=await page.request.get('/api/discover/today').then(r=>r.json()),keys:string[]=[]
 await page.route('**/api/discover/refresh',async route=>{keys.push(route.request().postDataJSON().idempotency_key);const response=await route.fetch();if(keys.length===1)await route.abort('failed');else await route.fulfill({response})})
 await page.getByRole('button',{name:'换一组',exact:true}).click()
 await expect(page.getByRole('button',{name:'重试换组',exact:true})).toBeEnabled()
 await page.getByRole('button',{name:'重试换组',exact:true}).click();await expect(page.locator('.topic-card')).toHaveCount(5)
 expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1])
 const after=await page.request.get('/api/discover/today').then(r=>r.json());expect(after.batch_number).toBe(before.batch_number+1)
 await page.getByRole('button',{name:'换一组',exact:true}).click();await expect.poll(()=>keys.length).toBe(3);expect(keys[2]).not.toBe(keys[1])
})

test('曝光失败切换批次后仍重试原批次',async({page})=>{
 const retry=gate(),bodies:{batch_id:string;topic_ids:string[]}[]=[]
 await page.route('**/api/discover/impressions',async route=>{
  bodies.push(route.request().postDataJSON())
  if(bodies.length===1){await route.fulfill({status:503,json:{error:{message:'controlled failure'}}});return}
  if(bodies.length===2)await retry.promise
  const response=await route.fetch();await route.fulfill({response})
 })
 await start(page);await expect.poll(()=>bodies.length).toBeGreaterThanOrEqual(2)
 await page.getByRole('button',{name:'跨领域桥梁',exact:true}).click();await expect(page.locator('.topic-card')).toHaveCount(5)
 expect(bodies[0]).toEqual(bodies[1]);retry.release()
 await expect.poll(()=>bodies.length).toBeGreaterThanOrEqual(3)
 expect(bodies[2]!.batch_id).not.toBe(bodies[0]!.batch_id)
})

test('A → B → A 详情乱序不会覆盖最后一次导航',async({page})=>{
 await start(page,`/topics/${a}`);await relatedB(page)
 const oldA=gate(),oldB=gate();let callsA=0,receivedB=false
 await page.route(`**/api/topics/${a}`,async route=>{const response=await route.fetch();const body=await response.json();callsA++;if(callsA===1){body.title='过期 A';await oldA.promise}await route.fulfill({response,json:body})})
 await page.route(`**/api/topics/${b}`,async route=>{const response=await route.fetch();const body=await response.json();body.title='过期 B';receivedB=true;await oldB.promise;await route.fulfill({response,json:body})})
 await page.goBack();await expect.poll(()=>callsA).toBe(1)
 await page.goForward();await expect.poll(()=>receivedB).toBe(true)
 await page.goBack();await expect(page.locator('.topic-header h1')).toContainText('图论')
 const ra=page.waitForResponse(`**/api/topics/${a}`),rb=page.waitForResponse(`**/api/topics/${b}`);oldB.release();oldA.release();await Promise.all([ra,rb]);await settle(page)
 await expect(page.locator('.topic-header h1')).toContainText('图论');await expect(page.locator('.topic-header h1')).not.toContainText('过期')
})

for(const kind of ['feedback','bookmark'] as const)test(`${kind} 晚返回不修改新主题`,async({page})=>{
 await start(page,`/topics/${a}`);await expect(page.locator('.related-topic')).not.toHaveCount(0)
 const delayed=gate();let received=false
 const path=kind==='feedback'?`**/api/topics/${a}/feedback`:'**/api/bookmarks'
 await page.route(path,async route=>{const response=await route.fetch();received=true;await delayed.promise;await route.fulfill({response})})
 await page.getByRole('button',{name:kind==='feedback'?'完全陌生':'收藏这个主题',exact:true}).click();await expect.poll(()=>received).toBe(true)
 await relatedB(page)
 const response=page.waitForResponse(path);delayed.release();await response;await settle(page)
 await expect(page.getByRole('button',{name:'收藏这个主题',exact:true})).toBeEnabled()
 await expect(page.getByRole('button',{name:'完全陌生',exact:true})).toHaveAttribute('aria-pressed','false')
})

test('旧关联和历史讨论不覆盖新主题，独立区域可以重试',async({page})=>{
 const delayed=gate();let held=false
 await page.route(`**/api/topics/${a}/related`,async route=>{const response=await route.fetch();held=true;await delayed.promise;await route.fulfill({response})})
 await start(page,`/topics/${a}`);await expect(page.locator('.topic-header h1')).toContainText('图论');await expect.poll(()=>held).toBe(true)
 // Navigate through a link while the independent section remains pending.
 await page.getByRole('link',{name:'回到今日探索'}).click();await expect(page.locator('.topic-card')).toHaveCount(5)
 await page.locator('.topic-card').first().getByRole('link',{name:'开始探索'}).click();await expect(page.locator('.topic-header h1')).toBeVisible()
 delayed.release()
 await page.route('**/api/topics/*/related',route=>route.fulfill({status:503,json:{error:{message:'关联暂时不可用'}}}))
 await page.reload();await expect(page.locator('.topic-header h1')).toBeVisible();await expect(page.getByRole('button',{name:'重试关联'})).toBeVisible()
})

test('解释深度隔离且旧 AI 回答不进入新主题',async({page})=>{
 await enableMockAI(page);await start(page,`/topics/${a}`)
 const beginner=gate(),chatGate=gate();let explainHeld=false,chatHeld=false
 await page.route('**/api/ai/explain',async route=>{const body=route.request().postDataJSON();if(body.depth==='beginner'){explainHeld=true;await beginner.promise}await route.fulfill({json:explanation(body.depth==='beginner'?'过期入门解释':'当前深入解释')})})
 await page.route('**/api/ai/chat',async route=>{chatHeld=true;await chatGate.promise;await route.fulfill({json:{status:'ready',answer:'旧主题的回答',source_ids:[],sources:[]}})})
 await page.getByRole('button',{name:'生成解释',exact:true}).click();await expect.poll(()=>explainHeld).toBe(true)
 await page.getByRole('button',{name:'深入理解',exact:true}).click();await page.getByRole('button',{name:'生成解释',exact:true}).click();await expect(page.locator('.ai-content')).toContainText('当前深入解释')
 const r=page.waitForResponse('**/api/ai/explain');beginner.release();await r;await settle(page);await expect(page.locator('.ai-content')).not.toContainText('过期入门解释')
 await page.getByLabel('针对当前主题提问').fill('测试问题');await page.getByRole('button',{name:'发送问题'}).click();await expect.poll(()=>chatHeld).toBe(true)
 await relatedB(page)
 const c=page.waitForResponse('**/api/ai/chat');chatGate.release();await c;await settle(page)
 await expect(page.locator('.chat-history')).toHaveCount(0);await expect(page.getByLabel('针对当前主题提问')).toHaveValue('');await expect(page.locator('.ai-content')).toHaveCount(0)
})

test('历史讨论晚返回不抹掉刚发送的新消息',async({page})=>{
 await enableMockAI(page)
 const history=gate();let held=false
 await page.route('**/api/ai/chat?topic_id=*',async route=>{held=true;await history.promise;await route.fulfill({json:{items:[{role:'assistant',content:'旧历史快照'}]}})})
 await page.route('**/api/ai/chat',route=>route.fulfill({json:{status:'ready',answer:'新消息的回答',source_ids:[],sources:[]}}))
 await start(page,`/topics/${a}`);await expect.poll(()=>held).toBe(true)
 await page.getByLabel('针对当前主题提问').fill('新问题');await page.getByRole('button',{name:'发送问题'}).click();await expect(page.locator('.chat-history')).toContainText('新消息的回答')
 const r=page.waitForResponse('**/api/ai/chat?topic_id=*');history.release();await r;await settle(page)
 await expect(page.locator('.chat-history')).toContainText('新问题');await expect(page.locator('.chat-history')).toContainText('新消息的回答')
})

for(const width of [1440,390])test(`${width}px 跳过撤销、学习回访和状态更新真实 API 闭环`,async({page})=>{
 await page.setViewportSize({width,height:900});await start(page);await expect(page.locator('.topic-card')).toHaveCount(5)
 const first=page.locator('.topic-card').first();await first.getByRole('button',{name:/熟悉程度反馈/}).click();await first.getByRole('button',{name:'暂时跳过',exact:true}).click()
 await expect(first.locator('.skip-notice')).toContainText('有效至');await page.reload();await expect(page.locator('.topic-card').first().locator('.skip-notice')).toBeVisible()
 await page.locator('.topic-card').first().getByRole('button',{name:'撤销跳过'}).click();await expect(page.locator('.skip-notice')).toHaveCount(0)
 await page.locator('.topic-card').first().getByRole('link',{name:'开始探索'}).click();await expect(page.locator('.topic-header')).toBeVisible()
 const title=await page.locator('.topic-header h1').innerText()
 await page.getByLabel('现在的学习状态').selectOption('learning');await expect(page.getByLabel('现在的学习状态')).toHaveValue('learning')
 if(width===390){await page.getByRole('button',{name:'展开导航',exact:true}).click();await page.locator('.mobile-nav').getByRole('link',{name:'我的探索',exact:true}).click()}else await page.getByRole('link',{name:'我的探索',exact:true}).first().click()
 await page.getByRole('button',{name:'学习列表',exact:true}).click();await expect(page.locator('.learning-item')).toHaveCount(1);await expect(page.locator('.learning-item')).toContainText(title.split('\n')[0]!)
 await page.locator('.learning-item').getByRole('link').click();await page.getByLabel('现在的学习状态').selectOption('understood');await expect(page.getByLabel('现在的学习状态')).toHaveValue('understood')
 await page.goBack();await expect(page.locator('.learning-list')).toContainText('还没有正在学习')
 await page.getByLabel('学习状态',{exact:true}).selectOption('understood');await expect(page.locator('.learning-item')).toHaveCount(1)
 await page.locator('.learning-item select').selectOption('none');await expect(page.locator('.learning-list')).toContainText('还没有自述已理解')
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
})

test('从详情定位地图并在找不到主题时显示降级提示',async({page})=>{
 await start(page,`/topics/${a}`);await page.getByRole('link',{name:'在认知地图中探索'}).click()
 await expect(page).toHaveURL(/root=topic/);await expect(page.locator('.inspector-title')).toContainText('图论')
 await page.goto('/map?root=topic:missing');await expect(page.locator('.soft-notice')).toContainText('未找到指定主题');await expect(page.locator('.map-bottom')).toContainText(/[1-9]\d* 个节点/)
})
