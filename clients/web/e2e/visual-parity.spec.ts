import { test, expect, type Page } from "@playwright/test";
import { resolve } from "node:path";
const origin = {
  id: "aster",
  program_key: "aster",
  tier_key: "gold",
  program: "Aster Club",
  tier: "Gold",
};
const targetA = {
  id: "meridian",
  program_key: "meridian",
  tier_key: "platinum",
  program: "Meridian Club",
  tier: "Platinum",
};
const targetB = {
  id: "harbor",
  program_key: "harbor",
  tier_key: "gold",
  program: "Harbor Hotels",
  tier: "Gold",
};
const titles = [
  "让已有会籍，连接 Meridian Platinum。",
  "Harbor Gold：一次新的酒店会籍选择。",
  "会籍活动里，还有这些值得留意的变化。",
];
const summaries = [
  "适用来源会籍、申请条件与等级映射，在同一份简报中查看。",
  "看清匹配费用和适用范围，再决定这条路径是否适合自己。",
  "其他会籍相关资讯仍保留简报，不作为正式匹配图中的路线。",
];
const routes = [targetA, targetB].map((n, i) => {
  const step = {
    ref: `step-${i}`,
    from: "Aster Club Gold",
    to: `${n.program} ${n.tier}`,
    from_tier_id: "aster",
    to_tier_id: n.id,
    activity_ref: n.id,
    version_ref: "v1",
    paid: !!i,
  };
  return {
    ref: `route-${i}`,
    data: {
      from: step.from,
      to: step.to,
      step_refs: [step.ref],
      steps: { [step.ref]: step },
      paid: !!i,
      step_count: 1,
    },
  };
});
async function mock(page: Page) {
  await page.route(/\/(auth|v[123])\//, async (route) => {
    const u = new URL(route.request().url());
    let data: any = {};
    if (u.pathname === "/auth/me") data = { id: "parity", username: "" };
    else if (u.pathname === "/v1/status-holdings")
      data = [
        {
          id: "h1",
          program_key: "aster",
          tier_key: "gold",
          program_display_name: "Aster Club",
          tier_display_name: "Gold",
          valid_until: null,
        },
      ];
    else if (u.pathname === "/v1/membership-catalog")
      data = { nodes: [origin, targetA, targetB] };
    else if (u.pathname.endsWith("/brief"))
      data = {
        program: "Meridian Club",
        brief: {
          title: titles[0],
          summary:
            "一份清楚的申请资料：来源会籍、目标等级，以及决定前需要了解的条件。",
        },
        fee: { label: "免费" },
        brief_updated_at: "2026-09-16T00:00:00Z",
        relationship: { text: "Aster Club Gold → Meridian Club Platinum" },
        action_links: ["https://example.com/apply"],
        source_links: ["https://example.com/terms"],
        facts: {
          status_mappings: [
            {
              source_program: "Aster Club",
              source_tiers: ["Gold"],
              target_tier: "Platinum",
              availability: "CONDITIONAL",
              conditions: "仅限新会员",
              conflict: true,
              conflict_note: "申请地区存在冲突",
            },
          ],
        },
        routes: [
          {
            scope: "国际申请",
            region: "指定地区",
            prices: [
              {
                target_tier: "Platinum",
                currency: "USD",
                amount: 120,
                availability: "CONDITIONAL",
                raw_text: "升级费用，需核对地区",
              },
            ],
          },
        ],
      };
    else if (u.pathname.startsWith("/v2/activities/"))
      data = { name: "Meridian Club", facts: {} };
    else if (u.pathname === "/v2/activities")
      data = {
        activities: titles.map((name, i) => ({
          ref: `news-${i}`,
          version_ref: "v1",
          name,
          is_current: true,
          updated_at: `2026-09-${16 - i}T00:00:00Z`,
          card: { summary: summaries[i] },
        })),
        has_more: false,
      };
    else if (u.pathname.endsWith("/artifacts/p1"))
      data = {
        payload: {
          blocks: [{ type: "route_graph", payload: { objects: routes } }],
        },
      };
    else if (u.pathname.includes("/workspaces"))
      data = {
        id: "w1",
        revision: 1,
        runs: [],
        messages: [
          {
            id: "u1",
            role: "user",
            content: [
              {
                type: "text",
                text: "我有 Aster Club Gold，想看看有哪些可以匹配的会籍。",
              },
            ],
          },
          {
            id: "a1",
            role: "assistant",
            content: [
              {
                type: "text",
                text: "## 你的下一程，有两种可能。\n\n这份演示展示两条会籍路径。先看清楚你能走到哪里，再打开对应简报了解条件。",
              },
            ],
            attachments: { presentation_refs: ["artifact:p1"] },
          },
        ],
      };
    await route.fulfill({ json: data });
  });
}
async function prototype(page: Page) {
  await page.goto(
    "file://" + resolve("../../doc/design/2026-09-16/preview.html"),
  );
  // Only remove the presentation/demo frame. Product styles are unchanged.
  await page.addStyleTag({
    content:
      ".review-bar,.review-note{display:none}.stage{padding:0;max-width:none}.stage:not(.android) .app{height:100vh;min-height:0;max-height:none;border:0;border-radius:0;box-shadow:none}",
  });
}
async function styles(page: Page, ref: Page, a: string, b: string) {
  const read = (el: Element) => {
    const c = getComputedStyle(el);
    return Object.fromEntries(
      [
        "fontFamily",
        "fontSize",
        "fontWeight",
        "lineHeight",
        "color",
        "backgroundColor",
        "borderRadius",
        "borderColor",
      ].map((k) => [
        k,
        c.getPropertyValue(k.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase())),
      ]),
    );
  };
  expect(await page.locator(a).first().evaluate(read)).toEqual(
    await ref.locator(b).first().evaluate(read),
  );
}
async function compare(
  page: Page,
  reference: Page,
  actual: string,
  expected: string,
) {
  await reference.evaluate(() =>
    document.getAnimations().forEach((a) => a.finish()),
  );
  const a = await page.locator(actual).first().boundingBox();
  const b = await reference.locator(expected).first().boundingBox();
  expect(a, actual).not.toBeNull();
  expect(b, expected).not.toBeNull();
  for (const key of ["x", "y", "width", "height"] as const)
    expect(
      Math.abs(a![key] - b![key]),
      `${actual}.${key}: ${a![key]} vs ${b![key]}`,
    ).toBeLessThanOrEqual(1);
}
for (const width of [1440, 1100, 800])
  for (const theme of ["light", "dark"])
    test(`prototype geometry ${width} ${theme}`, async ({
      page,
      context,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 960 });
      const ref = await context.newPage();
      await ref.setViewportSize({ width, height: 960 });
      await prototype(ref);
      await ref.evaluate((t) => {
        document.querySelector("#app")!.setAttribute("data-theme", t);
      }, theme);
      await page.addInitScript(
        (t) => localStorage.setItem("jp-theme", t),
        theme,
      );
      await mock(page);
      await page.goto("/");
      await expect(
        page.getByRole("button", {
          name: "Meridian Club Platinum，查看申请详情",
        }),
      ).toBeVisible();
      await compare(page, ref, '[class*="brand_"]', ".brand");
      await compare(page, ref, '[class*="rail_"]', ".primary-nav");
      await compare(
        page,
        ref,
        '[class*="workspaceHeading"]',
        ".workspace-heading",
      );
      await compare(page, ref, '[class*="userMessage"]', ".user-msg");
      await compare(page, ref, '[class*="speaker_"]', ".speaker");
      await compare(page, ref, '[class*="answer_"] h2', ".response h2");
      await compare(page, ref, '[class*="composer_"]', ".composer");
      await compare(page, ref, '[class*="origin_"]', ".graph-body .origin");
      await compare(page, ref, 'button[class*="node_"]', ".route-target");
      await styles(page, ref, '[class*="userMessage"]', ".user-msg");
      await styles(page, ref, '[class*="composer_"]', ".composer");
      await styles(page, ref, 'button[class*="node_"]', ".route-target");
      await page
        .getByRole("textbox", { name: "消息", exact: true })
        .fill("自动换行测试。".repeat(40));
      await ref.locator("#message").fill("自动换行测试。".repeat(40));
      await compare(page, ref, '[class*="composer_"]', ".composer");
      await page.getByRole("textbox", { name: "消息", exact: true }).fill("");
      await ref.locator("#message").fill("");
      await page.screenshot({ path: testInfo.outputPath("chat.png") });
      await ref.screenshot({ path: testInfo.outputPath("prototype-chat.png") });
      await page.getByRole("button", { name: "会籍新闻", exact: true }).click();
      await ref.locator(".primary-nav [data-view=journal]").click();
      // Demo-only tags absent from production activity fields are removed from the fixture.
      await ref
        .locator(".row-tag")
        .evaluateAll((nodes) => nodes.forEach((n) => n.remove()));
      await expect(
        page.getByRole("heading", { name: "会籍新闻" }),
      ).toBeVisible();
      await compare(page, ref, "main h1", ".news-title");
      await compare(page, ref, '[class*="newsRow"]', ".brief-row");
      await page.screenshot({ path: testInfo.outputPath("news.png") });
      await ref.screenshot({ path: testInfo.outputPath("prototype-news.png") });
      await page
        .locator("main button")
        .filter({ has: page.locator("h2") })
        .first()
        .click();
      await ref.locator(".brief-row").first().click();
      await expect(
        page.getByRole("heading", { name: "完整映射表" }),
      ).toBeVisible();
      await compare(page, ref, "main h1", "#reader-title");
      await compare(page, ref, '[class*="lede_"]', ".reader-lede");
      await styles(page, ref, "main h1", "#reader-title");
      await expect(
        page.getByRole("button", { name: "会籍新闻", exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByText("有条件／可选", { exact: true }),
      ).toBeVisible();
      await expect(page.getByText("信息有冲突", { exact: true })).toBeVisible();
      await page.getByText("条件说明", { exact: true }).click();
      await expect(page.getByText("仅限新会员", { exact: true })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath("reader.png") });
      await page.getByRole("button", { name: "返回", exact: true }).click();
      await ref.locator("#desktop-reader-back").click();
      await page.getByRole("button", { name: "我的会籍", exact: true }).click();
      await ref.locator(".primary-nav [data-view=holdings]").click();
      await expect(
        page.getByRole("heading", { name: "我的会籍" }),
      ).toBeVisible();
      await compare(page, ref, '[class*="heading_"]', ".holdings-heading");
      await compare(page, ref, '[class*="holding_"]', ".membership-item");
      await compare(page, ref, '[class*="settings_"]', ".appearance-row");
      await compare(page, ref, '[class*="back_"]', ".desktop-reader-back");
      await page.screenshot({ path: testInfo.outputPath("holdings.png") });
      await ref.screenshot({
        path: testInfo.outputPath("prototype-holdings.png"),
      });
      await page.getByRole("button", { name: "编辑", exact: true }).click();
      await ref.locator(".membership-edit").click();
      const actualModal = await page.locator("[role=dialog]").boundingBox();
      const expectedModal = await ref.locator(".sheet").boundingBox();
      expect(actualModal!.width).toBe(expectedModal!.width);
      await page.screenshot({ path: testInfo.outputPath("editor.png") });
    });

test("narrow Web keeps prototype proportions and native scroll directions", async ({
  page,
  context,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const ref = await context.newPage();
  await ref.setViewportSize({ width: 390, height: 844 });
  await prototype(ref);
  await mock(page);
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Meridian Club Platinum，查看申请详情" }),
  ).toBeVisible();
  // Scroll position does not belong to the design: both compare at the top.
  await page
    .locator('[class*="chatScroll"]')
    .evaluate((el) => (el.scrollTop = 0));
  await compare(page, ref, '[class*="workspaceHeading"]', ".workspace-heading");
  await compare(page, ref, '[class*="userMessage"]', ".user-msg");
  await compare(page, ref, '[class*="composer_"]', ".composer");
  await compare(page, ref, '[class*="segment_"]', ".mobile-segment");
  await expect(page.locator('[class*="graphScroll"]')).toHaveCSS(
    "touch-action",
    "pan-x pan-y",
  );
  await page.screenshot({ path: testInfo.outputPath("narrow-web.png") });
});

test("node opens its pinned brief and closes the detail sheet", async ({
  page,
}) => {
  await mock(page);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Meridian Club Platinum，查看申请详情" })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "查看对应版本简报 ↗" }).click();
  await expect(page).toHaveURL(/activity_id=meridian&version_ref=v1/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "完整映射表" })).toBeVisible();
  await page.getByRole("button", { name: "返回", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "消息", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "开始新对话" })).toBeVisible();
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
