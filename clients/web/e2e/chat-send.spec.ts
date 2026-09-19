import {test, expect} from '@playwright/test';

test('send clears immediately, shows bubble, and restores draft on rejected request', async ({page}) => {
  let release!:()=>void;
  const gate=new Promise<void>(r=>release=r);
  await page.route(/\/(auth|v3)\//,async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.endsWith('/runs')) {
      await gate;
      await route.fulfill({status:503,json:{detail:'测试请求失败'}});
    } else await route.fulfill({json:path==='/auth/me'?{id:'test',username:'test'}:
      {id:'workspace',revision:1,messages:[],runs:[]}});
  });
  try {
    await page.goto('/');
    await expect(page.getByLabel('消息')).toBeEnabled();
    await page.getByLabel('消息').fill('我的会籍能匹配到什么');
    await page.getByRole('button',{name:'发送',exact:true}).click();
    await expect(page.getByLabel('消息')).toHaveValue('');
    await expect(page.locator('article').getByText('我的会籍能匹配到什么',{exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'停止回答'})).toBeVisible();
    release();
    await expect(page.getByLabel('消息')).toHaveValue('我的会籍能匹配到什么');
    await expect(page.locator('article').getByText('我的会籍能匹配到什么',{exact:true})).toHaveCount(0);
  } finally {release();}
});

test('finished tool narration disappears on reload without hiding final response',async({page})=>{
  await page.route(/\/(auth|v3)\//,route=>route.fulfill({json:new URL(route.request().url()).pathname==='/auth/me'?{id:'test'}:
    {id:'workspace',revision:1,runs:[],messages:[
      {id:'u',role:'user',content:[{type:'text',text:'查询'}]},
      {id:'p',role:'assistant',content:[{type:'text',text:'我先查资料'},{type:'tool_call'}]},
      {id:'f',role:'assistant',content:[{type:'text',text:'最终结论'}]},
    ]}}));
  await page.goto('/');
  await expect(page.getByText('最终结论',{exact:true})).toBeVisible();
  await expect(page.getByText('我先查资料',{exact:true})).toHaveCount(0);
});
