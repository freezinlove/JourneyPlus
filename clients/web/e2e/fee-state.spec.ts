import { test, expect } from '@playwright/test';

for (const paid of [null, true, false]) {
  test(`graph preserves fee state ${paid}`, async ({ page }) => {
    await page.route(/\/(auth|v[123])\//, async route => {
      const path = new URL(route.request().url()).pathname;
      const data = path === '/auth/me' ? { id: 'test', username: 'test' }
        : path.includes('/membership-catalog') ? { nodes: [] }
        : path.includes('/artifacts/') ? { payload: { blocks: [{
            type: 'route_graph', payload: { objects: [{ ref: 'route:test', data: {
              paid, step_refs: ['step:test'], steps: { 'step:test': {
                ref: 'step:test', from: 'Lufthansa Senator', to: 'Flying Blue Gold',
                paid, matching_policy: 'simple-matching-v2-fee-state',
              }},
            }}] },
          }], next_steps: [] } }
        : { id: 'workspace', revision: 1, messages: [{
            id: 'reply', role: 'assistant', content: [],
            attachments: { presentation_refs: ['artifact:graph'] },
          }], runs: [] };
      await route.fulfill({ json: data });
    });
    await page.goto('/login');
    await expect(page.getByText(paid === null ? '费用待核实' : paid ? '付费申请' : '免费申请', { exact: true })).toBeVisible();
    if (paid !== false) await expect(page.getByText('免费申请', { exact: true })).toHaveCount(0);
  });
}
