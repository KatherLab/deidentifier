/**
 * Builds renderable highlight segments over the ORIGINAL source text.
 *
 * Entity/warning offsets from the Python backend are Unicode CODE POINT
 * offsets; JavaScript string indices are UTF-16 code units. To stay correct
 * with astral characters (and defensively for all inputs), the source text is
 * split into a code point array via `Array.from(...)` and segments are built
 * by slicing/joining that array — never by `String.prototype.slice`.
 */
import type { AnonymizedEntity, ValidationWarning } from '@/types/anonymizer'

export interface HighlightSegment {
  /** Stable key for v-for rendering. */
  key: string
  /** Code point offset of the segment's first character in the source text. */
  start: number
  /** The segment's text (joined code points). */
  text: string
  /** Index into the response's `entities` array, or null for plain text. */
  entityIndex: number | null
  /** Whether this segment lies inside a located validation warning. */
  warning: boolean
  /** Index into the search matches, or null when this segment is not a hit. */
  matchIndex: number | null
  /**
   * True for the last segment of a given entity — the label chip is rendered
   * once per entity, on this segment.
   */
  showEntityLabel: boolean
}

interface Span {
  start: number
  end: number
}

/** A search hit, in the same code point offsets as everything else. */
export type MatchRange = Span

/**
 * Fold one code point for searching: lower case, without diacritics — so
 * "muller" finds "Müller" and "MÜLLER" alike, which is what a reviewer typing
 * a name from memory expects.
 *
 * The result is always exactly ONE code point, so folded and source arrays stay
 * index-aligned and a hit maps back to source offsets without any bookkeeping.
 * Anything that would fold to several code points (ß → ss, İ → i̇) keeps its
 * first one rather than shifting every following offset.
 */
const foldCache = new Map<string, string>()

function foldCodePoint(codePoint: string): string {
  const cached = foldCache.get(codePoint)
  if (cached !== undefined) return cached
  const stripped = codePoint.normalize('NFD').replace(/\p{M}/gu, '')
  const folded = Array.from((stripped.length > 0 ? stripped : codePoint).toLowerCase())[0]
  const result = folded ?? codePoint
  foldCache.set(codePoint, result)
  return result
}

/**
 * Locate every occurrence of `query` in `text`, case- and diacritic-insensitive,
 * as non-overlapping code point ranges in document order.
 *
 * The query is trimmed: a stray space pasted along with a name would otherwise
 * report zero hits, and "not found" is exactly the answer this search must
 * never give wrongly.
 */
export function findMatches(text: string, query: string): MatchRange[] {
  const needle = Array.from(query.trim()).map(foldCodePoint)
  if (needle.length === 0) return []
  const haystack = Array.from(text).map(foldCodePoint)

  const matches: MatchRange[] = []
  for (let i = 0; i + needle.length <= haystack.length; i++) {
    let j = 0
    while (j < needle.length && haystack[i + j] === needle[j]) j++
    if (j === needle.length) {
      matches.push({ start: i, end: i + needle.length })
      i += needle.length - 1
    }
  }
  return matches
}

function clamp(value: number, max: number): number {
  return Math.max(0, Math.min(max, value))
}

export function buildHighlightSegments(
  sourceText: string,
  entities: AnonymizedEntity[],
  warnings: ValidationWarning[],
  matches: MatchRange[] = [],
): HighlightSegment[] {
  const codePoints = Array.from(sourceText)
  const length = codePoints.length

  const entitySpans: (Span & { index: number })[] = entities
    .map((entity, index) => ({
      start: clamp(entity.start, length),
      end: clamp(entity.end, length),
      index,
    }))
    .filter((span) => span.end > span.start)

  const warningSpans: Span[] = warnings
    .filter(
      (warning): warning is ValidationWarning & { start: number; end: number } =>
        warning.start !== null && warning.end !== null,
    )
    .map((warning) => ({
      start: clamp(warning.start, length),
      end: clamp(warning.end, length),
    }))
    .filter((span) => span.end > span.start)

  const matchSpans: (Span & { index: number })[] = matches
    .map((match, index) => ({
      start: clamp(match.start, length),
      end: clamp(match.end, length),
      index,
    }))
    .filter((span) => span.end > span.start)

  // Elementary intervals between all span boundaries.
  const boundarySet = new Set<number>([0, length])
  for (const span of [...entitySpans, ...warningSpans, ...matchSpans]) {
    boundarySet.add(span.start)
    boundarySet.add(span.end)
  }
  const boundaries = [...boundarySet].sort((a, b) => a - b)

  const raw: Omit<HighlightSegment, 'showEntityLabel'>[] = []
  for (let i = 0; i < boundaries.length - 1; i++) {
    const start = boundaries[i]!
    const end = boundaries[i + 1]!
    if (end <= start) continue

    // Entities are non-overlapping after backend resolution; take the first
    // one covering this elementary interval.
    const entity = entitySpans.find((span) => span.start <= start && span.end >= end)
    const inWarning = warningSpans.some((span) => span.start <= start && span.end >= end)
    // Matches are non-overlapping by construction, for the same reason.
    const match = matchSpans.find((span) => span.start <= start && span.end >= end)

    const entityIndex = entity ? entity.index : null
    const matchIndex = match ? match.index : null
    const previous = raw[raw.length - 1]
    if (
      previous &&
      previous.entityIndex === entityIndex &&
      previous.warning === inWarning &&
      previous.matchIndex === matchIndex
    ) {
      // Merge adjacent segments with identical coverage.
      previous.text += codePoints.slice(start, end).join('')
      continue
    }
    raw.push({
      key: `${start}-${end}`,
      start,
      text: codePoints.slice(start, end).join(''),
      entityIndex,
      warning: inWarning,
      matchIndex,
    })
  }

  // Mark the last segment of each entity so the label chip renders once.
  const lastSegmentPerEntity = new Map<number, number>()
  raw.forEach((segment, index) => {
    if (segment.entityIndex !== null) lastSegmentPerEntity.set(segment.entityIndex, index)
  })

  return raw.map((segment, index) => ({
    ...segment,
    showEntityLabel:
      segment.entityIndex !== null && lastSegmentPerEntity.get(segment.entityIndex) === index,
  }))
}
