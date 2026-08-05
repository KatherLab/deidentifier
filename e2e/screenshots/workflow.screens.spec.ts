import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Documentation-screenshot harness: walks the product path with the synthetic
 * fixtures and rewrites every image under docs/assets/screenshots/.
 *
 * Run with `npm run screenshots` after any UI change that affects a documented
 * screen. Never point this at a real installation — the images end up in a
 * public docs site.
 *
 * Everything after the core path is wrapped in `capture()`, which logs and
 * continues on failure: one drifted selector should cost one image, not the
 * whole run.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FIXTURES = path.resolve(HERE, '../../backend/tests/files')
const SHOTS = path.resolve(HERE, '../../docs/assets/screenshots')

const DISCHARGE_LETTER = `SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION

Entlassungsbrief

Patient: Max Mustermann, geb. 01.02.1980
Anschrift: Musterstraße 12, 01307 Dresden
Pat.-Nr.: PAT-123456
Fallnummer: 2024-004711

Sehr geehrte Kollegin, sehr geehrter Kollege,

wir berichten über den o. g. Patienten, der sich vom 10.03.2024 bis zum
15.03.2024 in unserer stationären Behandlung befand. Die Aufnahme erfolgte
bei akuter Cholezystitis. Die laparoskopische Cholezystektomie am 11.03.2024
verlief komplikationslos.

Rückfragen an: Tel.: 0351 458-0, E-Mail: chirurgie@beispiel-klinikum.de

Mit freundlichen Grüßen
Erika Musterfrau`

/** Contains an identifier no detector in the harness knows — on purpose. */
const LEAKY_NOTE = `SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION

Kurzbefund

Patient: Hans Beispielhuber
Aufnahme: 04.06.2024

Befund unauffällig, Wiedervorstellung nach Bedarf.`

async function shoot(target: Page | Locator, name: string): Promise<void> {
  await target.screenshot({ path: path.join(SHOTS, `${name}.png`) })
  console.log(`[screenshots] ${name}.png`)
}

/** Run an optional capture; a failure costs this image only. */
async function capture(name: string, fn: () => Promise<void>): Promise<void> {
  try {
    await fn()
  } catch (error) {
    console.warn(`[screenshots] SKIPPED ${name}: ${(error as Error).message.split('\n')[0]}`)
  }
}

async function runPastedDocument(page: Page): Promise<void> {
  await page.getByLabel('Text einfügen').fill(DISCHARGE_LETTER)
  await page.getByRole('button', { name: 'Anonymisieren' }).click()
  await expect(page.getByRole('button', { name: 'Exportieren' })).toBeVisible({ timeout: 60_000 })
}

test('captures the documentation screenshots', async ({ page }) => {
  test.slow()

  // --- Input screen --------------------------------------------------------
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await shoot(page, 'input-empty')

  await capture('input-advanced', async () => {
    await page.getByLabel('Text einfügen').fill(DISCHARGE_LETTER)
    await page.getByRole('button', { name: 'Erweiterte Einstellungen' }).click()
    await expect(page.locator('#advanced-settings')).toBeVisible()
    await shoot(page, 'input-advanced')
    await page.getByRole('button', { name: 'Erweiterte Einstellungen' }).click()
  })

  await capture('settings-expert-mode', async () => {
    // `exact`: Playwright matches accessible names as substrings by default,
    // which would also hit "Erweiterte Einstellungen".
    await page.getByRole('button', { name: 'Einstellungen', exact: true }).click()
    await expect(page.getByRole('dialog', { name: 'Einstellungen' })).toBeVisible()
    await shoot(page, 'settings-expert-mode')
    await page.keyboard.press('Escape')
  })

  // --- Result screen (pasted text) ----------------------------------------
  await page.reload()
  await runPastedDocument(page)
  await shoot(page, 'result-overview')

  await capture('result-entity-selected', async () => {
    await page.locator('[data-entity-index]', { hasText: 'Max Mustermann' }).first().click()
    await expect(page.getByLabel('Details zur ausgewählten Entität')).toBeVisible()
    await shoot(page, 'result-entity-selected')
    const review = page
      .locator('section', { has: page.getByRole('heading', { name: 'Quellprüfung' }) })
      .last()
    await shoot(review, 'result-review-panel')
  })

  await capture('result-export-menu', async () => {
    await page.getByRole('button', { name: 'Exportieren' }).click()
    await expect(page.getByRole('menu', { name: 'Exportieren' })).toBeVisible()
    await shoot(page, 'result-export-menu')
    await page.keyboard.press('Escape')
  })

  // A deliberately leaky document: the fake model does not know this name and
  // no rule matches it, so the leakage validation flags the labelled field and
  // the result lands in "Prüfbedarf" — which is what the warnings docs show.
  await capture('result-warnings', async () => {
    await page.reload()
    await page.getByLabel('Text einfügen').fill(LEAKY_NOTE)
    await page.getByRole('button', { name: 'Anonymisieren' }).click()
    await expect(page.getByRole('button', { name: 'Exportieren' })).toBeVisible({ timeout: 60_000 })
    await shoot(page, 'result-review-required')

    const toggle = page.getByRole('button', { name: /Hinweise & Warnungen/ })
    // The list starts expanded whenever the validation did not pass.
    if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
    const warnings = page.locator('section', { has: toggle }).last()
    await warnings.scrollIntoViewIfNeeded()
    await shoot(warnings, 'result-warnings')
  })

  // --- Result screen (PDF upload) -----------------------------------------
  await page.reload()
  await page.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, '9874562_text.pdf'))
  await shoot(page, 'input-file-selected')
  await page.getByRole('button', { name: 'Anonymisieren' }).click()
  await expect(page.getByRole('button', { name: 'Exportieren' })).toBeVisible({ timeout: 60_000 })

  await capture('result-pdf', async () => {
    await expect(page.locator('iframe[title="Geschwärztes PDF (Vorschau)"]')).toBeVisible({
      timeout: 60_000,
    })
    // Chromium's embedded PDF viewer paints late inside an iframe; without a
    // generous wait the panel screenshots blank.
    await page.waitForTimeout(6000)
    await shoot(page, 'result-pdf')
  })

  await capture('result-pdf-area-editor', async () => {
    await page.getByRole('button', { name: /Bereiche schwärzen/ }).click()
    await page.waitForTimeout(1500)
    await shoot(page, 'result-pdf-area-editor')
    await page.getByRole('button', { name: /Bereiche schwärzen/ }).click()
  })

  // --- Batch run (two documents) ------------------------------------------
  await capture('batch-documents', async () => {
    await page.reload()
    await page
      .locator('input[type="file"]')
      .setInputFiles([
        path.join(FIXTURES, '9874562_text.pdf'),
        path.join(FIXTURES, 'synthetic_discharge.txt'),
      ])
    await page.getByRole('button', { name: /Dokumente anonymisieren/ }).click()
    await expect(page.getByRole('button', { name: 'Exportieren' })).toBeVisible({ timeout: 90_000 })
    await shoot(page, 'batch-documents')
  })
})
