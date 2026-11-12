/**
 * Provider failures (OpenRouter and other BYOK providers) arrive from the backend either as a
 * structured pipeline error (`{ code, details }`) or, for Ask and connection tests, as a plain
 * string of the form `[llm_no_credit] <provider message>`. These helpers turn both into
 * actionable, translated text.
 */

export const ACTIONABLE_LLM_ERROR_CODES = [
  'llm_invalid_key',
  'llm_no_credit',
  'llm_unknown_model',
  'llm_rate_limited',
  'llm_model_unavailable',
  'llm_moderated',
] as const

export const ACTIONABLE_STT_ERROR_CODES = [
  'stt_no_credit',
  'stt_unknown_model',
  'stt_rate_limited',
] as const

export type ActionableProviderErrorCode =
  | (typeof ACTIONABLE_LLM_ERROR_CODES)[number]
  | (typeof ACTIONABLE_STT_ERROR_CODES)[number]

const ACTIONABLE_CODES = new Set<string>([
  ...ACTIONABLE_LLM_ERROR_CODES,
  ...ACTIONABLE_STT_ERROR_CODES,
])

// stt_invalid_key already has its own long message; it can also arrive as a coded string.
const CODED_STRING_CODES = new Set<string>([...ACTIONABLE_CODES, 'stt_invalid_key'])

export function isActionableProviderErrorCode(code: string): code is ActionableProviderErrorCode {
  return ACTIONABLE_CODES.has(code)
}

export interface CodedError {
  code: string
  details: string
}

export function parseCodedError(message: string): CodedError | null {
  const match = /^\[([a-z_]+)\]\s*([\s\S]*)$/.exec(message.trim())
  if (!match || !CODED_STRING_CODES.has(match[1])) return null
  return { code: match[1], details: match[2].trim() }
}

type Translate = (key: string, values?: Record<string, string>) => string

/** Actionable text for a coded string; any other message is returned unchanged. */
export function describeCodedError(message: string, t: Translate): string {
  const coded = parseCodedError(message)
  if (!coded) return message
  return t(`errors.${coded.code}`, { details: coded.details }).trim()
}
