import math

import pytest

from penny.engines.portfolio import (
    Holding,
    analyze,
    bumpiness_for,
    daily_move_pct,
    spread_for,
)


def holding(symbol: str, shares: int, price_cents: int) -> Holding:
    return Holding(symbol=symbol, shares=shares, price_cents=price_cents)


# ------------------------------------------------------------------ values and weights


def test_values_and_weights_add_up_and_are_sorted_largest_first():
    report = analyze([holding("snk", 5, 1000), holding("pxl", 6, 2000), holding("rkt", 2, 1500)])
    assert report.total_cents == 20000
    assert [(p.symbol, p.value_cents) for p in report.positions] == [
        ("PXL", 12000),
        ("SNK", 5000),
        ("RKT", 3000),
    ]
    assert [round(p.weight_pct) for p in report.positions] == [60, 25, 15]
    assert math.isclose(sum(p.weight_pct for p in report.positions), 100)
    assert report.largest_weight_pct == 60


def test_effective_number_of_companies():
    equal = analyze([holding("A", 1, 100), holding("B", 1, 100), holding("C", 1, 100)])
    assert math.isclose(equal.effective_holdings, 3)
    lopsided = analyze([holding("A", 98, 100), holding("B", 1, 100), holding("C", 1, 100)])
    assert lopsided.effective_holdings < 1.1
    assert math.isclose(analyze([holding("A", 3, 100)]).effective_holdings, 1)


@pytest.mark.parametrize(
    ("largest", "count", "spread"),
    [
        (100, 1, "Concentrated"),
        (60, 3, "Concentrated"),
        (50, 2, "Concentrated"),
        (40, 3, "Somewhat spread"),
        (35, 4, "Somewhat spread"),
        (34, 3, "Spread out"),
        (20, 5, "Spread out"),
    ],
)
def test_spread_labels(largest, count, spread):
    assert spread_for(largest, count) == spread


def test_a_single_company_is_always_concentrated():
    assert analyze([holding("A", 10, 100)]).spread == "Concentrated"


# ------------------------------------------------------------------ bumpiness


def test_flat_prices_have_no_daily_moves():
    assert daily_move_pct([1000, 1000, 1000, 1000]) == 0


def test_daily_move_is_the_spread_of_daily_percentage_changes():
    # +10% then -10%: returns 10 and about -9.09, sample standard deviation about 13.5
    move = daily_move_pct([1000, 1100, 1000])
    assert move == pytest.approx(13.5, abs=0.1)


@pytest.mark.parametrize("closes", [[], [1000], [1000, 1010], [1000, 0, 1000], [1000, -5, 1000]])
def test_too_little_or_broken_history_gives_no_answer(closes):
    assert daily_move_pct(closes) is None


@pytest.mark.parametrize(
    ("move", "label"),
    [
        (None, "Unknown"),
        (0.0, "Calmer"),
        (0.99, "Calmer"),
        (1.0, "Medium"),
        (1.99, "Medium"),
        (2.0, "Bumpier"),
        (5.0, "Bumpier"),
    ],
)
def test_bumpiness_labels(move, label):
    assert bumpiness_for(move) == label


def test_portfolio_bumpiness_is_weighted_by_value_and_skips_missing_history():
    calm = [1000, 1001, 1000, 1001, 1000]  # tiny moves
    wild = [1000, 1100, 1000, 1100, 1000]  # about 10% moves
    report = analyze(
        [holding("CALM", 3, 1000), holding("WILD", 1, 1000), holding("NEW", 1, 1000)],
        {"calm": calm, "wild": wild},  # symbol case does not matter
    )
    by_symbol = {p.symbol: p for p in report.positions}
    assert by_symbol["NEW"].daily_move_pct is None
    expected = (by_symbol["CALM"].daily_move_pct * 3 + by_symbol["WILD"].daily_move_pct * 1) / 4
    assert report.daily_move_pct == pytest.approx(expected)
    assert report.bumpiness == "Bumpier"


def test_without_any_history_bumpiness_is_unknown():
    report = analyze([holding("A", 1, 100), holding("B", 1, 100)])
    assert (report.daily_move_pct, report.bumpiness) == (None, "Unknown")


# ------------------------------------------------------------------ bad input


def test_an_empty_portfolio_or_a_repeated_company_is_refused():
    with pytest.raises(ValueError, match="at least one"):
        analyze([])
    with pytest.raises(ValueError, match="only once"):
        analyze([holding("PXL", 1, 100), holding("pxl", 2, 100)])


@pytest.mark.parametrize(
    "fields",
    [
        {"symbol": "", "shares": 1, "price_cents": 100},
        {"symbol": "A", "shares": 0, "price_cents": 100},
        {"symbol": "A", "shares": 1, "price_cents": 0},
    ],
)
def test_holdings_must_be_real(fields):
    with pytest.raises(ValueError):
        Holding(**fields)
