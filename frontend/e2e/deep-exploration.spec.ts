import {test,expect} from '@playwright/test'

async function start(page:import('@playwright/test').Page){
 await page.goto('/')
 await page.getByRole('button',{name:'跳过，直接探索'}).click()
 await expect(page.locator('.topic-card')).toHaveCount(5)
}

for(const width of [1440,390])test(`${width}px 主动随机破壁与历史独立选项`,async({page})=>{
 await page.setViewportSize({width,height:1000});let draws=0
 page.on('request',r=>{if(r.url().endsWith('/api/discover/surprise'))draws++})
 await start(page);expect(draws).toBe(0)
 const region=page.getByRole('region',{name:'随机破壁'})
 await region.getByLabel('探索强度').selectOption('far')
 await region.getByLabel('不按个人历史探索').check()
 await region.getByRole('button',{name:'随机破壁',exact:true}).click()
 await expect(region.locator('.surprise-result')).toBeVisible()
 await expect(region.locator('.surprise-result')).toContainText('不使用个人历史')
 expect(draws).toBe(1)
 await expect(region.getByRole('link',{name:/原始来源/})).toHaveAttribute('href',/^https:\/\//)
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
})

test('有来源的多步路径主动保存、继续与重新打开',async({page})=>{
 await start(page);await page.goto('/topics/graph-theory')
 const paths=page.getByRole('region',{name:'从这个知识继续探索'})
 await expect(paths).toContainText('社会资本')
 await expect(paths).toContainText('公共物品')
 await paths.getByRole('button',{name:'保存这条路径'}).click()
 await expect(paths.getByRole('link',{name:'查看已保存路径'})).toBeVisible()
 await paths.getByRole('link',{name:'继续探索：社会网络'}).click()
 await expect(page.locator('.topic-header h1')).toContainText('社会网络')
 await expect(paths.getByRole('link',{name:'返回上一节点'})).toBeVisible()
 await expect.poll(async()=>{const result=await page.request.get('/api/paths').then(r=>r.json());return result.items[0]?.position}).toBe(1)
 await page.goto('/journey?tab=paths')
 await page.getByRole('link',{name:'重新打开路径'}).click()
 await expect(page.locator('.topic-header h1')).toContainText('社会网络')
})

test('无 Key 认知挑战、独立自评、刷新保留与自愿回访',async({page})=>{
 await start(page);await page.goto('/topics/graph-theory')
 const section=page.getByRole('region',{name:'认知挑战',exact:true})
 await section.getByRole('button',{name:'开始认知挑战'}).click()
 const answer='节点表示站点，边表示站间直达连接，边的含义取决于建模问题。'
 await section.getByLabel('用自己的话回答').fill(answer)
 await section.getByRole('button',{name:'保存回答并对照'}).click()
 await expect(section.locator('.saved-attempt')).toContainText(answer)
 await section.getByLabel('对照后，你现在的感觉').selectOption('partial')
 await expect(section.getByLabel('对照后，你现在的感觉')).toHaveValue('partial')
 await page.reload()
 await expect(section.locator('.saved-attempt')).toContainText(answer)
 await expect(page.getByLabel('现在的学习状态')).toHaveValue('none')
 await page.getByRole('button',{name:'希望一周后回访'}).click()
 await page.goto('/journey?tab=revisits')
 await expect(page.getByRole('region',{name:'自愿回访'})).toContainText('图论')
 await page.getByRole('button',{name:'取消回访',exact:true}).click()
 await expect(page.getByRole('region',{name:'自愿回访'})).toContainText('暂无回访意愿')
})
