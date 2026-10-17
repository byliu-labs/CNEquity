from datetime import date, datetime, timezone

import polars as pl
import pytest

from cnequity.config import Config
from cnequity.quality.bar_finality import daily_bar_finality_findings
from cnequity.quality.cross_checks import adj_factor_coverage_findings, daily_bars_calendar_findings
from cnequity.storage import StagingWriter
from cnequity.storage.instruments import compact_instruments


def test_hk_sessions_do_not_inherit_mainland_national_day_closure(tmp_path):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["09992.HK"],
            "trade_date": [date(2026, 10, 2)],
            "currency": ["HKD"],
            "volume": [100],
        }
    ).write_parquet(root / "part.parquet")
    cal = cfg.curated_root / "trading_calendar"
    cal.mkdir(parents=True)
    pl.DataFrame({"trade_date": [date(2026, 9, 30)], "is_trading": [True]}).write_parquet(
        cal / "part.parquet"
    )
    assert daily_bars_calendar_findings(cfg, date(2026, 10, 2)) == []


def test_hk_holiday_is_rejected_without_mainland_calendar(tmp_path):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["09992.HK"],
            "trade_date": [date(2026, 10, 1)],
            "currency": ["HKD"],
            "volume": [100],
        }
    ).write_parquet(root / "part.parquet")
    findings = daily_bars_calendar_findings(cfg, date(2026, 10, 2))
    assert len(findings) == 1
    assert findings[0]["check"] == "daily_bars_calendar_orphan"
    assert findings[0]["exchange"] == "HK"


@pytest.mark.parametrize("hour,expected", [(7, 1), (9, 0)])
def test_hk_finality_uses_hong_kong_close(tmp_path, hour, expected):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["09992.HK"],
            "trade_date": [date(2026, 10, 2)],
            "currency": ["HKD"],
            "volume": [100],
            "fetched_at": [datetime(2026, 10, 2, hour, 30, tzinfo=timezone.utc)],
        }
    ).write_parquet(root / "part.parquet")
    assert len(daily_bar_finality_findings(cfg, date(2026, 10, 2))) == expected


@pytest.mark.parametrize(
    "incoming_source,incoming_exchange", [("eastmoney_hk_scoped", "HK"), ("tdx_protocol", "SH")]
)
def test_scoped_hk_and_mainland_snapshots_preserve_other_hk_identities(
    tmp_path, incoming_source, incoming_exchange
):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "instruments"
    root.mkdir(parents=True)
    rows = [
        {
            "symbol": f"{i:05d}.HK",
            "name": str(i),
            "exchange": "HK",
            "asset_type": "stock",
            "list_date": date(2020, 1, 1),
            "delist_date": None,
            "prev_symbol": None,
            "source": "eastmoney_hk_scoped",
            "data_version": "v1",
            "fetched_at": datetime(2026, 10, 2, tzinfo=timezone.utc),
        }
        for i in range(100)
    ]
    pl.DataFrame(rows).write_parquet(root / "part-merged.parquet")
    bars = cfg.curated_root / "daily_bars"
    bars.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": [r["symbol"] for r in rows],
            "trade_date": [date(2026, 10, 2)] * 100,
            "currency": ["HKD"] * 100,
        }
    ).write_parquet(bars / "part.parquet")
    incoming = (
        rows[1:]
        if incoming_exchange == "HK"
        else [{**rows[0], "symbol": "600519.SH", "exchange": "SH"}]
    )
    incoming = [{**r, "source": incoming_source} for r in incoming]
    for day in (date(2026, 10, 5), date(2026, 10, 6)):
        run_id = day.isoformat()
        StagingWriter(cfg.staging_root).write_batch(
            "instruments", run_id, "selected", pl.DataFrame(incoming)
        )
        _, findings = compact_instruments(cfg.staging_root, cfg.curated_root, run_id, day)
        assert findings == []
    merged = pl.read_parquet(root / "part-merged.parquet")
    assert merged.filter(pl.col("symbol").str.ends_with(".HK"))["delist_date"].null_count() == 100


def test_raw_only_hk_is_not_claimed_to_have_missing_supported_adjustments(tmp_path):
    cfg = Config(data_root=tmp_path)
    datasets = {
        cfg.curated_root / "instruments": {"symbol": ["09992.HK"], "asset_type": ["stock"]},
        cfg.curated_root / "daily_bars": {
            "symbol": ["09992.HK"],
            "currency": ["HKD"],
            "trade_date": [date(2026, 10, 2)],
            "volume": [100],
        },
        cfg.derived_root / "adj_factors": {
            "symbol": ["600519.SH"],
            "trade_date": [date(2026, 10, 2)],
            "factor": [1.0],
            "adjust_type": ["hfq"],
        },
    }
    for root, data in datasets.items():
        root.mkdir(parents=True)
        pl.DataFrame(data).write_parquet(root / "part.parquet")
    assert adj_factor_coverage_findings(cfg, date(2026, 10, 2)) == []
