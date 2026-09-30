// Prescription images for the mock API, drawn as SVG so the demo needs no binary assets.

const HAND = `'Bradley Hand','Segoe Print','Comic Sans MS',cursive`
const TYPE = `'Courier New',Courier,monospace`

function page(inner: string, tint: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 800" width="600" height="800">
  <defs>
    <filter id="paper"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" seed="4"/><feColorMatrix values="0 0 0 0 0.55  0 0 0 0 0.52  0 0 0 0 0.45  0 0 0 0.07 0"/><feComposite in2="SourceGraphic" operator="in"/></filter>
    <linearGradient id="shade" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.08"/></linearGradient>
  </defs>
  <rect width="600" height="800" fill="${tint}"/>
  <rect width="600" height="800" filter="url(#paper)"/>
  ${inner}
  <rect width="600" height="800" fill="url(#shade)"/>
</svg>`
}

const typedClinic = page(
  `<text x="40" y="70" font-family="Georgia,serif" font-size="30" font-weight="700" fill="#1d3b6e">Sunrise Clinic</text>
  <text x="40" y="96" font-family="Georgia,serif" font-size="15" fill="#1d3b6e">Dr. A. Mehta, MBBS, MD (Medicine) · Reg. No. 48213</text>
  <text x="40" y="116" font-family="Georgia,serif" font-size="13" fill="#4b5d7a">14 Link Road, Andheri West, Mumbai · Mon–Sat 10–1, 5–8</text>
  <line x1="40" y1="132" x2="560" y2="132" stroke="#1d3b6e" stroke-width="2"/>
  <text x="40" y="170" font-family="${TYPE}" font-size="16" fill="#222">Patient: R. Sharma    Age/Sex: 34/M</text>
  <text x="400" y="170" font-family="${TYPE}" font-size="16" fill="#222">Date: 28/09/26</text>
  <text x="40" y="230" font-family="Georgia,serif" font-size="44" font-style="italic" fill="#1d3b6e">℞</text>
  <text x="70" y="290" font-family="${TYPE}" font-size="19" fill="#222">1. Tab. Augmentin 625   1-0-1 x 5 days</text>
  <text x="70" y="340" font-family="${TYPE}" font-size="19" fill="#222">2. Tab Pan 40   1-0-0 before food x 5d</text>
  <text x="70" y="390" font-family="${TYPE}" font-size="19" fill="#222">3. Tab D</text>
  <ellipse cx="163" cy="384" rx="11" ry="9" fill="#6b7d99" opacity="0.55"/>
  <text x="172" y="390" font-family="${TYPE}" font-size="19" fill="#222">lo 650   SOS</text>
  <text x="70" y="460" font-family="${TYPE}" font-size="16" fill="#444">Adv: plenty of fluids, review after 5 days.</text>
  <path d="M390 640 c 20 -40, 40 10, 60 -20 s 30 30, 60 -10" stroke="#1d3b6e" stroke-width="2.5" fill="none"/>
  <text x="400" y="690" font-family="Georgia,serif" font-size="14" fill="#1d3b6e">Dr. A. Mehta</text>`,
  '#fbfaf5',
)

const handwritten = page(
  `<text x="40" y="70" font-family="Georgia,serif" font-size="26" font-weight="700" fill="#7a2d2d">Dr. S. Kulkarni</text>
  <text x="40" y="94" font-family="Georgia,serif" font-size="14" fill="#7a2d2d">MBBS, DCH · Child &amp; Family Clinic, Pune</text>
  <line x1="40" y1="110" x2="560" y2="110" stroke="#7a2d2d" stroke-width="1.5"/>
  <text x="40" y="160" font-family="${HAND}" font-size="24" fill="#1c2f6b">Priya N.   29 F        27/9/26</text>
  <text x="44" y="236" font-family="${HAND}" font-size="46" fill="#1c2f6b">Rx</text>
  <g transform="rotate(-2 300 320)">
    <text x="90" y="310" font-family="${HAND}" font-size="30" fill="#1c2f6b">T. Azithral 500</text>
    <text x="150" y="350" font-family="${HAND}" font-size="26" fill="#1c2f6b">1 — 0 — 0  × 3d</text>
  </g>
  <g transform="rotate(-3 300 460)">
    <text x="90" y="440" font-family="${HAND}" font-size="30" fill="#1c2f6b">T. Mont~r LC</text>
    <text x="150" y="480" font-family="${HAND}" font-size="26" fill="#1c2f6b">0 — 0 — 1  × 10d</text>
  </g>
  <path d="M380 660 q 30 -50 50 -5 t 50 -10 t 40 5" stroke="#1c2f6b" stroke-width="2.5" fill="none"/>`,
  '#f7f4ea',
)

const svgUrl = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`

export const SAMPLE_IMAGES: Record<string, string> = {
  typed_clinic_3: svgUrl(typedClinic),
  handwritten_2: svgUrl(handwritten),
}

export const FALLBACK_IMAGE = SAMPLE_IMAGES.typed_clinic_3
