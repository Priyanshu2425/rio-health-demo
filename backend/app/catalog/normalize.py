"""Pure text normalization shared by the catalog ETL and catalog search.

No database, no I/O. Everything here is deterministic so the ETL output is reproducible
and the same folding is applied to stored compositions and to search queries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.contracts import Form, Salt, Schedule

# ---------------------------------------------------------------------------
# Salt names
# ---------------------------------------------------------------------------

SALT_ALIASES: dict[str, str] = {
    # spelling variants -> the spelling the dataset uses most
    "amoxicillin": "amoxycillin",
    "amoxicilin": "amoxycillin",
    "amoxycilin": "amoxycillin",
    "acetaminophen": "paracetamol",
    "paracetamol/acetaminophen": "paracetamol",
    "potassium clavulanate": "clavulanic acid",
    "clavulanate": "clavulanic acid",
    "clavulanate potassium": "clavulanic acid",
    "tazobactum": "tazobactam",
    "clinidipine": "cilnidipine",
    "cephalexin": "cefalexin",
    "cefpodoxime": "cefpodoxime proxetil",
    "albuterol": "salbutamol",
    "beclomethasone": "beclometasone",
    "frusemide": "furosemide",
    "cyclosporine": "ciclosporin",
    "cyclosporin": "ciclosporin",
    "glyburide": "glibenclamide",
    "levothyroxine": "thyroxine",
    "l-thyroxine": "thyroxine",
    "thyroxine sodium": "thyroxine",
    "acetylsalicylic acid": "aspirin",
    "ascorbic acid": "vitamin c",
    "cholecalciferol": "vitamin d3",
    "pyridoxine": "vitamin b6",
    "cyanocobalamin": "vitamin b12",
    "mecobalamin": "methylcobalamin",
    "ors": "oral rehydration salts",
    "oral rehydration salt": "oral rehydration salts",
    "rosuvastatin calcium": "rosuvastatin",
    "atorvastatin calcium": "atorvastatin",
    "metformin hydrochloride": "metformin",
    "metformin hcl": "metformin",
    "pantoprazole sodium": "pantoprazole",
    "esomeprazole magnesium": "esomeprazole",
    "rabeprazole sodium": "rabeprazole",
    "losartan potassium": "losartan",
    "amlodipine besylate": "amlodipine",
    "amlodipine besilate": "amlodipine",
    "clopidogrel bisulphate": "clopidogrel",
    "clopidogrel bisulfate": "clopidogrel",
    "sertraline hydrochloride": "sertraline",
    "ondansetron hydrochloride": "ondansetron",
    "cetirizine hydrochloride": "cetirizine",
    "levocetirizine dihydrochloride": "levocetirizine",
    "montelukast sodium": "montelukast",
    "diclofenac sodium": "diclofenac",
    "diclofenac potassium": "diclofenac",
}

_PARENS = re.compile(r"\s*\([^()]*\)")
_SPACES = re.compile(r"\s+")


def normalize_salt_name(raw: str) -> str:
    """'Vitamin B6 (Pyridoxine)' -> 'vitamin b6'; 'Amoxicillin' -> 'amoxycillin'."""
    name = _SPACES.sub(" ", _PARENS.sub("", raw.lower())).strip(" ,.;")
    if not name:
        # the whole thing was parenthesised; keep the inside instead
        name = _SPACES.sub(" ", raw.lower().replace("(", " ").replace(")", " ")).strip(" ,.;")
    return SALT_ALIASES.get(name, name)


# ---------------------------------------------------------------------------
# Strengths
# ---------------------------------------------------------------------------

_GRAMS = re.compile(r"^(\d+(?:\.\d+)?)(?:gm|g)$")


def _fmt_number(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def normalize_strength(raw: str | None) -> str | None:
    """'500 mg' -> '500mg', '5mg/5ml' kept, '1gm' -> '1000mg', 'NA' -> None."""
    if raw is None:
        return None
    text = _SPACES.sub("", raw.lower()).strip(" ,.;")
    if text in {"", "na", "n/a", "nil", "none"}:
        return None
    grams = _GRAMS.match(text)
    if grams:
        return _fmt_number(float(grams.group(1)) * 1000) + "mg"
    # '500.0mg' -> '500mg', '0.50%w/w' -> '0.5%w/w'
    return re.sub(r"\d+\.\d+", lambda m: _fmt_number(float(m.group(0))), text)


# ---------------------------------------------------------------------------
# Compositions
# ---------------------------------------------------------------------------

# 'Amoxycillin  (500mg)' or 'Vitamin B6 (Pyridoxine) (10mg)': strength is the last group
_PART = re.compile(r"^(?P<name>.*?)\s*\((?P<strength>[^()]*)\)\s*$")


def parse_salt(part: str) -> Salt | None:
    part = part.strip(" ,;+")
    if not part:
        return None
    match = _PART.match(part)
    if match and match.group("name").strip():
        name, strength = match.group("name"), match.group("strength")
        # 'Vitamin B6 (Pyridoxine)' with no strength group: the parens were part of the name
        if not re.search(r"\d", strength) and strength.strip().lower() not in {"na", "n/a", ""}:
            name, strength = part, None
    else:
        name, strength = part, None
    salt_name = normalize_salt_name(name)
    if not salt_name:
        return None
    return Salt(name=salt_name, strength=normalize_strength(strength))


def parse_composition(*parts: str | None) -> list[Salt]:
    """Parse one or more composition strings into salts, sorted by name, deduplicated.

    Each part may itself hold several salts joined with '+', e.g.
    'Amoxycillin (500mg) + Clavulanic Acid (125mg)'.
    """
    salts: dict[tuple[str, str | None], Salt] = {}
    for part in parts:
        if part is None or (isinstance(part, float)):  # pandas NaN
            continue
        for piece in str(part).split("+"):
            salt = parse_salt(piece)
            if salt is not None:
                salts[(salt.name, salt.strength)] = salt
    return sorted(salts.values(), key=lambda s: (s.name, s.strength or ""))


def composition_key(salts: list[Salt]) -> str:
    """Canonical 'name strength + name strength', sorted by salt name."""
    ordered = sorted(salts, key=lambda s: (s.name, s.strength or ""))
    return " + ".join(f"{s.name} {s.strength}" if s.strength else s.name for s in ordered)


# ---------------------------------------------------------------------------
# Packs and forms
# ---------------------------------------------------------------------------

# Checked in order: the first keyword found in the pack label decides the form.
_FORM_RULES: list[tuple[str, Form]] = [
    ("injection", "injection"),
    ("infusion", "injection"),
    ("prefilled syringe", "injection"),
    ("pre-filled pen", "injection"),
    ("cartridge", "injection"),
    ("respule", "inhaler"),
    ("rotacap", "inhaler"),
    ("respicap", "inhaler"),
    ("transhaler", "inhaler"),
    ("inhaler", "inhaler"),
    ("for inhalation", "inhaler"),
    ("nasal spray", "other"),
    ("mdi", "inhaler"),
    ("eye ointment", "ointment"),
    ("ointment", "ointment"),
    ("drop", "drops"),
    ("ophthalmic solution", "drops"),
    ("opthalmic solution", "drops"),
    ("ophthalmic suspension", "drops"),
    ("opthalmic suspension", "drops"),
    ("tablet", "tablet"),
    ("capsule", "capsule"),
    ("transcaps", "capsule"),
    ("dry syrup", "syrup"),
    ("powder for oral suspension", "suspension"),
    ("suspension", "suspension"),
    ("syrup", "syrup"),
    ("expectorant", "syrup"),
    ("linctus", "syrup"),
    ("oral solution", "syrup"),
    ("oral liquid", "syrup"),
    ("liquid", "syrup"),
    ("cream", "cream"),
    ("gel", "gel"),
    ("sachet", "sachet"),
    ("granules", "sachet"),
    ("powder", "powder"),
    ("lotion", "other"),
    ("spray", "other"),
    ("mouth wash", "other"),
    ("gargle", "other"),
    ("suppositor", "other"),
    ("pessar", "other"),
    ("patch", "other"),
    ("lozenge", "other"),
    ("disintegrating strip", "other"),
]

_PACK = re.compile(r"^(?P<container>[a-z\- ]+?) of (?P<num>\d+(?:\.\d+)?)\s*(?P<rest>.*)$")
_MEASURE_UNITS = {"ml", "gm", "g", "mg", "mcg", "kg", "l", "ltr", "mdi"}


@dataclass(frozen=True)
class Pack:
    form: Form
    pack_size: int
    pack_label: str


def map_form(label: str) -> Form | None:
    text = label.lower()
    for keyword, form in _FORM_RULES:
        if keyword in text:
            return form
    return None


# Forms dispensed whole: one bottle / tube / inhaler / sachet per pack (contracts-v2).
# Forms whose packs are counted in units (contracts-v2: "countable units per pack").
_COUNTED_FORMS: set[str] = {"tablet", "capsule", "injection"}
# Other packs that hold countable units: inhalation capsules and single-dose ampoules,
# and the countable "other" forms. Everything else (bottles, tubes, sachets, sprays,
# lotions, metered-dose inhaler devices) is one unit per pack.
_COUNTED_KEYWORDS = (
    "rotacap",
    "respicap",
    "respule",
    "transcap",
    "suppositor",
    "pessar",
    "patch",
    "lozenge",
    "disintegrating strip",
)


def parse_pack(raw: str | None) -> Pack | None:
    """Map a pack label to form, pack size (countable units) and label.

    Tablets, capsules, vials/ampoules, rotacaps, respicaps, respules, suppositories,
    patches and lozenges count units ('strip of 30 rotacaps' -> 30). A volume, weight or
    metered-dose count means one container ('bottle of 100 ml syrup' -> 1, 'packet of
    200 mdi inhaler' -> 1), as do bottles, tubes, sachets and inhaler devices.
    Returns None when the label can't be mapped; the ETL drops those rows.
    """
    if raw is None or isinstance(raw, float):
        return None
    label = _SPACES.sub(" ", raw.strip().lower())
    form = map_form(label)
    match = _PACK.match(label)
    if form is None or match is None:
        return None
    number = float(match.group("num"))
    first_word = (match.group("rest").split(" ", 1)[0] if match.group("rest") else "").strip()
    counted = form in _COUNTED_FORMS or any(k in label for k in _COUNTED_KEYWORDS)
    if first_word in _MEASURE_UNITS or not counted:
        pack_size = 1
    else:
        if number < 1 or number != int(number):
            return None
        pack_size = int(number)
    return Pack(form=form, pack_size=pack_size, pack_label=tidy_pack_label(label))


# The dataset abbreviates tablet/capsule modifiers after the noun ('strip of 15 capsule
# pr'). Spelled out and moved in front: 'strip of 15 prolonged-release capsules'.
PACK_MODIFIERS = {
    "sr": "sustained-release",
    "er": "extended-release",
    "xr": "extended-release",
    "xl": "extended-release",
    "pr": "prolonged-release",
    "cr": "controlled-release",
    "mr": "modified-release",
    "dr": "delayed-release",
    "ir": "immediate-release",
    "tr": "timed-release",
    "dt": "dispersible",
    "md": "mouth-dissolving",
    "vt": "vaginal",
}
_UNIT_LABEL = re.compile(
    r"^(?P<head>.+? of (?P<num>\d+(?:\.\d+)?) )(?P<pre>(?:[a-z\-]+ )*?)"
    r"(?P<unit>tablet|capsule)s?(?: (?P<mod>[a-z]+))?$"
)


def tidy_pack_label(label: str) -> str:
    """Readable tablet/capsule pack labels, idempotent on its own output.

    'strip of 10 tablet er' -> 'strip of 10 extended-release tablets',
    'strip of 10 tablet dt' -> 'strip of 10 dispersible tablets', 'strip of 10 capsule'
    -> 'strip of 10 capsules', 'strip of 1 tablets' -> 'strip of 1 tablet'. An unknown
    trailing word is kept in brackets ('strip of 3 tablets (combikit)'). Other labels
    are returned unchanged.
    """
    m = _UNIT_LABEL.match(label)
    if m is None:
        return label
    unit = m.group("unit") + ("" if float(m.group("num")) == 1 else "s")
    mod = m.group("mod")
    before = PACK_MODIFIERS.get(mod, "") if mod else ""
    after = f" ({mod})" if mod and mod not in PACK_MODIFIERS else ""
    prefix = f"{before} " if before and before not in m.group("pre").split() else ""
    return f"{m.group('head')}{m.group('pre')}{prefix}{unit}{after}"


# ---------------------------------------------------------------------------
# Brand names
# ---------------------------------------------------------------------------

_FORM_WORDS = (
    r"tablets?|capsules?|caps|syrup|dry syrup|oral|suspension|injections?|infusion|cream|ointment|"
    r"gel|drops?|eye|ear|nasal|inhaler|powder|sachet|granules|lotion|solution|respules?|rotacaps?|"
    r"respicaps?|transcaps|expectorant|linctus|liquid|spray|vaginal|soft gelatin|chewable|"
    r"effervescent|sublingual|mouth ?wash|gargle|dusting|prefilled|transdermal|suppository|"
    r"pessary|lozenges?|shampoo|soap|kit|infusion|mdi|vial|ampoule|ophthalmic|opthalmic"
)
_FORM_TAIL = re.compile(rf"\s+\b(?:{_FORM_WORDS})\b.*$", re.IGNORECASE)


def clean_brand(name: str) -> str:
    """'Augmentin 625 Duo Tablet' -> 'Augmentin 625 Duo'; 'Pan Mps Oral Suspension' -> 'Pan Mps'."""
    text = _SPACES.sub(" ", name).strip()
    cut = _FORM_TAIL.sub("", text).strip(" -,")
    return cut or text


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

_SCHEDULE_RANK: dict[str, int] = {"H": 1, "H1": 2, "X": 3}


def schedule_for(salts: list[Salt], schedule_map: dict[str, Schedule]) -> Schedule | None:
    """Strictest schedule of any salt. An entry 'metoprolol' also covers 'metoprolol succinate'."""
    best: Schedule | None = None
    for salt in salts:
        found = schedule_map.get(salt.name)
        if found is None:
            for entry, sched in schedule_map.items():
                if salt.name.startswith(entry + " "):
                    found = sched
                    break
        if found is not None and (best is None or _SCHEDULE_RANK[found] > _SCHEDULE_RANK[best]):
            best = found
    return best


# ---------------------------------------------------------------------------
# Search queries
# ---------------------------------------------------------------------------

_QUERY_ALIAS = re.compile(
    r"\b(" + "|".join(re.escape(v) for v in sorted(SALT_ALIASES, key=len, reverse=True)) + r")\b"
)


def normalize_query(query: str) -> str:
    """Lowercase, fold salt spelling variants, split '500/125' into '500 125'."""
    text = query.lower()
    text = re.sub(r"(?<=\d)\s*/\s*(?=\d)", " ", text)
    text = re.sub(r"[^\w%./+\- ]", " ", text)
    text = _SPACES.sub(" ", text).strip()

    def fold(match: re.Match[str]) -> str:
        canonical = SALT_ALIASES[match.group(1)]
        # 'cefpodoxime proxetil' is already canonical; don't expand it twice
        if text.startswith(canonical, match.start()):
            return match.group(1)
        return canonical

    return _QUERY_ALIAS.sub(fold, text)
