import { describe, expect, it } from 'vitest'
import { formatINR, roundINR, sumINR } from './money'

describe('formatINR', () => {
  it('formats a simple amount with two decimals', () => {
    expect(formatINR(1234.5)).toBe('₹1,234.50')
  })

  it('formats zero', () => {
    expect(formatINR(0)).toBe('₹0.00')
  })

  it('formats a value already at two decimals', () => {
    expect(formatINR(33.6)).toBe('₹33.60')
  })

  it('uses Indian digit grouping for large amounts', () => {
    expect(formatINR(123456.789)).toBe('₹1,23,456.79')
  })

  it('rounds away binary float noise', () => {
    expect(formatINR(0.1 + 0.2)).toBe('₹0.30')
  })

  it('renders null as an em dash', () => {
    expect(formatINR(null)).toBe('₹—')
  })

  it('renders undefined as an em dash', () => {
    expect(formatINR(undefined)).toBe('₹—')
  })

  it('renders NaN as an em dash', () => {
    expect(formatINR(NaN)).toBe('₹—')
  })

  it('renders Infinity as an em dash', () => {
    expect(formatINR(Infinity)).toBe('₹—')
  })

  it('normalises negative zero to a plain zero', () => {
    expect(formatINR(-0)).toBe('₹0.00')
  })
})

describe('roundINR', () => {
  it('rounds to the nearest paisa', () => {
    expect(roundINR(412.09999999)).toBe(412.1)
  })
})

describe('sumINR', () => {
  it('sums a set of line totals without float drift', () => {
    expect(sumINR([223.5, 155, 33.6])).toBe(412.1)
  })

  it('sums an empty list to zero', () => {
    expect(sumINR([])).toBe(0)
  })
})
