// A small in-browser catalog for the mock API: the fixture SKUs plus a couple of dozen
// common Indian brands so the pharmacist's SKU picker and typed orders feel real.
// Prices are approximate MRPs; the real catalog comes from the backend in Wave 2.
import type { MatchCandidate, SKU } from '../../contracts.gen'
import catalogFixture from '../../../../contracts/fixtures/catalog_search.json'
import pendingFixture from '../../../../contracts/fixtures/order_pending_review.json'
import otcFixture from '../../../../contracts/fixtures/order_text_otc.json'

type Salts = [string, string | null][]

function sku(
  sku_id: string,
  brand_name: string,
  manufacturer: string,
  form: SKU['form'],
  pack_size: number,
  pack_label: string,
  mrp_inr: number,
  salts: Salts,
  rx: SKU['schedule'] | false,
): SKU {
  const composition = salts.map(([name, strength]) => ({ name, strength }))
  const composition_key = [...composition]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((s) => (s.strength ? `${s.name} ${s.strength}` : s.name))
    .join(' + ')
  return {
    sku_id,
    brand_name,
    manufacturer,
    form,
    pack_size,
    pack_label,
    mrp_inr,
    composition,
    composition_key,
    rx_only: rx !== false,
    schedule: rx === false ? null : rx,
  }
}

const strip = (n: number, what = 'tablets') => `strip of ${n} ${what}`

const EXTRA: SKU[] = [
  sku('sku_clavam_625', 'Clavam 625', 'Alkem', 'tablet', 10, strip(10), 201.6, [['amoxycillin', '500mg'], ['clavulanic acid', '125mg']], 'H'),
  sku('sku_crocin_650', 'Crocin 650 Advance', 'GSK Consumer', 'tablet', 15, strip(15), 34.5, [['paracetamol', '650mg']], false),
  sku('sku_calpol_650', 'Calpol 650', 'GlaxoSmithKline', 'tablet', 15, strip(15), 31.2, [['paracetamol', '650mg']], false),
  sku('sku_paracip_650', 'Paracip 650', 'Cipla', 'tablet', 10, strip(10), 17.9, [['paracetamol', '650mg']], false),
  sku('sku_pantocid_40', 'Pantocid 40', 'Sun Pharma', 'tablet', 15, strip(15), 169.0, [['pantoprazole', '40mg']], 'H'),
  sku('sku_pantodac_40', 'Pantodac 40', 'Zydus Cadila', 'tablet', 15, strip(15), 118.5, [['pantoprazole', '40mg']], 'H'),
  sku('sku_pan_d', 'Pan-D', 'Alkem', 'capsule', 15, strip(15, 'capsules'), 199.0, [['pantoprazole', '40mg'], ['domperidone', '30mg']], 'H'),
  sku('sku_azithral_500', 'Azithral 500', 'Alembic', 'tablet', 5, strip(5), 119.5, [['azithromycin', '500mg']], 'H'),
  sku('sku_azee_500', 'Azee 500', 'Cipla', 'tablet', 5, strip(5), 97.3, [['azithromycin', '500mg']], 'H'),
  sku('sku_montair_lc', 'Montair LC', 'Cipla', 'tablet', 15, strip(15), 247.0, [['montelukast', '10mg'], ['levocetirizine', '5mg']], 'H'),
  sku('sku_montek_lc', 'Montek LC', 'Sun Pharma', 'tablet', 10, strip(10), 132.0, [['montelukast', '10mg'], ['levocetirizine', '5mg']], 'H'),
  sku('sku_okacet_10', 'Okacet 10', 'Cipla', 'tablet', 10, strip(10), 18.4, [['cetirizine', '10mg']], false),
  sku('sku_cetzine_10', 'Cetzine 10', 'Dr. Reddy’s', 'tablet', 10, strip(10), 21.0, [['cetirizine', '10mg']], false),
  sku('sku_allegra_120', 'Allegra 120', 'Sanofi', 'tablet', 10, strip(10), 219.0, [['fexofenadine', '120mg']], 'H'),
  sku('sku_shelcal_500', 'Shelcal 500', 'Torrent', 'tablet', 15, strip(15), 118.0, [['calcium carbonate', '1250mg'], ['vitamin d3', '250iu']], false),
  sku('sku_becosules', 'Becosules Z', 'Pfizer', 'capsule', 20, strip(20, 'capsules'), 49.0, [['vitamin b complex', null], ['zinc', '50mg']], false),
  sku('sku_digene_gel', 'Digene Gel Mint', 'Abbott', 'suspension', 1, 'bottle of 200 ml', 185.0, [['magnesium hydroxide', null], ['aluminium hydroxide', null], ['simethicone', null]], false),
  sku('sku_ecosprin_75', 'Ecosprin 75', 'USV', 'tablet', 14, strip(14), 5.3, [['aspirin', '75mg']], 'H'),
  sku('sku_telma_40', 'Telma 40', 'Glenmark', 'tablet', 30, strip(30), 258.0, [['telmisartan', '40mg']], 'H'),
  sku('sku_glycomet_500', 'Glycomet 500', 'USV', 'tablet', 20, strip(20), 35.4, [['metformin', '500mg']], 'H'),
  sku('sku_thyronorm_50', 'Thyronorm 50', 'Abbott', 'tablet', 120, 'bottle of 120 tablets', 214.0, [['thyroxine', '50mcg']], 'H'),
  sku('sku_ors_orange', 'ORS Orange Powder', 'FDC', 'sachet', 1, 'sachet of 21 g', 21.0, [['oral rehydration salts', null]], false),
  sku('sku_benadryl_150', 'Benadryl Cough Syrup', 'Johnson & Johnson', 'syrup', 1, 'bottle of 150 ml', 142.0, [['diphenhydramine', '14.08mg/5ml'], ['ammonium chloride', '138mg/5ml']], false),
  sku('sku_volini_gel', 'Volini Gel', 'Sun Pharma', 'gel', 1, 'tube of 30 g', 135.0, [['diclofenac', '1%']], false),
]

function fixtureSkus(): SKU[] {
  const out: SKU[] = []
  for (const c of catalogFixture as MatchCandidate[]) out.push(c.sku)
  for (const order of [pendingFixture, otcFixture]) {
    for (const item of order.items) {
      if (item.sku) out.push(item.sku as SKU)
      if (item.generic_alternative) out.push(item.generic_alternative as SKU)
    }
  }
  return out
}

export const CATALOG: SKU[] = (() => {
  const byId = new Map<string, SKU>()
  for (const s of [...fixtureSkus(), ...EXTRA]) if (!byId.has(s.sku_id)) byId.set(s.sku_id, s)
  return [...byId.values()]
})()

export function findSku(skuId: string): SKU | undefined {
  return CATALOG.find((s) => s.sku_id === skuId)
}

/** Cheapest other SKU with the same composition_key, if it saves money. */
export function cheapestGeneric(s: SKU): SKU | null {
  let best: SKU | null = null
  for (const c of CATALOG) {
    if (c.sku_id === s.sku_id || c.composition_key !== s.composition_key) continue
    if (c.mrp_inr / c.pack_size >= s.mrp_inr / s.pack_size) continue
    if (!best || c.mrp_inr / c.pack_size < best.mrp_inr / best.pack_size) best = c
  }
  return best
}

const ALIASES: Record<string, string> = {
  ors: 'electral',
  paracetamol: 'dolo 650',
  pcm: 'dolo 650',
  crocin: 'crocin 650',
  cetirizine: 'okacet',
  antacid: 'digene',
  calcium: 'shelcal',
  'cough syrup': 'benadryl',
}

function trigrams(s: string): Set<string> {
  const t = `  ${s} `
  const out = new Set<string>()
  for (let i = 0; i < t.length - 2; i++) out.add(t.slice(i, i + 3))
  return out
}

function similarity(a: string, b: string): number {
  const A = trigrams(a)
  const B = trigrams(b)
  let inter = 0
  for (const g of A) if (B.has(g)) inter++
  return inter / (A.size + B.size - inter)
}

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim()

/** Trigram-ish search over brand and salt names, a stand-in for pg_trgm. */
export function searchCatalog(query: string, limit = 10): MatchCandidate[] {
  let q = norm(query)
  if (!q) return []
  q = ALIASES[q] ?? q
  const scored = CATALOG.map((s) => {
    const brand = norm(s.brand_name)
    const salts = norm(s.composition.map((c) => c.name).join(' '))
    let score = Math.max(similarity(q, brand), similarity(q, salts) * 0.9)
    if (brand.startsWith(q)) score = Math.max(score, 0.9 + 0.1 * (q.length / brand.length))
    else if (brand.includes(q)) score = Math.max(score, 0.8)
    else if (salts.includes(q)) score = Math.max(score, 0.75)
    return { sku: s, score: Math.round(Math.min(score, 0.99) * 100) / 100 }
  })
  return scored
    .filter((c) => c.score >= 0.3)
    .sort((a, b) => b.score - a.score || a.sku.mrp_inr - b.sku.mrp_inr)
    .slice(0, Math.min(limit, 20))
}
