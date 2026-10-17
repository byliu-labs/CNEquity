from datetime import date

import polars as pl
import pytest

from cnequity.config import Config
from cnequity.domain.datasets import DATASETS
from cnequity.quality.verify import last_contiguous_dense_date
from cnequity.storage.staged_contracts import enforce_daily_bar_contracts
from cnequity.storage.state import StateStore


@pytest.mark.parametrize("session", [date(2026, 10, 2), date(2026, 10, 9)])
def test_hk_only_publication_does_not_create_mainland_completeness_debt(tmp_path, session):
    cfg = Config(data_root=tmp_path)
    instruments = cfg.curated_root / "instruments"
    instruments.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": [f"92000{i}.BJ" for i in range(5)],
            "name": ["listed"] * 5,
            "exchange": ["BJ"] * 5,
            "list_date": [date(2020, 1, 1)] * 5,
            "delist_date": [None] * 5,
        },
        schema_overrides={"delist_date": pl.Date},
    ).write_parquet(instruments / "part.parquet")
    staged = cfg.staging_root / "hk.parquet"
    staged.parent.mkdir(parents=True)
    pl.DataFrame(
        {"symbol": ["09992.HK"], "trade_date": [session], "currency": ["HKD"]}
    ).write_parquet(staged)

    findings = enforce_daily_bar_contracts(
        cfg,
        "hk-run",
        [staged],
        committed_root=None,
        actions_root=None,
        instruments_root=instruments,
    )

    assert findings == []
    assert not StateStore(cfg.meta_root).get_payload("daily_bars").get("missing_ranges")


@pytest.mark.parametrize("mainland_present", [False, True])
def test_hk_rows_do_not_advance_mainland_daily_bars_watermark(tmp_path, mainland_present):
    cfg = Config(data_root=tmp_path)
    bars = cfg.curated_root / "daily_bars"
    bars.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["09992.HK"],
            "trade_date": [date(2026, 10, 9)],
            "currency": ["HKD"],
            "volume": [100],
        }
    ).write_parquet(bars / "hk.parquet")
    if mainland_present:
        pl.DataFrame(
            {
                "symbol": ["600519.SH"],
                "trade_date": [date(2026, 10, 8)],
                "currency": ["CNY"],
                "volume": [100],
            }
        ).write_parquet(bars / "cn.parquet")

    expected = date(2026, 10, 8) if mainland_present else None
    assert last_contiguous_dense_date(cfg, DATASETS["daily_bars"]) == expected
