import { describe, expect, it } from 'vitest'
import { searchCatalog } from './catalog'

describe('searchCatalog', () => {
  it('ranks the exact brand match for "augmentin" first', () => {
    const results = searchCatalog('augmentin')
    expect(results[0]?.sku.sku_id).toBe('sku_augmentin_625')
  })

  it('caps results at 20 even when a higher limit is requested', () => {
    const results = searchCatalog('a', 25)
    expect(results.length).toBeLessThanOrEqual(20)
  })

  it('returns nothing for an empty query', () => {
    expect(searchCatalog('')).toEqual([])
  })
})
