import { test, expect } from "@playwright/test";
test("login, stream, refresh, news, holdings, theme and logout against FastAPI", async ({
  page,
}) => {
  test.setTimeout(60000);
  await page.goto("/");
  await page.getByLabel("账号").fill("client-test");
  await page.getByLabel("密码").fill("Client-test-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "新对话", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  await page.getByRole("button", { name: "开始新对话", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "从已有会籍出发" }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "消息", exact: true })
    .fill("读取我的会籍");
  await expect(
    page.getByRole("button", { name: "发送", exact: true }),
  ).toBeEnabled();
  await page.getByRole("textbox", { name: "消息", exact: true }).press("Enter");
  await expect(
    page.getByText("这是隔离验收环境的流式回复，未调用真实模型。"),
  ).toBeVisible({ timeout: 20000 });
  await page.reload();
  await expect(page.getByText("读取我的会籍", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "会籍新闻", exact: true }).click();
  await expect(page.getByRole("heading", { name: "会籍新闻" })).toBeVisible();
  await page
    .locator("main button")
    .filter({ has: page.locator("h2") })
    .first()
    .click();
  await expect(page.getByRole("heading", { name: "完整映射表" })).toBeVisible();
  await page.getByRole("button", { name: "返回", exact: true }).click();
  await page.getByRole("button", { name: "我的会籍", exact: true }).click();
  await page.getByRole("button", { name: "＋ 添加会籍" }).click();
  await page.getByLabel("搜索项目").fill("Marriott");
  await expect(page.getByLabel("会籍等级").locator("option")).not.toHaveCount(
    1,
  );
  await page
    .getByLabel("会籍等级")
    .selectOption({ label: "Marriott Bonvoy · Platinum Elite" });
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByText("Marriott Bonvoy", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "深色", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "登录", exact: true }),
  ).toBeVisible();
});
