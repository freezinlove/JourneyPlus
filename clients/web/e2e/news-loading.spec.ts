import { test, expect } from '@playwright/test';

test('news refresh does not initialize hidden chat; visiting chat retains its draft', async ({ page }) => {
  const requests: string[] = [];
  await page.route(/\/(auth|v[123])\//, async route => {
    const path = new URL(route.request().url()).pathname;
    requests.push(path);
    const data = path === '/auth/me' ? { id: 'test', username: 'test' }
      : path === '/v2/activities' ? { activities: [{ ref: 'a', name: '测试新闻', updated_at: '2026-09-17', card: { summary: '已发布摘要' } }], has_more: false }
      : { id: 'workspace', revision: 1, messages: [], runs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto('/news');
  await expect(page.getByRole('heading', { name: '测试新闻' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '测试新闻' })).toBeVisible();
  expect(requests.filter(p => p.startsWith('/v3/') || p.includes('membership-catalog'))).toEqual([]);
  await page.getByRole('button', { name: '对话', exact: true }).click();
  const input = page.locator('textarea');
  await expect(input).toBeVisible();
  await input.fill('保留未发送的草稿');
  await page.getByRole('button', { name: '会籍新闻', exact: true }).click();
  await expect(page.getByRole('heading', { name: '测试新闻' })).toBeVisible();
  await page.getByRole('button', { name: '对话', exact: true }).click();
  await expect(input).toHaveValue('保留未发送的草稿');
});

test('brief content renders while relationship is still pending', async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route(/\/(auth|v[123])\//, async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith('/relationship')) {
      await pending;
      return route.fulfill({ json: { status: 'DIRECT', text: '关系计算完成', path: ['source', 'target'], path_labels: ['Miles & More · Senator', 'Mabuhay Miles · Premier Elite'] } });
    }
    if (path.endsWith('/brief')) expect(url.searchParams.get('include_relationship')).toBe('false');
    const data = path === '/auth/me' ? { id: 'test', username: 'test' }
      : path.endsWith('/brief') ? { program: 'Test', brief: { title: '简报正文', summary: '不等待关系计算' }, facts: {} }
      : { ref: 'a', version_ref: 'v1', facts: {}, card: {} };
    await route.fulfill({ json: data });
  });
  try {
    await page.goto('/news?activity_id=a');
    await expect(page.getByRole('heading', { name: '简报正文' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '会籍匹配表' })).toBeVisible();
    await expect(page.getByText('正在查看与你的会籍的关系…')).toBeVisible();
    release();
    await expect(page.getByLabel('我的会籍匹配路径')).toBeVisible();
    await expect(page.getByText('Senator', { exact: true })).toBeVisible();
    await expect(page.getByText('Premier Elite', { exact: true })).toBeVisible();
    await expect(page.getByText('关系计算完成')).toHaveCount(0);
  } finally { release(); }
});
