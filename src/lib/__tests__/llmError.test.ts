import { describe, expect, it } from 'vitest'
import { describeCodedError, isActionableProviderErrorCode, parseCodedError } from '../llmError'

const t = (key: string, values?: Record<string, string>) =>
  `${key}|${values?.details ?? ''}`.replace(/\|$/, '')

describe('parseCodedError', () => {
  it('splits a bracketed code from the provider message', () => {
    expect(parseCodedError('[llm_no_credit] Insufficient credits')).toEqual({
      code: 'llm_no_credit',
      details: 'Insufficient credits',
    })
  })

  it('accepts a code with no details and surrounding whitespace', () => {
    expect(parseCodedError('  [llm_rate_limited]  ')).toEqual({
      code: 'llm_rate_limited',
      details: '',
    })
  })

  it('recognises coded speech-to-text failures', () => {
    expect(parseCodedError('[stt_unknown_model] nope')?.code).toBe('stt_unknown_model')
    expect(parseCodedError('[stt_invalid_key] bad')?.code).toBe('stt_invalid_key')
  })

  it('ignores unknown codes and plain messages', () => {
    expect(parseCodedError('[something_else] x')).toBeNull()
    expect(parseCodedError('HTTP 500: boom')).toBeNull()
    expect(parseCodedError('Ask request failed (500): boom')).toBeNull()
  })
})

describe('describeCodedError', () => {
  it('turns a coded string into the translated actionable text with details', () => {
    expect(describeCodedError('[llm_invalid_key] No auth credentials found', t)).toBe(
      'errors.llm_invalid_key|No auth credentials found',
    )
  })

  it('returns other messages unchanged', () => {
    expect(describeCodedError('Ask request failed (500): boom', t)).toBe(
      'Ask request failed (500): boom',
    )
  })
})

describe('isActionableProviderErrorCode', () => {
  it('covers the four required cases for LLM and speech', () => {
    for (const code of [
      'llm_invalid_key',
      'llm_no_credit',
      'llm_unknown_model',
      'llm_rate_limited',
      'stt_no_credit',
      'stt_unknown_model',
      'stt_rate_limited',
    ]) {
      expect(isActionableProviderErrorCode(code)).toBe(true)
    }
    expect(isActionableProviderErrorCode('llm_failed')).toBe(false)
    expect(isActionableProviderErrorCode('stt_invalid_key')).toBe(false)
  })
})
