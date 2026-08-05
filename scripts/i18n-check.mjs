#!/usr/bin/env node
// i18n catalog parity + message-compilation check (ported from llmaixweb).
//
// 1. Parity: every non-source locale under frontend/locales/ has exactly the
//    same set of (deeply-flattened) message keys as the source-of-truth
//    `de.json` — no missing keys, no extras. German is the source here because
//    the UI text of this app is authored in German (see frontend/i18n).
// 2. Placeholders: a translation must use the same `{named}` placeholders as
//    the German message — a dropped `{count}` silently renders a sentence with
//    a missing number.
// 3. Compilation: every message in every catalog actually compiles under
//    vue-i18n's message syntax. This catches the silent killers — an
//    unescaped `@` (vue-i18n reads it as linked-message syntax, so
//    "a@b.com" throws "Invalid linked format"), stray `|`, unbalanced
//    braces. A message that fails to compile throws at *render* time and
//    blanks the entire component subtree, which no type check or build
//    catches. Escape literals as `{'@'}`.
//
// Run in `npm run check` / CI so translations can never silently drift out of
// sync with — or break — the German catalog.
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { baseCompile } from '@intlify/message-compiler'

const SOURCE_LOCALE = 'de'
const localesDir = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'frontend', 'locales')

/** Flatten a nested message object into [dotted key, message] pairs. */
function flattenEntries(obj, prefix = '') {
  const entries = []
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      entries.push(...flattenEntries(value, path))
    } else {
      entries.push([path, value])
    }
  }
  return entries
}

function loadCatalog(locale) {
  return JSON.parse(readFileSync(join(localesDir, `${locale}.json`), 'utf8'))
}

/** The `{named}` placeholders a message uses, as a sorted list. */
function placeholders(message) {
  return [...String(message).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
}

const localeFiles = readdirSync(localesDir).filter((f) => f.endsWith('.json'))
const sourceEntries = new Map(flattenEntries(loadCatalog(SOURCE_LOCALE)))

let failed = false
for (const file of localeFiles) {
  const locale = file.replace(/\.json$/, '')
  if (locale === SOURCE_LOCALE) continue

  const entries = new Map(flattenEntries(loadCatalog(locale)))
  const missing = [...sourceEntries.keys()].filter((k) => !entries.has(k))
  const extra = [...entries.keys()].filter((k) => !sourceEntries.has(k))
  const mismatched = []
  for (const [key, message] of entries) {
    if (!sourceEntries.has(key)) continue
    const expected = placeholders(sourceEntries.get(key)).join(',')
    const actual = placeholders(message).join(',')
    if (expected !== actual) {
      mismatched.push(`${key}: expected {${expected}}, found {${actual}}`)
    }
  }

  if (missing.length || extra.length || mismatched.length) {
    failed = true
    console.error(`\n✖ ${locale}.json is out of sync with ${SOURCE_LOCALE}.json`)
    if (missing.length) {
      console.error(`  Missing keys (${missing.length}):\n    ${missing.join('\n    ')}`)
    }
    if (extra.length) {
      console.error(`  Extra keys (${extra.length}):\n    ${extra.join('\n    ')}`)
    }
    if (mismatched.length) {
      console.error(
        `  Placeholder mismatches (${mismatched.length}):\n    ${mismatched.join('\n    ')}`,
      )
    }
  } else {
    console.log(`✓ ${locale}.json (${entries.size} keys)`)
  }
}

// --- Message compilation -------------------------------------------------
for (const file of localeFiles) {
  const locale = file.replace(/\.json$/, '')
  const broken = []
  for (const [key, message] of flattenEntries(loadCatalog(locale))) {
    if (typeof message !== 'string') continue
    try {
      baseCompile(message, {
        onError: (e) => {
          throw e
        },
      })
    } catch (err) {
      broken.push(`${key}: ${err.message?.split('\n')[0] ?? err}\n      ${JSON.stringify(message)}`)
    }
  }
  if (broken.length) {
    failed = true
    console.error(`\n✖ ${locale}.json has ${broken.length} message(s) that fail to compile:`)
    console.error(`    ${broken.join('\n    ')}`)
    console.error(`  Hint: literal '@' and '|' must be escaped, e.g. "a{'@'}b.com".`)
  }
}

if (failed) {
  console.error('\ni18n catalog check failed.')
  process.exit(1)
}
console.log('\nAll locale catalogs are in sync and compile cleanly.')
