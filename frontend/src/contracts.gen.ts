/* Generated from contracts/schema.json by scripts/gen-contracts.mjs. Do not edit. */

export interface RioContracts {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "ApiError".
 */
export interface ApiError {
  code: string;
  message: string;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "BacktestSummary".
 */
export interface BacktestSummary {
  horizon_days: number;
  model_mape: number;
  naive_mape: number;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "CartItem".
 */
export interface CartItem {
  confidence: Confidence;
  /**
   * Cheapest SKU with the same composition_key
   */
  generic_alternative: SKU | null;
  item_id: string;
  line_total_inr: number;
  /**
   * Null for typed-text orders
   */
  parsed: ParsedLine | null;
  quantity_packs: number;
  /**
   * The typed request, for text orders
   */
  requested_text: string | null;
  /**
   * Per line, if the customer swaps
   */
  savings_inr: number | null;
  /**
   * Null when nothing matched; always red
   */
  sku: SKU | null;
  status: "pending" | "approved" | "edited" | "removed";
  unit_price_inr: number;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "Confidence".
 */
export interface Confidence {
  /**
   * Share of drug/strength/frequency/duration present
   */
  completeness: number;
  /**
   * 1 - illegible fields / fields read
   */
  legibility: number;
  match_score: number;
  /**
   * Short, pharmacist-facing, e.g. 'strength unreadable'
   */
  reasons: string[];
  /**
   * Combined score used for sorting
   */
  score: number;
  triage: "green" | "amber" | "red";
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "SKU".
 */
export interface SKU {
  brand_name: string;
  composition: Salt[];
  /**
   * Canonical sorted 'salt strength + salt strength'; equal keys = substitutable
   */
  composition_key: string;
  form:
    | "tablet"
    | "capsule"
    | "syrup"
    | "suspension"
    | "injection"
    | "cream"
    | "ointment"
    | "gel"
    | "drops"
    | "inhaler"
    | "powder"
    | "sachet"
    | "other";
  manufacturer: string;
  /**
   * Price per pack in rupees
   */
  mrp_inr: number;
  /**
   * Human label, e.g. 'strip of 10 tablets'
   */
  pack_label: string;
  /**
   * Units per pack, e.g. 10 for a strip of 10
   */
  pack_size: number;
  rx_only: boolean;
  schedule: ("H" | "H1" | "X") | null;
  sku_id: string;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "Salt".
 */
export interface Salt {
  /**
   * Normalized lowercase salt, e.g. 'amoxycillin'
   */
  name: string;
  /**
   * Normalized, e.g. '500mg', '5mg/ml'
   */
  strength: string | null;
}
/**
 * One medicine line as read off the prescription. No catalog knowledge.
 *
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "ParsedLine".
 */
export interface ParsedLine {
  /**
   * Optional [x0, y0, x1, y1] in 0..1 image coordinates; UI falls back to the full image
   */
  bbox: [number, number, number, number] | null;
  /**
   * Normalized from frequency: '1-0-1' -> 2, 'TDS' -> 3, 'SOS' -> null
   */
  doses_per_day: number | null;
  /**
   * Brand or generic name as written, e.g. 'Augmentin'
   */
  drug: string | null;
  duration_days: number | null;
  form:
    | (
        | "tablet"
        | "capsule"
        | "syrup"
        | "suspension"
        | "injection"
        | "cream"
        | "ointment"
        | "gel"
        | "drops"
        | "inhaler"
        | "powder"
        | "sachet"
        | "other"
      )
    | null;
  /**
   * As written, e.g. '1-0-1', 'BD', 'SOS'
   */
  frequency: string | null;
  /**
   * Fields the model could not read with confidence
   */
  illegible_fields: ("drug" | "strength" | "form" | "frequency" | "duration" | "quantity")[];
  /**
   * 1-based position on the prescription
   */
  line_no: number;
  /**
   * Only if an explicit count is written
   */
  quantity: number | null;
  /**
   * The line exactly as written, for the pharmacist
   */
  raw_text: string;
  /**
   * As written, e.g. '625', '500/125 mg', '5 ml'
   */
  strength: string | null;
}
/**
 * Base for every contract model. In the exported schema, fields with defaults are
 * still marked required for responses, because the API always sends them.
 *
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "Contract".
 */
export interface Contract {}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "ErrorResponse".
 */
export interface ErrorResponse {
  error: ApiError;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "ForecastPoint".
 */
export interface ForecastPoint {
  /**
   * Present inside the backtest window
   */
  actual: number | null;
  forecast: number;
  /**
   * Start of the hour, Asia/Kolkata
   */
  ts: string;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "ForecastSummary".
 */
export interface ForecastSummary {
  areas: string[];
  backtest: BacktestSummary;
  generated_at: string;
  /**
   * Stockout risks first
   */
  reorders: ReorderSuggestion[];
  /**
   * SKUs that have forecasts, for the picker
   */
  skus: SkuRef[];
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "ReorderSuggestion".
 */
export interface ReorderSuggestion {
  area: string;
  brand_name: string;
  forecast_over_lead_time: number;
  hours_to_stockout: number | null;
  on_hand: number;
  reorder_qty: number;
  sku_id: string;
  stockout_risk: boolean;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "SkuRef".
 */
export interface SkuRef {
  brand_name: string;
  sku_id: string;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "ItemDecision".
 */
export interface ItemDecision {
  action: "approve" | "edit" | "remove";
  item_id: string;
  quantity_packs?: number | null;
  /**
   * Required for edit when changing the SKU
   */
  sku_id?: string | null;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "MatchCandidate".
 */
export interface MatchCandidate {
  /**
   * Trigram or re-rank score
   */
  score: number;
  sku: SKU;
}
/**
 * What the matcher decided for one ParsedLine.
 *
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "MatchResult".
 */
export interface MatchResult {
  /**
   * Top candidates considered, best first
   */
  candidates: MatchCandidate[];
  reason: string | null;
  /**
   * True when the LLM re-rank ran
   */
  reranked: boolean;
  score: number;
  /**
   * Chosen SKU, or null when nothing fits
   */
  sku: SKU | null;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "Order".
 */
export interface Order {
  created_at: string;
  /**
   * GET /api/orders/{id}/image serves it when true
   */
  has_image: boolean;
  items: CartItem[];
  order_id: string;
  parsed_rx: ParsedRx | null;
  pharmacist_note: string | null;
  requires_review: boolean;
  reviewed_at: string | null;
  source: "prescription" | "sample" | "text";
  status: "pending_review" | "verified" | "rejected" | "confirmed_otc" | "needs_prescription" | "placed";
  total_inr: number;
}
/**
 * Everything the vision model extracted from one prescription image.
 *
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "ParsedRx".
 */
export interface ParsedRx {
  clinic_name: string | null;
  cost_usd: number | null;
  doctor_name: string | null;
  latency_ms: number;
  lines: ParsedLine[];
  /**
   * OpenRouter model id that produced this parse
   */
  model: string;
  patient_name: string | null;
  rx_date: string | null;
}
/**
 * One row in the pharmacist queue. Worst triage first, then oldest first.
 *
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "QueueItem".
 */
export interface QueueItem {
  counts: {
    [k: string]: number;
  };
  created_at: string;
  item_count: number;
  order_id: string;
  source: "prescription" | "sample" | "text";
  total_inr: number;
  worst_triage: "green" | "amber" | "red";
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "ReviewRequest".
 */
export interface ReviewRequest {
  decision: "approve" | "reject";
  /**
   * Items not listed are approved as is
   */
  items?: ItemDecision[];
  note?: string | null;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "Sample".
 */
export interface Sample {
  /**
   * e.g. 'Typed clinic Rx, 3 lines'
   */
  label: string;
  sample_id: string;
  thumbnail_url: string;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "SkuForecast".
 */
export interface SkuForecast {
  area: string;
  brand_name: string;
  /**
   * Backtest error of our model on this series
   */
  model_mape: number;
  /**
   * Same hour last week
   */
  naive_mape: number;
  points: ForecastPoint[];
  sku_id: string;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "SwapRequest".
 */
export interface SwapRequest {
  item_id: string;
  use_generic: boolean;
}
/**
 * This interface was referenced by `RioContracts`'s JSON-Schema
 * via the `definition` "TextOrderRequest".
 */
export interface TextOrderRequest {
  text: string;
}
