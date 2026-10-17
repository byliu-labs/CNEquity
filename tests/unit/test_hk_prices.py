from datetime import date, datetime, timezone

import httpx
import pytest

from cnequity.adapters.eastmoney.bars import _secid, fetch_daily_bars
from cnequity.domain.symbols import is_all_a_symbol, is_tdx_servable, parse_symbol


def test_hk_symbol_preserves_five_digits_and_routes_to_hk_market():
    info = parse_symbol("09992.HK")
    assert (info.code, info.exchange) == ("09992", "HK")
    assert _secid(info.symbol) == "116.09992"
    assert not is_tdx_servable(info.symbol)
    assert not is_all_a_symbol(info.code, info.exchange)


@pytest.mark.parametrize("symbol", ["9992.HK", "099920.HK", "ABCDE.HK", "00000.HK"])
def test_hk_symbol_rejects_ambiguous_or_invalid_codes(symbol):
    with pytest.raises(ValueError):
        parse_symbol(symbol)


def test_hk_kline_preserves_share_volume_and_hkd_currency():
    def respond(request):
        assert request.url.params["secid"] == "116.09992"
        return httpx.Response(
            200,
            json={
                "data": {
                    "code": "09992",
                    "market": 116,
                    "name": "泡泡玛特",
                    "klines": ["2026-10-02,151.2,149.2,152.3,147.5,4324247,645130400"],
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        bars = fetch_daily_bars(["09992.HK"], date(2026, 10, 2), date(2026, 10, 2), client=client)
    row = bars.row(0, named=True)
    assert row["volume"] == 4324247
    assert row["currency"] == "HKD"
    assert row["amount"] / row["volume"] == pytest.approx(149.189, abs=0.01)


def test_hk_calendar_keeps_mainland_holiday_and_rejects_unknown_year():
    from cnequity.domain.hk_market import hk_sessions, is_hk_session

    assert not is_hk_session(date(2026, 10, 1))
    assert is_hk_session(date(2026, 10, 2))
    assert date(2026, 10, 5) in hk_sessions(date(2026, 10, 1), date(2026, 10, 9))
    with pytest.raises(ValueError, match="calendar"):
        is_hk_session(date(2040, 1, 2))


def test_hk_finality_has_own_full_and_half_day_close():
    from cnequity.domain.hk_market import is_hk_session_final

    assert not is_hk_session_final(
        date(2026, 10, 2), datetime(2026, 10, 2, 7, 30, tzinfo=timezone.utc)
    )
    assert is_hk_session_final(date(2026, 10, 2), datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc))
    assert is_hk_session_final(
        date(2026, 12, 24), datetime(2026, 12, 24, 4, 15, tzinfo=timezone.utc)
    )


def test_unverified_hk_counter_is_rejected_before_network():
    with pytest.raises(ValueError, match="unverified"):
        fetch_daily_bars(["80011.HK"], date(2026, 10, 2), date(2026, 10, 5))
