"""Forecast model, backtest and reorder maths on generated data. Pure: no database."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from app.contracts import ForecastSummary, SkuForecast
from app.forecast import model
from app.forecast.store import compute
from app.forecast.synthetic import IST, PLAN, SPIKE_SKUS, generate, hour_of_week_curve

END = datetime(2026, 9, 30, 14, 30, tzinfo=IST)


@pytest.fixture(scope="module")
def data():
    return generate(END)


@pytest.fixture(scope="module")
def computed(data):
    frame = data.demand.stack(["area", "sku_id"], future_stack=True).rename("qty").reset_index()
    frame = frame.rename(columns={"level_0": "ts"})
    frame = frame[frame["qty"] > 0]
    brands = {sku: sku.removeprefix("sku_") for sku, _ in PLAN}
    return compute(frame, data.inventory, brands, END)


def test_generator_is_reproducible(data):
    again = generate(END)
    assert again.demand.equals(data.demand)
    assert again.inventory.equals(data.inventory)


def test_generator_structure(data):
    demand = data.demand
    assert demand.shape == (90 * 24, 150)
    hourly = demand.sum(axis=1)
    by_hour = hourly.groupby(hourly.index.hour).mean()
    assert by_hour.loc[18:22].mean() > 1.5 * by_hour.loc[9:17].mean()  # evening peak
    assert by_hour.loc[1:6].mean() < 0.1 * by_hour.loc[18:22].mean()  # quiet night
    daily = hourly.resample("D").sum().iloc[1:-1]
    assert daily[daily.index.dayofweek == 6].mean() > daily[daily.index.dayofweek < 5].mean()  # Sunday bump
    # area mix: chronic SKUs sell more in A, OTC in B
    assert demand[("Area A", "sku_telma_40")].sum() > 2 * demand[("Area B", "sku_telma_40")].sum()
    assert demand[("Area B", "sku_cetzine")].sum() > 1.5 * demand[("Area A", "sku_cetzine")].sum()
    # the outbreak: last 21 days well above the 21 before, for spike SKUs only
    last, before = demand.iloc[-21 * 24 :], demand.iloc[-42 * 24 : -21 * 24]
    assert last[("Area C", "sku_dolo_650")].sum() > 1.8 * before[("Area C", "sku_dolo_650")].sum()
    assert last[("Area C", "sku_telma_40")].sum() < 1.2 * before[("Area C", "sku_telma_40")].sum()


def test_curve_sums_to_one_day_per_day():
    assert hour_of_week_curve().sum() == pytest.approx(7)


def test_forecast_recovers_a_flat_seasonal_pattern():
    index = pd.date_range("2026-06-01", periods=10 * 168, freq="h", tz=IST)
    rates = hour_of_week_curve()[model.hour_of_week(index)] * 24
    history = pd.Series(rates, index=index)
    fc = model.forecast(history, 48)
    future = pd.date_range(index[-1] + pd.Timedelta(hours=1), periods=48, freq="h", tz=IST)
    expected = hour_of_week_curve()[model.hour_of_week(future)] * 24
    np.testing.assert_allclose(fc, expected, rtol=0.02)


def test_backtest_beats_naive_on_spike_skus(computed):
    _, series = computed
    spike = [s for s in series if s.sku_id in SPIKE_SKUS]
    assert len(spike) == len(SPIKE_SKUS) * 3
    assert np.mean([s.model_mape for s in spike]) < np.mean([s.naive_mape for s in spike])


def test_backtest_beats_naive_overall(computed):
    summary, _ = computed
    assert summary.backtest.horizon_days == 14
    assert summary.backtest.model_mape < summary.backtest.naive_mape


def test_reorders(computed, data):
    summary, _ = computed
    assert len(summary.reorders) == 150
    assert all(r.reorder_qty >= 0 for r in summary.reorders)
    risky = [r for r in summary.reorders if r.stockout_risk]
    assert risky, "at least one stockout risk"
    assert summary.reorders[0].stockout_risk  # risks first
    for r in risky:
        assert r.hours_to_stockout is not None and r.hours_to_stockout < 24
        assert r.reorder_qty > 0
    # every deliberately low series is flagged
    flagged = {(r.area, r.sku_id) for r in risky}
    assert data.low_stock <= flagged


def test_outputs_validate_against_contracts(computed):
    summary, series = computed
    ForecastSummary.model_validate(summary.model_dump(mode="json"))
    assert summary.areas == ["Area A", "Area B", "Area C"]
    assert len(summary.skus) == 50
    one = SkuForecast.model_validate(series[0].model_dump(mode="json"))
    past = [p for p in one.points if p.actual is not None]
    future = [p for p in one.points if p.actual is None]
    assert len(past) == 7 * 24
    assert len(future) == 48
    assert all(p.ts.utcoffset() == IST.utcoffset(END) for p in one.points)


@pytest.mark.parametrize(
    ("on_hand", "rate", "qty", "risk", "hours"),
    [
        (0, 1.0, 29, True, 0.0),  # empty: order 24 x 1.2 = 28.8 -> 29
        (12, 1.0, 17, True, 12.0),
        (30, 1.0, 0, False, 30.0),  # lasts past the lead time, still inside 48 h
        (100, 1.0, 0, False, None),
    ],
)
def test_reorder_rule(on_hand, rate, qty, risk, hours):
    ro = model.reorder(on_hand, [rate] * 48, 24)
    assert ro.forecast_over_lead_time == pytest.approx(24.0)
    assert ro.reorder_qty == qty
    assert ro.stockout_risk is risk
    assert ro.hours_to_stockout == (None if hours is None else pytest.approx(hours))
