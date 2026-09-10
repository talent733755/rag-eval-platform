import { expect, test } from "@playwright/test";

const project = {
  id: "11111111-1111-4111-8111-111111111111",
  organization_id: "22222222-2222-4222-8222-222222222222",
  name: "Smoke 项目",
  slug: "smoke-project",
  description: null,
  archived_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

test("admin can open the project shell", async ({ page }) => {
  await page.route("**/api/projects", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: [project],
      status: 200,
    });
  });

  await page.goto("/");

  const navigation = page.getByRole("navigation", { name: "主导航" });
  await expect(navigation).toContainText("工作台");
  await expect(navigation).toContainText("数据资产");
  await expect(page.getByRole("combobox", { name: "当前项目" })).toHaveValue(project.id);

  await page.getByRole("link", { name: "项目与成员" }).click();

  await expect(page).toHaveURL(/\/settings\/members\?project=/);
  await expect(page.getByRole("heading", { name: "项目与成员" })).toBeVisible();
});
