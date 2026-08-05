/**
 * Localization of backend messages.
 *
 * The backend emits every non-fatal message as a stable `code` plus its
 * `params` (backend/src/utils/notices.py) and keeps an English `message` as the
 * rendering of last resort. This module resolves such a message against the
 * active catalog (`warnings.codes.*`) and falls back to the backend text for
 * anything the frontend does not know — a new backend code shows up as English
 * prose rather than as a raw key or an empty line.
 */
import { hasMessage, t } from '@/i18n'
import { entityTypeLabel } from '@/utils/entityLabels'
import type { Notice, NoticeParams, ValidationWarning } from '@/types/anonymizer'

/**
 * Params that are themselves backend vocabulary get their own label, so
 * "{entity_type}" reads "E-Mail" and not "EMAIL".
 */
function localizeParams(params: NoticeParams): NoticeParams {
  const localized: NoticeParams = { ...params }
  if (typeof params.entity_type === 'string') {
    localized.entity_type = entityTypeLabel(params.entity_type)
  }
  const riskKey = `warnings.risk.${String(params.risk)}`
  if (typeof params.risk === 'string' && hasMessage(riskKey)) {
    localized.risk = t(riskKey)
  }
  return localized
}

/** The localized text of a backend notice or validation warning. */
export function noticeMessage(notice: Notice | ValidationWarning): string {
  const key = `warnings.codes.${notice.code}`
  if (!notice.code || !hasMessage(key)) return notice.message
  return t(key, localizeParams(notice.params ?? {}))
}
