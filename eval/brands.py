"""Real Indian brands used to write synthetic prescriptions, with their compositions.

`composition_key` follows the catalog rule (DECISIONS.md #7): salts lowercased, sorted by
name, joined as "name strength + name strength". Once the catalog is loaded,
`eval/sync_truth.py` re-derives each truth key from the `skus` table, so small spelling
differences between this table and the ETL do not count as eval misses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Brand:
    written: str  # name as a doctor writes it, e.g. "Augmentin 625 Duo"
    drug: str  # truth drug field, e.g. "Augmentin Duo"
    strength: str | None  # truth strength as written, e.g. "625"
    form: str  # tablet | capsule | syrup | ...
    salts: tuple[tuple[str, str], ...]
    chronic: bool = False  # long courses (x 1 month) instead of 3-10 days
    prn_ok: bool = False  # may be written SOS

    @property
    def composition_key(self) -> str:
        return composition_key(self.salts)


def composition_key(salts) -> str:
    return " + ".join(f"{name} {strength}" for name, strength in sorted(salts))


BRANDS: list[Brand] = [
    Brand(
        "Augmentin 625 Duo",
        "Augmentin Duo",
        "625",
        "tablet",
        (("amoxycillin", "500mg"), ("clavulanic acid", "125mg")),
    ),
    Brand("Clavam 625", "Clavam", "625", "tablet", (("amoxycillin", "500mg"), ("clavulanic acid", "125mg"))),
    Brand("Mox 500", "Mox", "500", "capsule", (("amoxycillin", "500mg"),)),
    Brand("Azithral 500", "Azithral", "500", "tablet", (("azithromycin", "500mg"),)),
    Brand("Zifi 200", "Zifi", "200", "tablet", (("cefixime", "200mg"),)),
    Brand("Taxim-O 200", "Taxim-O", "200", "tablet", (("cefixime", "200mg"),)),
    Brand("Ciplox 500", "Ciplox", "500", "tablet", (("ciprofloxacin", "500mg"),)),
    Brand("Metrogyl 400", "Metrogyl", "400", "tablet", (("metronidazole", "400mg"),)),
    Brand("Pan 40", "Pan", "40", "tablet", (("pantoprazole", "40mg"),)),
    Brand("Pantocid 40", "Pantocid", "40", "tablet", (("pantoprazole", "40mg"),)),
    Brand("Pan-D", "Pan-D", None, "capsule", (("domperidone", "30mg"), ("pantoprazole", "40mg"))),
    Brand("Omez 20", "Omez", "20", "capsule", (("omeprazole", "20mg"),)),
    Brand("Dolo 650", "Dolo", "650", "tablet", (("paracetamol", "650mg"),), prn_ok=True),
    Brand("Calpol 500", "Calpol", "500", "tablet", (("paracetamol", "500mg"),), prn_ok=True),
    Brand("Crocin 650", "Crocin", "650", "tablet", (("paracetamol", "650mg"),), prn_ok=True),
    Brand(
        "Combiflam",
        "Combiflam",
        None,
        "tablet",
        (("ibuprofen", "400mg"), ("paracetamol", "325mg")),
        prn_ok=True,
    ),
    Brand(
        "Meftal Spas",
        "Meftal Spas",
        None,
        "tablet",
        (("dicyclomine", "10mg"), ("mefenamic acid", "250mg")),
        prn_ok=True,
    ),
    Brand("Ondem 4", "Ondem", "4", "tablet", (("ondansetron", "4mg"),), prn_ok=True),
    Brand("Allegra 120", "Allegra", "120", "tablet", (("fexofenadine", "120mg"),)),
    Brand("Cetzine 10", "Cetzine", "10", "tablet", (("cetirizine", "10mg"),)),
    Brand("Montair LC", "Montair LC", None, "tablet", (("levocetirizine", "5mg"), ("montelukast", "10mg"))),
    Brand("Telma 40", "Telma", "40", "tablet", (("telmisartan", "40mg"),), chronic=True),
    Brand("Amlong 5", "Amlong", "5", "tablet", (("amlodipine", "5mg"),), chronic=True),
    Brand("Glycomet 500", "Glycomet", "500", "tablet", (("metformin", "500mg"),), chronic=True),
    Brand("Atorva 10", "Atorva", "10", "tablet", (("atorvastatin", "10mg"),), chronic=True),
    Brand("Rosuvas 10", "Rosuvas", "10", "tablet", (("rosuvastatin", "10mg"),), chronic=True),
    Brand("Ecosprin 75", "Ecosprin", "75", "tablet", (("aspirin", "75mg"),), chronic=True),
    Brand("Thyronorm 50", "Thyronorm", "50", "tablet", (("thyroxine", "50mcg"),), chronic=True),
]
