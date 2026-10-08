import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Private access code").fill("incorrect");
  await page.getByRole("button", { name: "Unlock Blink" }).click();
  await expect(page.getByLabel("Private access code")).toBeVisible();
  const code = readFileSync(
    resolve(process.env.BLINK_TEST_DATA_DIR!, "access-code"),
    "utf8",
  );
  await page.getByLabel("Private access code").fill(code);
  await page.getByRole("button", { name: "Unlock Blink" }).click();
  await expect(page.getByText("Local workspace connected")).toBeVisible();
});

test("onboarding, resume, chat memory, review, confirmed submission, and history", async ({
  page,
  request,
}) => {
  await expect(page.getByText("Local workspace connected")).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: /Apply for internships in the blink of an eye/,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Applicant profile", exact: true })
    .click();
  await page.getByLabel("Legal first name", { exact: true }).fill("Synthetic");
  await page.getByLabel("Legal last name", { exact: true }).fill("Applicant");
  await page
    .getByLabel("Email address", { exact: true })
    .fill(`ui-${Date.now()}@example.test`);
  await page.getByLabel("Phone number", { exact: true }).fill("5550101234");
  await page.getByLabel("City", { exact: true }).fill("Bloomington");
  await page.getByRole("button", { name: "Education", exact: true }).click();
  await page
    .getByRole("button", { name: "Add education", exact: true })
    .click();
  await page
    .getByLabel("College or university", { exact: true })
    .fill("Synthetic University");
  await page
    .getByLabel("Degree type", { exact: true })
    .fill("Bachelor of Science");
  await page.getByLabel("Major", { exact: true }).fill("Computer Science");
  await page
    .getByLabel("Expected graduation date", { exact: true })
    .fill("2027-05");
  await page.getByRole("button", { name: "Preferences", exact: true }).click();
  await page
    .getByLabel("Legally authorized to work in the United States?", {
      exact: true,
    })
    .selectOption("Yes");
  await page
    .getByLabel(
      "Need visa sponsorship now or in the future in the United States?",
      { exact: true },
    )
    .selectOption("No");
  await page.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(
    page.getByText("Profile saved securely on this device."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  await page.getByLabel("Upload document", { exact: true }).setInputFiles({
    name: "synthetic-resume.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\nSynthetic resume\n%%EOF"),
  });
  await expect(page.getByText("Default resume", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await page
    .getByLabel("Where are we applying?", { exact: true })
    .fill(`http://127.0.0.1:8001/mock/jobs/ui-${Date.now()}`);
  await page
    .getByRole("button", { name: "Start application", exact: true })
    .click();
  await expect(
    page.getByText(
      "Are you available full-time from May through August 2027?",
      { exact: true },
    ),
  ).toBeVisible({ timeout: 30000 });
  await page.getByLabel("Message to assistant", { exact: true }).fill("Yes");
  await page
    .getByLabel("Remember this exact answer for future applications", {
      exact: true,
    })
    .check();
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page
      .getByText("What would you like to learn during this internship?", {
        exact: true,
      })
      .first(),
  ).toBeVisible();
  await page
    .getByLabel("Message to assistant", { exact: true })
    .fill("I want to practice writing maintainable code with a team.");
  await page
    .getByLabel("Remember this exact answer for future applications", {
      exact: true,
    })
    .check();
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Approve & submit", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Ready for your final review")).toBeVisible();
  // Keep the final action on the local fixture only.
  await page
    .getByRole("button", { name: "Approve & submit", exact: true })
    .click();
  await expect(
    page.getByText(/Application received. Confirmation NS-/).last(),
  ).toBeVisible({ timeout: 15000 });
  await page
    .getByRole("button", { name: "Application history", exact: true })
    .click();
  await expect(page.getByRole("table")).toContainText(/submitted/i);
  await page
    .getByRole("button", { name: "Applicant profile", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Saved answers", exact: true })
    .click();
  await expect(
    page.getByText("What would you like to learn during this internship?", {
      exact: true,
    }),
  ).toBeVisible();
  // The webpage cannot read applicant information directly without the local bearer token.
  expect(
    (await request.get("http://127.0.0.1:8000/api/profile")).status(),
  ).toBe(401);
});

test("responsive dashboard and profile remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Start application", exact: true }),
  ).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
  await page.screenshot({
    path: "test-results/blink-mobile.png",
    fullPage: true,
  });
});
