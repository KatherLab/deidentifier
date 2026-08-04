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

function clamp(value: number, max: number): number {
  return Math.max(0, Math.min(max, value))
}

export function buildHighlightSegments(
  sourceText: string,
  entities: AnonymizedEntity[],
  warnings: ValidationWarning[],
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

  // Elementary intervals between all span boundaries.
  const boundarySet = new Set<number>([0, length])
  for (const span of [...entitySpans, ...warningSpans]) {
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

    const entityIndex = entity ? entity.index : null
    const previous = raw[raw.length - 1]
    if (previous && previous.entityIndex === entityIndex && previous.warning === inWarning) {
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
