// Rupee formatting. Indian digit grouping (₹1,23,456.00) and always two decimals,
// because a pharmacist reads ₹33.60 differently from ₹33.6.
const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function formatINR(amount: number | null | undefined): string {
  if (amount == null || !Number.isFinite(amount)) return '₹—'
  // Normalise -0 and float noise such as 412.09999999.
  const v = Math.round(amount * 100) / 100 || 0
  return inr.format(v).replace(/ /g, '')
}

/** Round to paise, avoiding binary float drift when summing prices. */
export function roundINR(amount: number): number {
  return Math.round(amount * 100) / 100
}

export function sumINR(values: number[]): number {
  return roundINR(values.reduce((acc, v) => acc + Math.round(v * 100), 0) / 100)
}
