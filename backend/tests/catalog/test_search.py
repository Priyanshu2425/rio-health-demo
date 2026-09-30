"""Catalog search against the real `skus` table (loaded by scripts/etl/build_catalog.py)."""

import pytest

from app.catalog import cheapest_generic, get_sku, search
from app.catalog.query import pack_amount

pytestmark = pytest.mark.db

AMOX_CLAV = "amoxycillin 500mg + clavulanic acid 125mg"


async def test_brand_search_augmentin_625(conn):
    results = await search(conn, "augmentin 625")
    assert results[0].sku.composition_key == AMOX_CLAV
    assert results[0].sku.form == "tablet"
    assert all(0 <= r.score <= 1 for r in results)
    assert results == sorted(results, key=lambda r: -r.score)


async def test_composition_search_with_spelling_variant(conn):
    results = await search(conn, "amoxicillin clavulanic 500 125", limit=3)
    assert any(r.sku.composition_key == AMOX_CLAV for r in results)


async def test_composition_search_with_slash_strengths(conn):
    results = await search(conn, "amoxicillin clavulanate 500/125", limit=3)
    assert results[0].sku.composition_key == AMOX_CLAV


async def test_pan_40_is_pantoprazole_40(conn):
    results = await search(conn, "pan 40")
    assert results[0].sku.composition_key == "pantoprazole 40mg"


async def test_fixture_ids_exist(conn):
    for sku_id in ["sku_augmentin_625", "sku_moxclav_625", "sku_pan_40", "sku_dolo_650", "sku_electral_21g"]:
        sku = await get_sku(conn, sku_id)
        assert sku is not None, sku_id
    assert await get_sku(conn, "sku_does_not_exist") is None


async def test_generic_is_cheaper_with_same_key(conn):
    brand = await get_sku(conn, "sku_augmentin_625")
    generic = await cheapest_generic(conn, brand)
    assert generic is not None
    assert generic.sku_id != brand.sku_id
    assert generic.composition_key == brand.composition_key
    assert generic.form == brand.form
    assert generic.mrp_inr / generic.pack_size < brand.mrp_inr / brand.pack_size


async def test_empty_query(conn):
    assert await search(conn, "   ") == []


@pytest.mark.parametrize(
    ("query", "key_part", "rx_only", "schedule"),
    [
        ("azithromycin 500", "azithromycin 500mg", True, "H"),
        ("pantoprazole 40", "pantoprazole 40mg", True, "H"),
        ("metformin 500", "metformin 500mg", True, "H"),
        ("telmisartan 40", "telmisartan 40mg", True, "H"),
        ("cefixime 200", "cefixime 200mg", True, "H1"),
        ("alprazolam 0.25", "alprazolam 0.25mg", True, "H1"),
        ("paracetamol 650", "paracetamol 650mg", False, None),
        ("cetirizine 10", "cetirizine 10mg", False, None),
        ("electral", "oral rehydration salts", False, None),
        ("limcee", "vitamin c 500mg", False, None),
    ],
)
async def test_rx_flags_for_known_salts(conn, query, key_part, rx_only, schedule):
    results = await search(conn, query, limit=10)
    match = next((r.sku for r in results if r.sku.composition_key == key_part), None)
    assert match is not None, f"{query!r} did not find {key_part!r}"
    assert match.rx_only is rx_only
    assert match.schedule == schedule


async def test_generic_respects_price_floor(conn):
    # Oflocin at ₹1.14 a tablet sits far under the ₹7.98 median; it must not be offered
    brand = await get_sku(conn, "sku_oflox_200")
    generic = await cheapest_generic(conn, brand)
    assert generic is not None
    cur = await conn.execute(
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY mrp_inr / pack_size) AS m "
        "FROM skus WHERE composition_key = %s AND form = %s",
        (brand.composition_key, brand.form),
    )
    median_unit = (await cur.fetchone())["m"]
    assert generic.mrp_inr / generic.pack_size >= 0.2 * median_unit
    assert generic.mrp_inr / generic.pack_size < brand.mrp_inr / brand.pack_size


@pytest.mark.parametrize("sku_id", ["sku_dolo", "sku_dolo_250", "sku_augmentin_duo"])
async def test_whole_pack_generic_has_the_same_volume(conn, sku_id):
    brand = await get_sku(conn, sku_id)
    assert brand.pack_size == 1
    generic = await cheapest_generic(conn, brand)
    if generic is not None:
        assert pack_amount(generic.pack_label) == pack_amount(brand.pack_label)
        assert generic.mrp_inr < brand.mrp_inr


async def test_same_volume_generic_not_crowded_out_by_cheaper_sizes(conn):
    """60 cheaper 5 ml bottles must not hide the one cheaper 30 ml bottle."""
    key = "zz test salt 10mg/5ml"

    def row(sku_id: str, label: str, mrp: float) -> tuple:
        composition = '[{"name": "zz test salt", "strength": "10mg/5ml"}]'
        return (sku_id, sku_id, "Test Pharma", "syrup", 1, label, mrp, composition, key, False, None)

    rows = [row(f"sku_zz_small_{i:02d}", "bottle of 5 ml syrup", 10 + i / 100) for i in range(60)]
    rows.append(row("sku_zz_brand", "bottle of 30 ml syrup", 100))
    rows.append(row("sku_zz_generic", "bottle of 30 ml syrup", 50))
    rows.append(row("sku_zz_other_label", "bottle of 30 ml oral solution", 40))  # same volume, cheapest
    # inserted inside a savepoint that is always rolled back: the catalog is untouched
    async with conn.transaction(force_rollback=True):
        async with conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO skus (sku_id, brand_name, manufacturer, form, pack_size, pack_label, "
                "mrp_inr, composition, composition_key, rx_only, schedule) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                rows,
            )
        brand = await get_sku(conn, "sku_zz_brand")
        generic = await cheapest_generic(conn, brand)
    assert generic is not None
    assert generic.sku_id == "sku_zz_other_label"  # same 30 ml, cheapest of those
    assert pack_amount(generic.pack_label) == (30.0, "ml")
    assert await get_sku(conn, "sku_zz_brand") is None


async def test_search_leaves_trigram_threshold_alone(conn):
    await search(conn, "augmentin 625")
    await search(conn, "augmantin")
    cur = await conn.execute("SHOW pg_trgm.word_similarity_threshold")
    assert (await cur.fetchone())["pg_trgm.word_similarity_threshold"] == "0.6"  # pg_trgm default


async def test_typo_still_finds_brand(conn):
    results = await search(conn, "augmantin")
    assert results and results[0].sku.brand_name.lower().startswith("augmentin")


async def test_popularity_rank_is_loaded(conn):
    cur = await conn.execute(
        "SELECT count(*) AS n, count(popularity_rank) AS ranked, "
        "count(DISTINCT popularity_rank) AS distinct_ranks FROM skus"
    )
    row = await cur.fetchone()
    assert row["n"] == row["ranked"] == row["distinct_ranks"]


async def test_equal_scores_prefer_better_known_brand(conn):
    results = await search(conn, "paracetamol 650", limit=10)
    top_score = results[0].score
    tied = [r.sku.sku_id for r in results if r.score == top_score]
    cur = await conn.execute(
        "SELECT sku_id FROM skus WHERE sku_id = ANY(%s) ORDER BY popularity_rank",
        (tied,),
    )
    assert tied == [r["sku_id"] for r in await cur.fetchall()]
    assert {"sku_crocin_650", "sku_dolo_650"} <= set(tied[:3])
