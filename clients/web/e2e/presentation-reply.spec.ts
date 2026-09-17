import { test, expect } from '@playwright/test';

for (const live of [false, true]) {
  test(`${live ? 'new' : 'historical'} presentation hides tool-only replies and renders Markdown`, async ({ page }) => {
    let delivered = !live;
    const answer = '**匹配说明**\n\n- 免费路径\n- 付费路径\n\n' + '保留完整的申请条件。'.repeat(35);
    const messages = () => Array.from({ length: 11 }, (_, i) => ({
      id: `call-${i}`, role: 'assistant', content: [{ type: 'tool_call' }],
      ...(delivered && i === 10 ? { attachments: { presentation_refs: ['artifact:graph'] } } : {}),
    }));
    await page.route(/\/(auth|v[123])\//, async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/events')) {
        await new Promise(resolve => setTimeout(resolve, 150));
        delivered = true;
        return route.fulfill({ contentType: 'text/event-stream', body:
          'data: {"type":"presentation.created","payload":{"presentation_ref":"artifact:graph"}}\n\n' +
          'data: {"type":"completed","payload":{}}\n\n' });
      }
      const data = path === '/auth/me' ? { id: 'test', username: 'test' }
        : path.includes('/artifacts/') ? { payload: { answer, blocks: [], next_steps: [] } }
        : { id: 'workspace', revision: 1, messages: messages(), runs: [{ run_id: 'run', status: delivered ? 'COMPLETED' : 'RUNNING', last_seq: 0 }] };
      return route.fulfill({ json: data });
    });
    await page.goto('/login');
    await expect(page.locator('article')).toHaveCount(1);
    await expect(page.locator('article strong')).toHaveText('匹配说明');
    if (live) expect((await page.locator('article').innerText()).length).toBeLessThan(answer.length);
    await expect(page.locator('article li')).toHaveCount(2);
    await expect(page.locator('article p').last()).toHaveText('保留完整的申请条件。'.repeat(35), { timeout: 10000 });
    await expect(page.locator('article')).toHaveCount(1);
    // Reloaded history must appear immediately rather than replay the live effect.
    await page.reload();
    await expect(page.locator('article p').last()).toHaveText('保留完整的申请条件。'.repeat(35), { timeout: 2000 });
  });
}
