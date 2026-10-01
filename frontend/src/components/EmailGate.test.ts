import { describe, expect, it } from 'vitest'
import { isPlausibleEmail } from './EmailGate'

describe('isPlausibleEmail', () => {
  it('accepts anything shaped like name@domain.tld', () => {
    for (const e of ['a@b.co', 'Priya.S+demo@Example.in', '  name@clinic.org  ']) {
      expect(isPlausibleEmail(e)).toBe(true)
    }
  })
  it('rejects the rest, matching the API', () => {
    for (const e of ['', 'no-at-sign', 'a@b', 'two@@b.co', 'spa ce@b.co']) {
      expect(isPlausibleEmail(e)).toBe(false)
    }
  })
})
