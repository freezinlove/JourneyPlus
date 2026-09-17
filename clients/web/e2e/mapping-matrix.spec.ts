import { test, expect } from '@playwright/test';
test('conversation mapping uses one source row and target columns', async ({page}) => {
 await page.route(/\/(auth|v[123])\//, async route => {
 const path=new URL(route.request().url()).pathname;
 const data=path==='/auth/me'?{id:'test',username:'test'}:path.includes('/artifacts/')?{payload:{blocks:[{type:'mapping_table',payload:{objects:[{ref:'activity:test',data:{options:[{mappings:[
 {from_program:'Lufthansa',from_tiers:['Senator'],to_tier:'Gold',conditions:'特定条件',evidence:['internal-reference']},
 {from_program:'Lufthansa',from_tiers:['HON Circle'],to_tier:'Platinum'}]}]}}]}}],next_steps:[]}}:
 {id:'workspace',revision:1,messages:[{id:'reply',role:'assistant',content:[],attachments:{presentation_refs:['artifact:matrix']}}],runs:[]};
 await route.fulfill({json:data});
 });
 await page.goto('/login');
 await expect(page.locator('tbody tr')).toHaveCount(1);
 await expect(page.locator('thead')).toContainText('匹配至 Gold');
 await expect(page.locator('thead')).toContainText('匹配至 Platinum');
 await expect(page.locator('tbody')).toContainText('Senator');
 await expect(page.locator('tbody')).toContainText('HON Circle');
 await expect(page.locator('table')).not.toContainText('internal-reference');
 await page.getByText('条件说明',{exact:true}).click();
 await expect(page.locator('details')).toContainText('特定条件');
});
