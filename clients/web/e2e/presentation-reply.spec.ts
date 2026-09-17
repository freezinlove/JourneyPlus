import { test, expect } from '@playwright/test';

for (const mode of ['history', 'live', 'empty', 'reduced'] as const) {
  const live = mode !== 'history';
  test(`${mode} presentation reveals blocks in reading order`, async ({ page }) => {
    let delivered = !live;
    if (mode === 'reduced') await page.emulateMedia({ reducedMotion: 'reduce' });
    const answer = mode === 'empty' ? '' : '**匹配说明**\n\n- 免费路径\n- 付费路径\n\n' + '保留完整的申请条件。'.repeat(35);
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
        : path.includes('/artifacts/') ? { payload: { answer, blocks: [{ type: 'route_graph', title: '可匹配路径', payload: { objects: [{ ref: 'route:test', data: { step_refs: ['step:test'], steps: { 'step:test': { ref: 'step:test', from: '起点 Gold', to: '目标 Platinum', cost: { is_free: true } } } } }] } }], next_steps: [] } }
        : { id: 'workspace', revision: 1, messages: messages(), runs: [{ run_id: 'run', status: delivered ? 'COMPLETED' : 'RUNNING', last_seq: 0 }] };
      return route.fulfill({ json: data });
    });
    await page.goto('/login');
    await expect(page.locator('article')).toHaveCount(1);
    const graph = page.getByRole('heading', { name: '可匹配路径' });
    if (mode === 'live') {
      await expect(page.locator('article strong')).toHaveText('匹配说明');
      expect((await page.locator('article').innerText()).length).toBeLessThan(answer.length);
      await expect(graph).toHaveCount(0);
      await expect(page.getByRole('button', { name: '查看申请经验' })).toHaveCount(0);
    }
    if (answer) {
      await expect(page.locator('article li')).toHaveCount(2);
      await expect(page.locator('article p').last()).toHaveText('保留完整的申请条件。'.repeat(35), { timeout: mode === 'live' ? 10000 : 2000 });
    }
    await expect(graph).toBeVisible({ timeout: 2000 });
    await expect(page.getByRole('button', { name: '查看申请经验' })).toBeVisible();
    await expect(page.locator('article')).toHaveCount(1);
    if (mode === 'reduced') {
      expect(await graph.evaluate(el => getComputedStyle(el.parentElement!.parentElement!).animationName)).toBe('none');
    }
    // Reloaded history must appear immediately rather than replay the live effect.
    await page.reload();
    await expect(graph).toBeVisible({ timeout: 2000 });
    if (answer) await expect(page.locator('article p').last()).toHaveText('保留完整的申请条件。'.repeat(35), { timeout: 2000 });
  });
}
