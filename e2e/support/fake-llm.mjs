// Deterministic fake OpenAI-compatible server for the Playwright harnesses.
//
// The Node counterpart of backend/tests/fake_llm.py: it serves
// POST /v1/chat/completions and answers with the JSON shape the LLM detector
// expects. Instead of replaying a fixed list, it scans the submitted chunk for
// the identifiers of the synthetic fixtures in backend/tests/files and returns
// only the ones actually present — so grounding, chunking, and the re-check
// path all run against real (if predictable) model output.
//
// Three request shapes are distinguished the same way the backend builds them:
//   - vision (message content is an array)      → plain transcription text
//   - re-check (system prompt says "auditing")  → {entities, risk, concerns}
//   - detection (everything else)               → {entities}
import { createServer } from 'node:http'

const PORT = Number(process.env.FAKE_LLM_PORT || 9099)

/**
 * Mentions the fake model "knows". Every entry is a literal string from the
 * synthetic fixtures; a mention is only reported when it occurs verbatim in
 * the chunk, exactly as a real model is expected to copy it.
 */
const KNOWN_MENTIONS = [
  { text: 'Max Mustermann', type: 'PERSON_NAME', role: 'patient' },
  { text: 'Erika Musterfrau', type: 'PERSON_NAME', role: 'clinician' },
  { text: 'Dr. med. Anna Beispiel', type: 'PERSON_NAME', role: 'clinician' },
  { text: 'Wolfgang Schäfer', type: 'PERSON_NAME', role: 'patient' },
  { text: '01.02.1980', type: 'DATE_OF_BIRTH', role: '' },
  { text: 'Musterstraße 12', type: 'ADDRESS', role: '' },
  { text: '01307 Dresden', type: 'ADDRESS', role: '' },
  { text: 'PAT-123456', type: 'ID_NUMBER', role: '' },
  { text: '2024-004711', type: 'ID_NUMBER', role: '' },
  { text: '0351 458-0', type: 'PHONE', role: '' },
  { text: 'chirurgie@beispiel-klinikum.de', type: 'EMAIL', role: '' },
  { text: 'Beispiel-Klinikum Dresden', type: 'ORGANIZATION', role: '' },
  { text: '10.03.2024', type: 'OTHER_DATE', role: '' },
  { text: '11.03.2024', type: 'OTHER_DATE', role: '' },
  { text: '15.03.2024', type: 'OTHER_DATE', role: '' },
  // backend/tests/files/9874562_text.pdf (the English PDF fixture).
  { text: 'Ashley Park', type: 'PERSON_NAME', role: 'patient' },
  { text: 'Prof. Malala Miller', type: 'PERSON_NAME', role: 'clinician' },
  { text: '12/24/1996', type: 'DATE_OF_BIRTH', role: '' },
  { text: '9874562', type: 'ID_NUMBER', role: '' },
  { text: 'Fictitious University Hospital', type: 'ORGANIZATION', role: '' },
  { text: 'Gender: Female', type: 'OTHER_PII', role: '' },
]

function systemPrompt(body) {
  const message = (body.messages || []).find((m) => m.role === 'system')
  return typeof message?.content === 'string' ? message.content : ''
}

function userText(body) {
  const parts = []
  for (const message of body.messages || []) {
    if (message.role !== 'user') continue
    if (typeof message.content === 'string') parts.push(message.content)
  }
  return parts.join('\n')
}

const isVision = (body) => (body.messages || []).some((m) => Array.isArray(m.content))
const isRecheck = (body) => systemPrompt(body).includes('auditing')

function detectionPayload(body) {
  const document = userText(body)
  const entities = KNOWN_MENTIONS.filter((mention) => document.includes(mention.text))
  return { entities }
}

/**
 * The re-check sees the ANONYMIZED text, where every known mention has been
 * replaced. Anything still present is a genuine leak, so reporting it keeps
 * the leakage-validation path honest rather than always returning "clean".
 */
function recheckPayload(body) {
  const output = userText(body)
  const entities = KNOWN_MENTIONS.filter(
    (mention) => mention.type !== 'OTHER_DATE' && output.includes(mention.text),
  ).map((mention) => ({ ...mention, role: '' }))
  return {
    entities,
    risk: entities.length > 0 ? 'high' : 'low',
    concerns: [],
  }
}

function content(body) {
  if (isVision(body)) return 'Seite 1\nSYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION'
  return JSON.stringify(isRecheck(body) ? recheckPayload(body) : detectionPayload(body))
}

const server = createServer((req, res) => {
  if (req.method !== 'POST') {
    res.writeHead(405).end()
    return
  }
  let raw = ''
  req.on('data', (chunk) => {
    raw += chunk
  })
  req.on('end', () => {
    let body = {}
    try {
      body = JSON.parse(raw || '{}')
    } catch {
      /* malformed body → answer with an empty entity list */
    }
    const payload = JSON.stringify({
      id: 'fake',
      object: 'chat.completion',
      model: body.model || 'fake-model',
      choices: [
        {
          index: 0,
          message: { role: 'assistant', content: content(body) },
          finish_reason: 'stop',
        },
      ],
    })
    res.writeHead(200, {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    })
    res.end(payload)
  })
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[fake-llm] listening on http://127.0.0.1:${PORT}`)
})
