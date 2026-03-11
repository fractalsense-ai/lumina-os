import { test, expect } from '@playwright/test'

test('app shell loads', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: /I Agree/i })).toBeVisible()
})
