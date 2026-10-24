import { describe, expect, it } from 'vitest'
import { errorMessage, errMsg } from './errorMessage'
import { ApiError } from '../api/client'

describe('errorMessage()', () => {
  it('reads .message off an Error', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom')
  })

  it('reads the human-readable message off an ApiError (detail parsed by the client)', () => {
    const e = new ApiError(400, 'API key not valid')
    expect(errorMessage(e)).toBe('API key not valid')
  })

  it('passes strings through untouched', () => {
    expect(errorMessage('plain')).toBe('plain')
  })

  it('reads .message off non-Error objects (ErrorEvent-style)', () => {
    expect(errorMessage({ message: 'from event' })).toBe('from event')
  })

  it('falls back to JSON for objects without a message', () => {
    expect(errorMessage({ code: 7 })).toBe('{"code":7}')
  })

  it('stringifies numbers, null and undefined without throwing', () => {
    expect(errorMessage(42)).toBe('42')
    expect(errorMessage(null)).toBe('null')
    expect(errorMessage(undefined)).toBe('undefined')
  })

  it('never throws for exotic values', () => {
    const circular: Record<string, unknown> = {}
    circular.self = circular
    expect(() => errorMessage(circular)).not.toThrow()
    expect(errorMessage(circular)).toBe('[object Object]')
  })

  it('the legacy errMsg alias is the same function', () => {
    expect(errMsg).toBe(errorMessage)
  })
})
