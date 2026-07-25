// Model-layer roadmap item 3 (2026-07-22): the model picker stays actionable for the
// session's whole life (supersedes the 2026-07-04 lock that hid it after the first turn).
// A mid-session switch drops a persisted info marker into the transcript, and later
// messages ride the new model.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("mid-session model switch shows the marker and later turns use the new model", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByText("Draft the launch note").first().click();
  const box = page.getByPlaceholder(/Ask the coworker/);
  await box.fill("hello there");
  await box.press("Enter");
  await expect(page.getByText("Echo: hello there", { exact: false }).first()).toBeVisible();

  // The picker is still in the composer after the first turn (the old lock hid it).
  // The trigger is a neutral "Model" chip (2026-07-25) — the name lives in the menu only.
  const picker = page.getByTestId("model-picker");
  await expect(picker).toBeVisible();
  await expect(picker).toContainText("Model");
  await expect(picker).not.toContainText("Claude Opus 4.8");
  await picker.click();
  // The open menu still names every model, ✓ on the active one.
  await expect(page.locator(".dd-item.sel").filter({ hasText: "Claude Opus 4.8" })).toBeVisible();
  await page.locator(".dd-item").filter({ hasText: "GPT-5.5" }).click();

  // The switch marker lands in the transcript…
  await expect(page.getByText(/Model switched to gpt-5.5/).first()).toBeVisible();

  // …and the next message carries the new model (the fixture echoes it back).
  await box.fill("after the switch");
  await box.press("Enter");
  await expect(
    page.getByText("Echo: after the switch [model=gpt-5.5]", { exact: false }).first(),
  ).toBeVisible();
});
