// Builders for mock orders: seeded from contracts/fixtures and extended with a second sample.
import type { CartItem, Confidence, Order, ParsedLine, ParsedRx, SKU } from '../../contracts.gen'
import pendingFixture from '../../../../contracts/fixtures/order_pending_review.json'
import { roundINR, sumINR } from '../../lib/money'
import { cheapestGeneric, findSku } from './catalog'

export const PENDING_FIXTURE = pendingFixture as unknown as Order

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T

/** quantity_packs per contracts/API.md: written quantity, else ceil(dpd × days / pack), else 1. */
export function computePacks(line: ParsedLine | null, s: SKU | null): { packs: number; reason: string | null } {
  if (!line || !s) return { packs: 1, reason: null }
  if (line.quantity != null && line.quantity > 0) return { packs: line.quantity, reason: null }
  if (line.doses_per_day == null || line.duration_days == null) {
    return { packs: 1, reason: 'dose or duration missing; assumed 1 pack' }
  }
  return { packs: Math.max(1, Math.ceil((line.doses_per_day * line.duration_days) / s.pack_size)), reason: null }
}

export function triageFor(c: Omit<Confidence, 'triage' | 'score' | 'reasons'>, hasSku: boolean, drugIllegible: boolean) {
  if (!hasSku || drugIllegible || c.match_score < 0.6) return 'red' as const
  if (c.match_score < 0.85 || c.completeness < 1 || c.legibility < 1) return 'amber' as const
  return 'green' as const
}

export function priceItem(item: CartItem): CartItem {
  const unit = item.sku ? item.sku.mrp_inr : 0
  const generic = item.generic_alternative
  const swapped = !!(generic && item.sku && generic.sku_id === item.sku.sku_id)
  return {
    ...item,
    unit_price_inr: unit,
    line_total_inr: roundINR(unit * item.quantity_packs),
    savings_inr:
      generic && item.sku && !swapped
        ? roundINR((item.sku.mrp_inr - generic.mrp_inr) * item.quantity_packs)
        : item.savings_inr,
  }
}

export function priceOrder(order: Order): Order {
  const items = order.items.map(priceItem)
  return {
    ...order,
    items,
    total_inr: sumINR(items.filter((i) => i.status !== 'removed').map((i) => i.line_total_inr)),
  }
}

interface LineSpec {
  raw: string
  drug: string | null
  strength: string | null
  form: ParsedLine['form']
  frequency: string | null
  dpd: number | null
  days: number | null
  illegible?: ParsedLine['illegible_fields']
  skuId: string | null
  match: number
  reasons?: string[]
}

function buildItem(spec: LineSpec, lineNo: number): CartItem {
  const parsed: ParsedLine = {
    line_no: lineNo,
    raw_text: spec.raw,
    drug: spec.drug,
    strength: spec.strength,
    form: spec.form,
    frequency: spec.frequency,
    doses_per_day: spec.dpd,
    duration_days: spec.days,
    quantity: null,
    illegible_fields: spec.illegible ?? [],
    bbox: null,
  }
  const s = spec.skuId ? (findSku(spec.skuId) ?? null) : null
  const fields = [parsed.drug, parsed.strength, parsed.frequency, parsed.duration_days]
  const completeness = fields.filter((f) => f != null).length / fields.length
  const legibility = roundINR(1 - parsed.illegible_fields.length / 5)
  const { packs, reason } = computePacks(parsed, s)
  const reasons = [...(spec.reasons ?? [])]
  if (reason && !reasons.some((r) => r.includes('assumed'))) reasons.push(reason)
  const partial = { match_score: spec.match, completeness, legibility }
  const triage = triageFor(partial, !!s, parsed.illegible_fields.includes('drug'))
  const generic = s ? cheapestGeneric(s) : null
  return priceItem({
    item_id: `itm_${lineNo}`,
    parsed,
    requested_text: null,
    sku: s,
    quantity_packs: packs,
    unit_price_inr: 0,
    line_total_inr: 0,
    generic_alternative: generic,
    savings_inr: null,
    confidence: {
      score: roundINR(spec.match * 0.5 + completeness * 0.25 + legibility * 0.25),
      ...partial,
      triage,
      reasons,
    },
    status: 'pending',
  })
}

const HANDWRITTEN_LINES: LineSpec[] = [
  {
    raw: 'T. Azithral 500  1-0-0 × 3d',
    drug: 'Azithral',
    strength: '500',
    form: 'tablet',
    frequency: '1-0-0',
    dpd: 1,
    days: 3,
    skuId: 'sku_azithral_500',
    match: 0.95,
  },
  {
    raw: 'T. Mont~r LC  0-0-1 × 10d',
    drug: 'Montair LC',
    strength: null,
    form: 'tablet',
    frequency: '0-0-1',
    dpd: 1,
    days: 10,
    illegible: ['drug'],
    skuId: 'sku_montair_lc',
    match: 0.71,
    reasons: ['brand partly illegible: read as “Mont~r LC”', 'strength not written'],
  },
]

// Real-data edge cases: a long brand name, a line with no catalog match (sku null, always red),
// a line whose SKU has no cheaper generic, and a missing duration.
const MESSY_LINES: LineSpec[] = [
  {
    raw: 'Tab Augmentin Duo DT 625 1-0-1 x 5 days after food',
    drug: 'Augmentin Duo DT',
    strength: '625',
    form: 'tablet',
    frequency: '1-0-1',
    dpd: 2,
    days: 5,
    skuId: 'sku_augmentin_duo_dt',
    match: 0.88,
  },
  {
    raw: 'Cap. R?x~l Z? 1-0-1 x 7d',
    drug: null,
    strength: null,
    form: 'capsule',
    frequency: '1-0-1',
    dpd: 2,
    days: 7,
    illegible: ['drug', 'strength'],
    skuId: null,
    match: 0.21,
    reasons: ['no catalog match', 'drug name illegible'],
  },
  {
    raw: 'Tab Thyronorm 50mcg 1-0-0 empty stomach x 30 days',
    drug: 'Thyronorm',
    strength: '50mcg',
    form: 'tablet',
    frequency: '1-0-0',
    dpd: 1,
    days: 30,
    skuId: 'sku_thyronorm_50',
    match: 0.97,
  },
  {
    raw: 'Tab Telma 40 0-0-1',
    drug: 'Telma',
    strength: '40',
    form: 'tablet',
    frequency: '0-0-1',
    dpd: 1,
    days: null,
    illegible: ['duration'],
    skuId: 'sku_telma_40',
    match: 0.93,
    reasons: ['duration not written; assumed 1 pack'],
  },
]

export interface OrderSeed {
  items: CartItem[]
  parsed_rx: ParsedRx
}

/** The parse a sample (or, in mocks, any uploaded photo) produces. */
export function sampleParse(sampleId: string): OrderSeed | null {
  if (sampleId === 'typed_clinic_3') {
    return { items: clone(PENDING_FIXTURE.items), parsed_rx: clone(PENDING_FIXTURE.parsed_rx!) }
  }
  if (sampleId === 'messy_4') {
    const items = MESSY_LINES.map((l, i) => buildItem(l, i + 1))
    return {
      items,
      parsed_rx: {
        doctor_name: null,
        clinic_name: 'Shree Sai Polyclinic & Diagnostic Centre, Kandivali (East)',
        patient_name: 'Mohammed Irfan Shaikh',
        rx_date: null,
        lines: items.map((i) => i.parsed!),
        model: 'example/vision-model',
        latency_ms: 18420,
        cost_usd: 0.0031,
      },
    }
  }
  if (sampleId === 'blank_0') {
    return {
      items: [],
      parsed_rx: {
        doctor_name: null,
        clinic_name: null,
        patient_name: null,
        rx_date: null,
        lines: [],
        model: 'example/vision-model',
        latency_ms: 9800,
        cost_usd: 0.0012,
      },
    }
  }
  if (sampleId === 'handwritten_2') {
    const items = HANDWRITTEN_LINES.map((l, i) => buildItem(l, i + 1))
    return {
      items,
      parsed_rx: {
        doctor_name: 'Dr. S. Kulkarni',
        clinic_name: 'Child & Family Clinic',
        patient_name: 'Priya N.',
        rx_date: '2026-09-27',
        lines: items.map((i) => i.parsed!),
        model: 'example/vision-model',
        latency_ms: 7340,
        cost_usd: 0.0024,
      },
    }
  }
  return null
}

/** A small all-green order so the queue has more than one row when the demo opens. */
export function greenSeed(): OrderSeed {
  const items = [
    buildItem(
      {
        raw: 'Tab Thyronorm 50mcg  1-0-0 empty stomach × 30 days',
        drug: 'Thyronorm',
        strength: '50mcg',
        form: 'tablet',
        frequency: '1-0-0',
        dpd: 1,
        days: 30,
        skuId: 'sku_thyronorm_50',
        match: 0.96,
      },
      1,
    ),
    buildItem(
      {
        raw: 'Tab Shelcal 500  0-1-0 × 30 days',
        drug: 'Shelcal',
        strength: '500',
        form: 'tablet',
        frequency: '0-1-0',
        dpd: 1,
        days: 30,
        skuId: 'sku_shelcal_500',
        match: 0.93,
      },
      2,
    ),
  ]
  return {
    items,
    parsed_rx: {
      doctor_name: 'Dr. N. Iyer',
      clinic_name: 'Lakeview Endocrine',
      patient_name: 'M. Fernandes',
      rx_date: '2026-09-29',
      lines: items.map((i) => i.parsed!),
      model: 'example/vision-model',
      latency_ms: 5210,
      cost_usd: 0.0019,
    },
  }
}
