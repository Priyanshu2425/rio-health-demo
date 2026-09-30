"""Composition, pack and brand parsing. Pure: no database."""

import pytest

from app.catalog.normalize import (
    clean_brand,
    composition_key,
    normalize_query,
    normalize_salt_name,
    normalize_strength,
    parse_composition,
    parse_pack,
    schedule_for,
    tidy_pack_label,
)
from app.catalog.query import pack_amount, same_whole_pack
from app.contracts import SKU, Salt


def test_parses_two_salt_string_into_sorted_salts():
    salts = parse_composition("Clavulanic Acid (125mg) + Amoxycillin  (500 mg)")
    assert salts == [
        Salt(name="amoxycillin", strength="500mg"),
        Salt(name="clavulanic acid", strength="125mg"),
    ]


def test_dataset_columns_and_nan_second_column():
    salts = parse_composition("Azithromycin (500mg)", float("nan"))
    assert salts == [Salt(name="azithromycin", strength="500mg")]


def test_composition_key_is_order_independent():
    a = parse_composition("Amoxycillin (500mg)", "Clavulanic Acid (125mg)")
    b = parse_composition("Clavulanic Acid (125mg) + Amoxicillin (500mg)")
    assert composition_key(a) == composition_key(b) == "amoxycillin 500mg + clavulanic acid 125mg"


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("Amoxicillin", "amoxycillin"),
        ("Acetaminophen", "paracetamol"),
        ("Paracetamol/Acetaminophen", "paracetamol"),
        ("Potassium Clavulanate", "clavulanic acid"),
        ("Vitamin B6 (Pyridoxine)", "vitamin b6"),
        ("  Pantoprazole  ", "pantoprazole"),
        ("Clinidipine", "cilnidipine"),
    ],
)
def test_salt_aliases(raw, name):
    assert normalize_salt_name(raw) == name


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("cefixime", "cefepime"),
        ("clonazepam", "lorazepam"),
        ("dexamethasone", "betamethasone"),
        ("quinidine", "quinine"),
        ("nizatidine", "tizanidine"),
        ("enalaprilat", "enalapril"),
        ("lactose", "lactulose"),
        ("metoprolol succinate", "metoprolol tartrate"),
    ],
)
def test_look_alike_salts_stay_distinct(a, b):
    """Near-identical spellings that are different drugs must never be folded together."""
    assert normalize_salt_name(a) != normalize_salt_name(b)
    assert normalize_query(a) != normalize_query(b)


@pytest.mark.parametrize(
    ("raw", "strength"),
    [
        ("500 mg", "500mg"),
        ("5mg/5ml", "5mg/5ml"),
        ("1gm", "1000mg"),
        ("0.50% w/w", "0.5%w/w"),
        ("NA", None),
        (None, None),
    ],
)
def test_strength_normalization(raw, strength):
    assert normalize_strength(raw) == strength


def test_nested_parentheses_take_last_group_as_strength():
    assert parse_composition("Vitamin B6 (Pyridoxine) (10mg)") == [Salt(name="vitamin b6", strength="10mg")]


def test_missing_strength_gives_name_only_key():
    salts = parse_composition("Oral Rehydration Salts (NA)")
    assert composition_key(salts) == "oral rehydration salts"


@pytest.mark.parametrize(
    ("label", "form", "size"),
    [
        ("strip of 10 tablets", "tablet", 10),
        ("strip of 15 Tablet pr", "tablet", 15),
        ("strip of 10 capsule sr", "capsule", 10),
        ("bottle of 100 ml Syrup", "syrup", 1),
        ("bottle of 60 ml Oral Suspension", "suspension", 1),
        ("vial of 1 Powder for Injection", "injection", 1),
        ("tube of 20 gm Cream", "cream", 1),
        ("bottle of 10 ml Eye Drop", "drops", 1),
        ("packet of 200 MDI Inhaler", "inhaler", 1),
        # inhalation: capsules and ampoules count units, metered-dose devices are one
        ("strip of 30 rotacaps", "inhaler", 30),
        ("bottle of 30 rotacaps", "inhaler", 30),
        ("strip of 15 respicaps", "inhaler", 15),
        ("packet of 5 respules", "inhaler", 5),
        ("box of 20 respules", "inhaler", 20),
        ("packet of 2 ml respules", "inhaler", 1),
        ("box of 120 mdi inhaler", "inhaler", 1),
        ("packet of 1 inhaler", "inhaler", 1),
        ("bottle of 15 ml solution for inhalation", "inhaler", 1),
        # other countable units vs single containers
        ("packet of 5 suppositories", "other", 5),
        ("packet of 10 transdermal patches", "other", 10),
        ("strip of 10 lozenges", "other", 10),
        ("packet of 4 nasal spray", "other", 1),
        ("bottle of 100 ml lotion", "other", 1),
        ("box of 100 gm Powder", "powder", 1),
        ("packet of 5 injections", "injection", 5),
        ("bottle of 30 tablets", "tablet", 30),
        ("sachet of 21.8 g", "sachet", 1),
    ],
)
def test_pack_mapping(label, form, size):
    pack = parse_pack(label)
    assert pack is not None
    assert (pack.form, pack.pack_size) == (form, size)


def test_unmappable_pack_is_dropped():
    assert parse_pack("packet of 1 Kit") is None
    assert parse_pack(None) is None


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("strip of 15 capsule pr", "strip of 15 prolonged-release capsules"),
        ("strip of 10 tablet er", "strip of 10 extended-release tablets"),
        ("strip of 10 tablet dt", "strip of 10 dispersible tablets"),
        ("strip of 10 tablet sr", "strip of 10 sustained-release tablets"),
        ("strip of 1 tablet dt", "strip of 1 dispersible tablet"),
        ("bottle of 30 tablet cr", "bottle of 30 controlled-release tablets"),
        ("packet of 7 tablet vt", "packet of 7 vaginal tablets"),
        ("strip of 10 tablet", "strip of 10 tablets"),
        ("strip of 1 tablet", "strip of 1 tablet"),
        ("strip of 1 tablets", "strip of 1 tablet"),
        ("strip of 4 effervescent tablet", "strip of 4 effervescent tablets"),
        ("strip of 10 soft gelatin capsules", "strip of 10 soft gelatin capsules"),
        ("strip of 3 tablet combikit", "strip of 3 tablets (combikit)"),
        ("bottle of 60 ml syrup", "bottle of 60 ml syrup"),
        ("vial of 1 injection", "vial of 1 injection"),
    ],
)
def test_pack_label_is_readable(raw, label):
    assert tidy_pack_label(raw) == label
    assert tidy_pack_label(label) == label  # idempotent: the seed can be re-tidied


def test_parse_pack_tidies_the_label_but_keeps_form_and_size():
    pack = parse_pack("Strip of 15 Capsule PR")
    assert (pack.form, pack.pack_size, pack.pack_label) == (
        "capsule",
        15,
        "strip of 15 prolonged-release capsules",
    )


@pytest.mark.parametrize(
    ("name", "brand"),
    [
        ("Augmentin 625 Duo Tablet", "Augmentin 625 Duo"),
        ("Glycomet-GP 1 Tablet PR", "Glycomet-GP 1"),
        ("Pan Mps Oral Suspension Mint Sugar Free", "Pan Mps"),
        ("Budecort 0.5mg Respules 2ml", "Budecort 0.5mg"),
    ],
)
def test_clean_brand(name, brand):
    assert clean_brand(name) == brand


def test_schedule_takes_strictest_and_prefix_matches():
    schedules = {"amoxycillin": "H", "tramadol": "H1", "metoprolol": "H"}
    assert schedule_for(parse_composition("Paracetamol (325mg) + Tramadol (37.5mg)"), schedules) == "H1"
    assert schedule_for(parse_composition("Metoprolol Succinate (50mg)"), schedules) == "H"
    assert schedule_for(parse_composition("Paracetamol (650mg)"), schedules) is None


def test_query_normalization():
    assert normalize_query("Amoxicillin Clavulanate 500/125") == "amoxycillin clavulanic acid 500 125"
    assert normalize_query("cefpodoxime proxetil 200") == "cefpodoxime proxetil 200"
    assert normalize_query("  Tab. PAN 40 ") == "tab. pan 40"


@pytest.mark.parametrize(
    ("label", "amount"),
    [
        ("bottle of 15 ml oral suspension", (15.0, "ml")),
        ("packet of 15 ml oral suspension", (15.0, "ml")),
        ("tube of 30 gm gel", (30.0, "gm")),
        ("sachet of 21.8 g", (21.8, "gm")),
        ("packet of 120 mdi inhaler", (120.0, "mdi")),
        ("vial of 1 injection", None),
    ],
)
def test_pack_amount(label, amount):
    assert pack_amount(label) == amount


def _bottle(label: str) -> SKU:
    return SKU(
        sku_id="x",
        brand_name="x",
        manufacturer="x",
        form="suspension",
        pack_size=1,
        pack_label=label,
        mrp_inr=10,
        composition=[],
        composition_key="k",
        rx_only=False,
    )


def test_whole_pack_comparison_needs_equal_volume():
    assert same_whole_pack(
        _bottle("bottle of 15 ml oral suspension"), _bottle("packet of 15 ml oral suspension")
    )
    assert not same_whole_pack(_bottle("bottle of 60 ml oral suspension"), _bottle("bottle of 15 ml syrup"))
    assert same_whole_pack(_bottle("vial of 1 injection"), _bottle("vial of 1 injection"))
    assert not same_whole_pack(_bottle("vial of 1 injection"), _bottle("vial of 1 powder for injection"))
