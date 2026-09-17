import { test, expect } from '@playwright/test';

test('new workspace initialization stays in welcome state without stop button', async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route(/\/(auth|v3)\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === 'POST' && path === '/v3/agent/workspaces') await pending;
    await route.fulfill({ json: path === '/auth/me' ? { id: 'test', username: 'test' }
      : { id: 'workspace', revision: 1, messages: [], runs: [] } });
  });
  try {
    await page.goto('/');
    await expect(page.getByLabel('消息')).toBeEnabled();
    await page.getByRole('button', { name: '新对话', exact: true }).click();
    await page.getByRole('button', { name: '开始新对话', exact: true }).click();
    await expect(page.getByLabel('消息')).toBeDisabled();
    await expect(page.getByRole('heading', { name: '想用你的会籍，开启怎样的下一程？' })).toBeVisible();
    await expect(page.getByRole('button', { name: '停止回答' })).toHaveCount(0);
    release();
    await expect(page.getByLabel('消息')).toBeEnabled();
    await expect(page.getByRole('heading', { name: '想用你的会籍，开启怎样的下一程？' })).toBeVisible();
  } finally { release(); }
});
