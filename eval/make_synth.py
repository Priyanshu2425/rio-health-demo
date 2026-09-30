"""Render synthetic Indian prescriptions and degrade them to look like phone photos.

    cd backend && uv run python ../eval/make_synth.py            # eval/synth/s01..s20
    cd backend && uv run python ../eval/make_synth.py --samples  # eval/samples/ (then load_samples.py)

Four layouts (clinic letterhead, hospital OPD table, handwritten on a pad, minimal typed
with clinical notes as distractors), several fonts including handwriting-style ones, 2-5
medicine lines drawn from `brands.py`. Each image is degraded with rotation, perspective
warp, blur, uneven lighting, noise and JPEG compression. The truth file is written at
generation time. Output is deterministic for a given --seed (fonts come from macOS; on
another OS missing fonts fall back to Pillow's default font).
"""

from __future__ import annotations

import argparse
import io
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from brands import BRANDS, Brand
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SYNTH_DIR = ROOT / "eval" / "synth"
SAMPLES_DIR = ROOT / "eval" / "samples"  # ETL input for the samples table

W, H = 1240, 1754  # A4 at 150 dpi

FONT_DIRS = [
    Path("/System/Library/Fonts/Supplemental"),
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
]
PRINT_FONTS = {
    "arial": "Arial.ttf",
    "arial_bold": "Arial Bold.ttf",
    "georgia": "Georgia.ttf",
    "georgia_bold": "Georgia Bold.ttf",
    "times": "Times New Roman.ttf",
    "times_bold": "Times New Roman Bold.ttf",
    "verdana": "Verdana.ttf",
    "verdana_bold": "Verdana Bold.ttf",
    "courier": "Courier New.ttf",
    "trebuchet": "Trebuchet MS.ttf",
    "trebuchet_bold": "Trebuchet MS Bold.ttf",
    "tahoma": "Tahoma.ttf",
}
HAND_FONTS = {
    "bradley": "Bradley Hand Bold.ttf",
    "noteworthy": "Noteworthy.ttc",
    "marker": "MarkerFelt.ttc",
    "chalkboard": "Chalkboard.ttc",
    "comic": "Comic Sans MS.ttf",
}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    filename = PRINT_FONTS.get(name) or HAND_FONTS[name]
    for d in FONT_DIRS:
        if (d / filename).exists():
            return ImageFont.truetype(str(d / filename), size)
    return ImageFont.load_default(size)


def fit_font(name: str, size: int, text: str, max_width: int) -> ImageFont.FreeTypeFont:
    """The largest font <= size whose rendering of `text` fits in max_width."""
    f = font(name, size)
    while size > 18 and f.getlength(text) > max_width:
        size -= 2
        f = font(name, size)
    return f


DOCTORS = [
    ("Dr. Anil Mehta", "MBBS, MD (Medicine)", "Consultant Physician"),
    ("Dr. Kavita Rao", "MBBS, DNB (Family Medicine)", "Family Physician"),
    ("Dr. Suresh Iyer", "MBBS, MD (Paediatrics)", "Child Specialist"),
    ("Dr. Farah Siddiqui", "MBBS, MS (ENT)", "ENT Surgeon"),
    ("Dr. Rajiv Malhotra", "MBBS, MD, DM (Cardiology)", "Cardiologist"),
    ("Dr. Neha Kulkarni", "MBBS, MD (General Medicine)", "Diabetologist"),
    ("Dr. Arjun Nair", "MBBS, MD (Pulmonology)", "Chest Physician"),
    ("Dr. Pooja Bansal", "MBBS, DGO", "Gynaecologist"),
]
CLINICS = [
    "Sunrise Clinic",
    "Shree Sai Polyclinic",
    "Arogya Health Centre",
    "LifeCare Family Clinic",
    "Sanjeevani Medical Centre",
    "Green Park Clinic",
    "City Care Multispeciality Hospital",
    "Apex Heart & Diabetes Clinic",
]
AREAS = [
    "12, MG Road, Indiranagar, Bengaluru - 560038",
    "Shop 4, Sector 18 Market, Noida - 201301",
    "221 Linking Road, Bandra West, Mumbai - 400050",
    "45 Anna Salai, Teynampet, Chennai - 600018",
    "B-7, Lajpat Nagar II, New Delhi - 110024",
    "3rd Floor, FC Road, Shivajinagar, Pune - 411005",
]
PATIENTS = [
    "Rahul Sharma",
    "Priya Verma",
    "Mohd. Imran",
    "Sneha Patil",
    "Vikram Singh",
    "Anjali Gupta",
    "Ramesh Kumar",
    "Lakshmi Narayanan",
    "Deepak Joshi",
    "Fatima Shaikh",
    "Karan Kapoor",
    "Meera Pillai",
]
DIAGNOSES = [
    "Acute pharyngitis",
    "Viral fever",
    "URTI",
    "Acute gastritis",
    "Allergic rhinitis",
    "HTN, T2DM - follow up",
    "LRTI",
    "Acute gastroenteritis",
    "Dyslipidemia",
    "Sinusitis",
]
COMPLAINTS = [
    "fever, body ache x 2 days",
    "cough, cold x 4 days",
    "acidity, bloating",
    "sore throat x 3 days",
]
ADVICE = [
    "Plenty of oral fluids",
    "Review after 5 days",
    "Steam inhalation twice daily",
    "Avoid oily & spicy food",
    "Salt restriction, daily walk",
    "Review with CBC report",
]

ACUTE_FREQ = [("1-0-1", 2), ("1-1-1", 3), ("1-0-0", 1), ("0-0-1", 1), ("BD", 2), ("TDS", 3), ("OD", 1)]
CHRONIC_FREQ = [("1-0-0", 1), ("0-0-1", 1), ("OD", 1), ("1-0-1", 2), ("BD", 2), ("HS", 1)]
ACUTE_DUR = [
    ("x 5 days", 5),
    ("x 3 days", 3),
    ("5/7", 5),
    ("3/7", 3),
    ("x 7 days", 7),
    ("x 1 week", 7),
    ("x 10 days", 10),
    ("5d", 5),
    ("for 5 days", 5),
]
CHRONIC_DUR = [("x 1 month", 30), ("x 30 days", 30), ("1/12", 30), ("x 15 days", 15), ("2/52", 14)]
INSTRUCTIONS = ["after food", "before food", "A/F", "B/F", "", "", "empty stomach"]
PREFIX = {"tablet": ["Tab.", "Tab", "T."], "capsule": ["Cap.", "Cap"], "syrup": ["Syp.", "Syr."]}


@dataclass
class RxItem:
    brand: Brand
    prefix: str
    frequency: str
    doses_per_day: float | None
    duration: str | None
    duration_days: int | None
    instruction: str
    quantity: int | None = None  # explicit count in tablets/capsules, written as "#N"

    @property
    def med(self) -> str:
        count = f" #{self.quantity}" if self.quantity else ""
        return f"{self.prefix} {self.brand.written}{count}"

    @property
    def text(self) -> str:
        parts = [self.med, self.frequency]
        if self.duration:
            parts.append(self.duration)
        if self.instruction:
            parts.append(f"({self.instruction})")
        return "  ".join(parts)

    def truth(self) -> dict:
        return {
            "drug": self.brand.drug,
            "strength": self.brand.strength,
            "doses_per_day": self.doses_per_day,
            "duration_days": self.duration_days,
            "quantity": self.quantity,
            "composition_key": self.brand.composition_key,
            "raw_text": self.text,
        }


def pick_items(rng: random.Random, n: int, names: list[str] | None = None) -> list[RxItem]:
    """n brands with no salt in common (no doctor writes Dolo and Calpol together)."""
    if names:
        chosen = [next(b for b in BRANDS if b.written == name) for name in names]
    else:
        pool = BRANDS[:]
        rng.shuffle(pool)
        chosen = []
        salts: set[str] = set()
        for b in pool:
            names_here = {s for s, _ in b.salts}
            if not names_here & salts:
                chosen.append(b)
                salts |= names_here
            if len(chosen) == n:
                break
    items = []
    for b in chosen:
        if b.prn_ok and rng.random() < 0.35:
            freq, dpd = "SOS", None
            dur, days = rng.choice([("x 3 days", 3), (None, None)])
        else:
            freq, dpd = rng.choice(CHRONIC_FREQ if b.chronic else ACUTE_FREQ)
            dur, days = rng.choice(CHRONIC_DUR if b.chronic else ACUTE_DUR)
        item = RxItem(b, rng.choice(PREFIX[b.form]), freq, dpd, dur, days, rng.choice(INSTRUCTIONS))
        if not names and rng.random() < 0.15:
            item.quantity = int(dpd * days) if dpd and days else 10
        items.append(item)
    return items


@dataclass
class Header:
    doctor: str
    degrees: str
    title: str
    clinic: str
    address: str
    patient: str
    age_sex: str
    date: str
    reg_no: str
    phone: str


def make_header(rng: random.Random) -> Header:
    doctor, degrees, title = rng.choice(DOCTORS)
    return Header(
        doctor=doctor,
        degrees=degrees,
        title=title,
        clinic=rng.choice(CLINICS),
        address=rng.choice(AREAS),
        patient=rng.choice(PATIENTS),
        age_sex=f"{rng.randint(18, 72)}/{rng.choice(['M', 'F'])}",
        date=f"{rng.randint(1, 28):02d}/{rng.randint(1, 9):02d}/2026",
        reg_no=f"Reg. No. {rng.choice(['KMC', 'MMC', 'DMC', 'TNMC'])}-{rng.randint(10000, 99999)}",
        phone=f"+91 {rng.randint(70000, 99999)} {rng.randint(10000, 99999)}",
    )


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------


def paper(rng: random.Random) -> Image.Image:
    tone = rng.randint(244, 255)
    return Image.new("RGB", (W, H), (tone, tone, max(tone - rng.randint(0, 8), 232)))


def draw_rx_symbol(d: ImageDraw.ImageDraw, xy: tuple[int, int], f: ImageFont.FreeTypeFont, fill) -> None:
    d.text(xy, "Rx", font=f, fill=fill)


def hand_text(img: Image.Image, xy: tuple[int, int], text: str, f, rng: random.Random, ink, strike=False):
    """Draw text on its own layer with a small rotation and per-word baseline jitter."""
    x0, y0 = xy
    d = ImageDraw.Draw(img)
    tmp = Image.new("RGBA", (W, 160), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    x = 10
    for word in text.split(" "):
        if not word:
            x += int(f.size * 0.3)
            continue
        td.text((x, 40 + rng.randint(-4, 4)), word, font=f, fill=ink)
        x += int(td.textlength(word + " ", font=f)) + rng.randint(-2, 4)
    if strike:
        td.line((10, 40 + f.size * 0.6, x, 40 + f.size * 0.55), fill=ink, width=4)
    tmp = tmp.rotate(rng.uniform(-1.8, 1.8), resample=Image.Resampling.BICUBIC, center=(0, 80))
    img.paste(tmp, (x0 - 10, y0 - 40), tmp)
    del d


def layout_letterhead(rng: random.Random, hd: Header, items: list[RxItem]) -> Image.Image:
    img = paper(rng)
    d = ImageDraw.Draw(img)
    color = rng.choice([(16, 94, 120), (30, 50, 110), (128, 28, 40), (20, 110, 70)])
    body_font = rng.choice(["arial", "georgia", "verdana", "trebuchet"])
    d.rectangle((0, 0, W, 230), fill=color)
    d.text(
        (70, 40),
        hd.clinic,
        font=font(body_font + "_bold" if body_font != "arial" else "arial_bold", 58),
        fill="white",
    )
    d.text((70, 120), f"{hd.doctor}, {hd.degrees}", font=font(body_font, 32), fill="white")
    d.text((70, 165), f"{hd.title}  |  {hd.reg_no}", font=font(body_font, 26), fill=(225, 235, 240))
    d.text((70, 250), f"{hd.address}   Ph: {hd.phone}", font=font(body_font, 24), fill=(70, 70, 70))
    d.line((60, 300, W - 60, 300), fill=color, width=3)
    f = font(body_font, 30)
    d.text((70, 330), f"Patient: {hd.patient}", font=f, fill=(30, 30, 30))
    d.text((640, 330), f"Age/Sex: {hd.age_sex}", font=f, fill=(30, 30, 30))
    d.text((940, 330), f"Date: {hd.date}", font=f, fill=(30, 30, 30))
    if rng.random() < 0.6:
        d.text((70, 390), f"Dx: {rng.choice(DIAGNOSES)}", font=f, fill=(30, 30, 30))
    draw_rx_symbol(d, (70, 460), font("times_bold", 80), color)
    y = 580
    mf = font(body_font, 34)
    for i, it in enumerate(items, start=1):
        d.text((90, y), f"{i}.  {it.med}", font=mf, fill=(20, 20, 20))
        d.text((600, y), it.frequency, font=mf, fill=(20, 20, 20))
        if it.duration:
            d.text((800, y), it.duration, font=mf, fill=(20, 20, 20))
        if it.instruction:
            d.text((130, y + 46), f"({it.instruction})", font=font(body_font, 26), fill=(80, 80, 80))
        y += 120
    d.text((70, y + 40), f"Advice: {rng.choice(ADVICE)}", font=f, fill=(40, 40, 40))
    hand_text(img, (820, H - 300), hd.doctor.replace("Dr. ", "")[:12], font("bradley", 48), rng, (20, 30, 90))
    d.text((820, H - 220), hd.doctor, font=font(body_font, 26), fill=(40, 40, 40))
    d.rectangle((0, H - 90, W, H), fill=color)
    d.text(
        (70, H - 65),
        "Mon-Sat 10 am - 1 pm, 6 pm - 9 pm  |  Sunday closed",
        font=font(body_font, 24),
        fill="white",
    )
    return img


def layout_opd_table(rng: random.Random, hd: Header, items: list[RxItem]) -> Image.Image:
    img = paper(rng)
    d = ImageDraw.Draw(img)
    face = rng.choice(["times", "georgia", "tahoma"])
    bold = {"times": "times_bold", "georgia": "georgia_bold", "tahoma": "arial_bold"}[face]
    title = "City Care Multispeciality Hospital"
    tf = font(bold, 52)
    d.text(((W - d.textlength(title, font=tf)) / 2, 50), title, font=tf, fill=(10, 10, 10))
    sub = "Department of General Medicine - OPD Prescription"
    sf = font(face, 30)
    d.text(((W - d.textlength(sub, font=sf)) / 2, 125), sub, font=sf, fill=(40, 40, 40))
    d.rectangle((60, 190, W - 60, 330), outline=(0, 0, 0), width=2)
    f = font(face, 28)
    d.text((80, 205), f"UHID: CC{rng.randint(100000, 999999)}", font=f, fill=(0, 0, 0))
    d.text((640, 205), f"Date: {hd.date}", font=f, fill=(0, 0, 0))
    d.text((80, 250), f"Patient Name: {hd.patient}", font=f, fill=(0, 0, 0))
    d.text((640, 250), f"Age/Sex: {hd.age_sex}", font=f, fill=(0, 0, 0))
    d.text((80, 290), f"Consultant: {hd.doctor} ({hd.title})", font=f, fill=(0, 0, 0))
    d.text((60, 360), f"Diagnosis: {rng.choice(DIAGNOSES)}", font=f, fill=(0, 0, 0))
    cols = [60, 140, 620, 800, 1000, W - 60]
    heads = ["No.", "Medicine", "Dose", "Frequency", "Duration"]
    top = 430
    row_h = 90
    n_rows = len(items) + 1
    for i in range(n_rows + 1):
        d.line((cols[0], top + i * row_h, cols[-1], top + i * row_h), fill=(0, 0, 0), width=2)
    for x in cols:
        d.line((x, top, x, top + n_rows * row_h), fill=(0, 0, 0), width=2)
    hf = font(bold, 28)
    for x, h in zip(cols, heads, strict=False):
        d.text((x + 12, top + 28), h, font=hf, fill=(0, 0, 0))
    cf = font(face, 28)
    for r, it in enumerate(items, start=1):
        y = top + r * row_h + 28
        d.text((cols[0] + 20, y), str(r), font=cf, fill=(0, 0, 0))
        d.text((cols[1] + 12, y), it.med, font=cf, fill=(0, 0, 0))
        d.text((cols[2] + 12, y), "1 cap" if it.brand.form == "capsule" else "1 tab", font=cf, fill=(0, 0, 0))
        d.text((cols[3] + 12, y), it.frequency, font=cf, fill=(0, 0, 0))
        dur = it.duration.replace("x ", "") if it.duration else "-"
        d.text((cols[4] + 12, y), dur, font=cf, fill=(0, 0, 0))
    y = top + n_rows * row_h + 40
    notes = [f"{r}: {it.instruction}" for r, it in enumerate(items, start=1) if it.instruction]
    d.text((60, y), f"Instructions: {'; '.join(notes) or 'as advised'}", font=f, fill=(0, 0, 0))
    d.text((60, y + 50), f"Follow up: {rng.choice(ADVICE)}", font=f, fill=(0, 0, 0))
    hand_text(img, (860, H - 260), hd.doctor.split()[-1], font("noteworthy", 50), rng, (10, 10, 60))
    d.text((860, H - 180), "Signature of Consultant", font=font(face, 24), fill=(0, 0, 0))
    return img


def layout_handwritten(rng: random.Random, hd: Header, items: list[RxItem], hand: str) -> Image.Image:
    img = paper(rng)
    d = ImageDraw.Draw(img)
    face = rng.choice(["times", "georgia"])
    d.text((70, 50), hd.doctor, font=font(face + "_bold", 46), fill=(20, 40, 100))
    d.text((70, 110), hd.degrees, font=font(face, 28), fill=(20, 40, 100))
    d.text((70, 150), hd.reg_no, font=font(face, 24), fill=(20, 40, 100))
    d.text((720, 60), hd.clinic, font=font(face + "_bold", 32), fill=(20, 40, 100))
    d.text((720, 105), hd.address[:40], font=font(face, 22), fill=(20, 40, 100))
    d.text((720, 135), f"Ph: {hd.phone}", font=font(face, 22), fill=(20, 40, 100))
    d.line((60, 200, W - 60, 200), fill=(20, 40, 100), width=3)
    ink = rng.choice([(20, 30, 120), (15, 15, 25), (30, 40, 150)])
    hf = font(hand, 44 if hand != "marker" else 48)
    hand_text(img, (80, 240), f"Name: {hd.patient}   {hd.age_sex}", hf, rng, ink)
    hand_text(img, (900, 240), hd.date, hf, rng, ink)
    if rng.random() < 0.5:
        hand_text(img, (80, 320), f"C/O {rng.choice(COMPLAINTS)}", font(hand, 38), rng, ink)
    hand_text(img, (80, 410), "Rx", font(hand, 72), rng, ink)
    y = 520
    strike_at = rng.randrange(len(items) + 1) if rng.random() < 0.4 else None
    for i, it in enumerate(items, start=1):
        if strike_at == i - 1:
            wrong = rng.choice([b for b in BRANDS if b not in [x.brand for x in items]])
            hand_text(img, (110, y), f"Tab {wrong.written} 1-0-1", hf, rng, ink, strike=True)
            y += 100
        text = f"{i}) {it.text}"
        hand_text(img, (110, y), text, fit_font(hand, hf.size, text, W - 200), rng, ink)
        y += 110 + rng.randint(-10, 20)
    hand_text(img, (110, y + 30), f"Adv: {rng.choice(ADVICE)}", font(hand, 38), rng, ink)
    hand_text(img, (860, H - 260), hd.doctor.split()[-1], font(hand, 56), rng, ink)
    return img


def layout_minimal(rng: random.Random, hd: Header, items: list[RxItem]) -> Image.Image:
    img = paper(rng)
    d = ImageDraw.Draw(img)
    face = rng.choice(["courier", "georgia", "verdana"])
    big = font(face, 44)
    t = hd.clinic.upper()
    d.text(((W - d.textlength(t, font=big)) / 2, 60), t, font=big, fill=(0, 0, 0))
    small = font(face, 26)
    line2 = f"{hd.doctor}, {hd.degrees}"
    d.text(((W - d.textlength(line2, font=small)) / 2, 125), line2, font=small, fill=(0, 0, 0))
    d.text(((W - d.textlength(hd.address, font=small)) / 2, 165), hd.address, font=small, fill=(0, 0, 0))
    d.line((80, 215, W - 80, 215), fill=(0, 0, 0), width=2)
    f = font(face, 30)
    d.text((90, 240), f"{hd.patient}, {hd.age_sex}", font=f, fill=(0, 0, 0))
    d.text((930, 240), hd.date, font=f, fill=(0, 0, 0))
    d.text((90, 310), f"C/O: {rng.choice(COMPLAINTS)}", font=f, fill=(0, 0, 0))
    d.text(
        (90, 360),
        f"O/E: BP {rng.randint(110, 150)}/{rng.randint(70, 95)} mmHg, "
        f"Temp {rng.choice(['98.6', '100.2', '101.4'])} F, SpO2 {rng.randint(95, 99)}%",
        font=f,
        fill=(0, 0, 0),
    )
    draw_rx_symbol(d, (90, 440), font("times_bold", 70), (0, 0, 0))
    y = 550
    for i, it in enumerate(items, start=1):
        text = f"{i}) {it.text}"
        d.text((110, y), text, font=fit_font(face, 30, text, W - 180), fill=(0, 0, 0))
        y += 80
    d.text((90, y + 40), f"Adv: {rng.choice(ADVICE)}", font=f, fill=(0, 0, 0))
    d.text(
        (90, y + 90),
        f"Inv: {rng.choice(['CBC, CRP', 'HbA1c, lipid profile', 'Chest X-ray PA view'])}",
        font=f,
        fill=(0, 0, 0),
    )
    hand_text(img, (860, H - 240), hd.doctor.split()[-1], font("bradley", 50), rng, (10, 10, 10))
    return img


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


def _perspective_coeffs(src, dst):
    matrix = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.array(matrix, dtype=float)
    b = np.array([c for p in src for c in p], dtype=float)
    return np.linalg.solve(a, b).tolist()


def degrade(img: Image.Image, rng: random.Random, strength: float = 1.0) -> Image.Image:
    # Place the page on a table so the photo has a border, then warp.
    margin = int(W * 0.06)
    table = tuple(rng.randint(60, 140) for _ in range(3))
    canvas = Image.new("RGB", (W + 2 * margin, H + 2 * margin), table)
    canvas.paste(img, (margin, margin))
    cw, ch = canvas.size
    j = 0.035 * strength
    dst = [(0, 0), (cw, 0), (cw, ch), (0, ch)]
    src = [
        (rng.uniform(0, j) * cw, rng.uniform(0, j) * ch),
        (cw - rng.uniform(0, j) * cw, rng.uniform(0, j) * ch),
        (cw - rng.uniform(0, j) * cw, ch - rng.uniform(0, j) * ch),
        (rng.uniform(0, j) * cw, ch - rng.uniform(0, j) * ch),
    ]
    canvas = canvas.transform(
        (cw, ch),
        Image.Transform.PERSPECTIVE,
        _perspective_coeffs(src, dst),
        Image.Resampling.BICUBIC,
        fillcolor=table,
    )
    canvas = canvas.rotate(
        rng.uniform(-4, 4) * strength, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=table
    )

    arr = np.asarray(canvas).astype(np.float32)
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    angle = rng.uniform(0, 2 * math.pi)
    proj = (xx / w - 0.5) * math.cos(angle) + (yy / h - 0.5) * math.sin(angle)
    lo = 1 - rng.uniform(0.18, 0.4) * strength
    light = lo + (1 - lo) * (proj - proj.min()) / (proj.max() - proj.min())
    cx, cy = rng.uniform(0.3, 0.7), rng.uniform(0.3, 0.7)
    vignette = 1 - 0.25 * strength * np.clip(((xx / w - cx) ** 2 + (yy / h - cy) ** 2) * 2.2, 0, 1)
    tint = np.array([1.0, rng.uniform(0.96, 1.0), rng.uniform(0.86, 0.97)], dtype=np.float32)
    arr = arr * (light * vignette)[..., None] * tint
    arr += np.random.default_rng(rng.randint(0, 2**31)).normal(0, rng.uniform(3, 8) * strength, arr.shape)
    canvas = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    canvas = canvas.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.5) * strength))
    canvas.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    return canvas


def to_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


# ---------------------------------------------------------------------------


LAYOUTS = ["letterhead", "opd_table", "handwritten", "minimal"]


def render(rng: random.Random, layout: str, n_lines: int, hand: str = "bradley", names=None):
    hd = make_header(rng)
    items = pick_items(rng, n_lines, names)
    if layout == "letterhead":
        img = layout_letterhead(rng, hd, items)
    elif layout == "opd_table":
        img = layout_opd_table(rng, hd, items)
    elif layout == "handwritten":
        img = layout_handwritten(rng, hd, items, hand)
    else:
        img = layout_minimal(rng, hd, items)
    truth = {
        "lines": [it.truth() for it in items],
        "meta": {
            "layout": layout,
            "hand_font": hand if layout == "handwritten" else None,
            "doctor": hd.doctor,
            "clinic": hd.clinic,
            "patient": hd.patient,
            "date": hd.date,
        },
    }
    return img, truth, hd, items


def make_synth(n: int, seed: int) -> None:
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    hands = ["bradley", "noteworthy", "marker", "chalkboard", "comic"]
    for i in range(1, n + 1):
        layout = LAYOUTS[(i - 1) % len(LAYOUTS)]
        hand = hands[((i - 1) // len(LAYOUTS)) % len(hands)]
        img, truth, _, _ = render(rng, layout, rng.randint(2, 5), hand)
        photo = degrade(img, rng)
        (SYNTH_DIR / f"s{i:02d}.jpg").write_bytes(to_jpeg(photo, rng.randint(40, 70)))
        (SYNTH_DIR / f"s{i:02d}.truth.json").write_text(json.dumps(truth, indent=2) + "\n")
        print(
            f"s{i:02d}: {layout:<12} {len(truth['lines'])} lines  {', '.join(t['drug'] for t in truth['lines'])}"
        )


SAMPLE_SPECS = [
    (
        "typed_clinic_3",
        "Typed clinic Rx, 3 lines",
        "letterhead",
        "bradley",
        ["Augmentin 625 Duo", "Pan 40", "Dolo 650"],
    ),
    (
        "hospital_opd_4",
        "Hospital OPD Rx, 4 lines",
        "opd_table",
        "bradley",
        ["Azithral 500", "Montair LC", "Pan-D", "Calpol 500"],
    ),
    # Replace with one of the owner's handwritten prescriptions once eval/handwritten/ has them.
    (
        "handwritten_style_3",
        "Handwritten-style Rx, 3 lines",
        "handwritten",
        "noteworthy",
        ["Telma 40", "Glycomet 500", "Atorva 10"],
    ),
]


def make_samples(seed: int) -> None:
    """Demo samples: mildly degraded, with a truth-derived cached parse until a live one exists."""
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from app.contracts import ParsedLine, ParsedRx
    from app.parser.normalize import doses_per_day, duration_days, parse_date

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    manifest = []
    for sample_id, label, layout, hand, names in SAMPLE_SPECS:
        img, truth, hd, items = render(rng, layout, len(names), hand, names)
        photo = degrade(img, rng, strength=0.5)
        (SAMPLES_DIR / f"{sample_id}.jpg").write_bytes(to_jpeg(photo, 80))
        lines = [
            ParsedLine(
                line_no=i,
                raw_text=it.text,
                drug=it.brand.drug,
                strength=it.brand.strength,
                form=it.brand.form,
                frequency=it.frequency,
                doses_per_day=doses_per_day(it.frequency),
                duration_days=duration_days(it.duration),
                quantity=it.quantity,
            )
            for i, it in enumerate(items, start=1)
        ]
        parsed = ParsedRx(
            doctor_name=hd.doctor,
            clinic_name=hd.clinic,
            patient_name=hd.patient,
            rx_date=parse_date(hd.date),
            lines=lines,
            model="synthetic-truth",
            latency_ms=0,
            cost_usd=None,
        )
        (SAMPLES_DIR / f"{sample_id}.json").write_text(parsed.model_dump_json(indent=2) + "\n")
        manifest.append(
            {"sample_id": sample_id, "label": label, "image": f"{sample_id}.jpg", "mime": "image/jpeg"}
        )
        print(f"{sample_id}: {', '.join(t['drug'] for t in truth['lines'])}")
    (SAMPLES_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--samples", action="store_true", help="write the demo samples instead of the eval set")
    args = ap.parse_args()
    if args.samples:
        make_samples(args.seed + 1000)
    else:
        make_synth(args.n, args.seed)


if __name__ == "__main__":
    main()
