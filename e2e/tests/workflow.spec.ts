import { expect, test } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * End-to-end smoke test for the whole product path:
 *
 *   paste / upload → detection (rules + fake LLM) → review → override → export
 *
 * Everything runs against the real backend with the real detector stack; only
 * the LLM endpoint is faked (e2e/support/fake-llm.mjs) so results are
 * deterministic. See playwright.config.ts for the server wiring.
 */

const FIXTURES = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../backend/tests/files',
)

const DISCHARGE_LETTER = `SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION

Entlassungsbrief

Patient: Max Mustermann, geb. 01.02.1980
Anschrift: Musterstraße 12, 01307 Dresden
Pat.-Nr.: PAT-123456

wir berichten über den o. g. Patienten, der sich vom 10.03.2024 bis zum
15.03.2024 in unserer stationären Behandlung befand.

Rückfragen an: Tel.: 0351 458-0, E-Mail: chirurgie@beispiel-klinikum.de

Mit freundlichen Grüßen
Erika Musterfrau`

/** The result view is up once the status headline is rendered. */
async function waitForResult(page: import('@playwright/test').Page) {
  await expect(page.getByRole('button', { name: 'Exportieren' })).toBeVisible({ timeout: 60_000 })
}

test.describe('anonymization workflow', () => {
  test('anonymizes pasted text and lets the user override an entity', async ({ page }) => {
    await page.goto('/')

    await page.getByLabel('Text einfügen').fill(DISCHARGE_LETTER)
    await page.getByRole('button', { name: 'Anonymisieren' }).click()
    await waitForResult(page)

    // The anonymized output must contain no source identifier and must carry
    // the default policy's replacements.
    const output = page.getByRole('heading', { name: 'Anonymisierter Text' })
    await expect(output).toBeVisible()
    // `.last()`: the panel card is the innermost section carrying the heading.
    const outputPanel = page.locator('section', { has: output }).last()
    await expect(outputPanel).toContainText('[PERSON_1]')
    await expect(outputPanel).not.toContainText('Max Mustermann')
    await expect(outputPanel).not.toContainText('PAT-123456')
    await expect(outputPanel).not.toContainText('chirurgie@beispiel-klinikum.de')
    // Clinical dates are preserved by default so timelines stay usable.
    await expect(outputPanel).toContainText('10.03.2024')

    // The source review keeps the ORIGINAL text with the entities marked.
    const marks = page.locator('[data-entity-index]')
    expect(await marks.count()).toBeGreaterThan(0)

    // Select the patient name and preserve it — the deterministic
    // transformation re-runs and the name reappears in the output.
    await page.locator('[data-entity-index]', { hasText: 'Max Mustermann' }).first().click()
    const details = page.getByLabel('Details zur ausgewählten Entität')
    await expect(details).toBeVisible()
    await details.getByRole('button', { name: 'Beibehalten' }).click()

    await expect(outputPanel).toContainText('Max Mustermann', { timeout: 30_000 })
    await expect(details.getByRole('button', { name: 'Zurücksetzen' })).toBeVisible()

    // …and undoing the override redacts it again.
    await details.getByRole('button', { name: 'Zurücksetzen' }).click()
    await expect(outputPanel).not.toContainText('Max Mustermann', { timeout: 30_000 })
  })

  test('offers the text export for a pasted document', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('Text einfügen').fill(DISCHARGE_LETTER)
    await page.getByRole('button', { name: 'Anonymisieren' }).click()
    await waitForResult(page)

    await page.getByRole('button', { name: 'Exportieren' }).click()
    const menu = page.getByRole('menu', { name: 'Exportieren' })
    await expect(menu).toBeVisible()
    // A pasted document has no PDF source, so only the text exports appear.
    await expect(menu.getByRole('menuitem', { name: 'Als Textdatei (.txt)' })).toBeVisible()
    await expect(menu.getByRole('menuitem', { name: 'Als PDF' })).toHaveCount(0)

    const download = page.waitForEvent('download')
    await menu.getByRole('menuitem', { name: 'Als Textdatei (.txt)' }).click()
    expect((await download).suggestedFilename()).toContain('.txt')
  })

  test('anonymizes an uploaded PDF and exports a redacted PDF', async ({ page }) => {
    await page.goto('/')

    await page
      .locator('input[type="file"]')
      .setInputFiles(path.join(FIXTURES, '9874562_text.pdf'))
    await page.getByRole('button', { name: 'Anonymisieren' }).click()
    await waitForResult(page)

    // A PDF source opens the redacted-PDF panel instead of the plain text one.
    await expect(page.getByRole('heading', { name: 'Geschwärztes PDF' })).toBeVisible()
    await expect(page.locator('iframe[title="Geschwärztes PDF (Vorschau)"]')).toBeVisible({
      timeout: 60_000,
    })

    await page.getByRole('button', { name: 'Exportieren' }).click()
    const download = page.waitForEvent('download')
    await page
      .getByRole('menu', { name: 'Exportieren' })
      .getByRole('menuitem', { name: 'Als PDF' })
      .click()
    expect((await download).suggestedFilename()).toContain('.pdf')
  })

  test('rejects an unsupported file type before uploading', async ({ page }) => {
    await page.goto('/')

    await page.locator('input[type="file"]').setInputFiles({
      name: 'befund.rtf',
      mimeType: 'application/rtf',
      buffer: Buffer.from('{\\rtf1}'),
    })

    await expect(page.getByText(/Dateityp nicht unterstützt/)).toBeVisible()
  })

  test('switches the UI language and remembers the choice', async ({ page }) => {
    await page.goto('/')

    // The runner is pinned to de-DE (playwright.config.ts), so the app starts
    // in German and an explicit switch takes it to English.
    await expect(page.getByRole('button', { name: 'Anonymisieren' })).toBeVisible()

    await page.getByRole('button', { name: 'Sprache wählen' }).click()
    await page.getByRole('menuitemradio', { name: 'English' }).click()

    await expect(page.getByRole('button', { name: 'Anonymize' })).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')

    // The choice is persisted (localStorage) and survives a reload.
    await page.reload()
    await expect(page.getByRole('button', { name: 'Anonymize' })).toBeVisible()

    // …and a full run stays in the chosen language, warnings included.
    await page.getByLabel('Paste text').fill(DISCHARGE_LETTER)
    await page.getByRole('button', { name: 'Anonymize' }).click()
    await expect(page.getByRole('button', { name: 'Export' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('heading', { name: 'Anonymized text' })).toBeVisible()
  })

  test('writes the placeholders in the chosen output language', async ({ page }) => {
    await page.goto('/')

    // The output language is an advanced setting, captured at submit.
    await page.getByRole('button', { name: 'Erweiterte Einstellungen' }).click()
    await page
      .getByLabel('Sprache der Platzhalter')
      .selectOption({ label: 'Français' })
    await page.getByLabel('Text einfügen').fill(DISCHARGE_LETTER)
    await page.getByRole('button', { name: 'Anonymisieren' }).click()
    await waitForResult(page)

    const output = page.getByRole('heading', { name: 'Anonymisierter Text' })
    const outputPanel = page.locator('section', { has: output }).last()
    await expect(outputPanel).toContainText('[PERSONNE_1]')
    await expect(outputPanel).toContainText('[DATE_DE_NAISSANCE]')
    await expect(outputPanel).not.toContainText('[PERSON_1]')

    // Switching the INTERFACE language afterwards translates the chrome but
    // must not rewrite the placeholders of the finished document.
    await page.getByRole('button', { name: 'Sprache wählen' }).click()
    await page.getByRole('menuitemradio', { name: 'English' }).click()
    await expect(page.getByRole('button', { name: 'Export' })).toBeVisible()
    const translatedPanel = page
      .locator('section', { has: page.getByRole('heading', { name: 'Anonymized text' }) })
      .last()
    await expect(translatedPanel).toContainText('[PERSONNE_1]')

    // The exported file belongs to the document, so its name follows the
    // document's language too — "anonymise.txt", not the interface's
    // "anonymized.txt".
    await page.getByRole('button', { name: 'Export' }).click()
    const download = page.waitForEvent('download')
    await page
      .getByRole('menu', { name: 'Export' })
      .getByRole('menuitem', { name: 'As text file (.txt)' })
      .click()
    expect((await download).suggestedFilename()).toBe('anonymise.txt')
  })

  test('reports the configured backends in the status header', async ({ page }) => {
    await page.goto('/')

    // The fake LLM runs on 127.0.0.1, which counts as local — so the app must
    // NOT warn about content leaving the installation.
    await expect(page.getByRole('button', { name: /Externer Endpunkt/ })).toHaveCount(0)
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Anonymisierer')
  })
})
