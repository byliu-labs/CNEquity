from datetime import date, datetime, timezone

import duckdb
import polars as pl
import pytest

from cnequity.config import Config
from cnequity.domain.schemas import SchemaValidationError, sanitize_dataset_rows, validate_dataframe
from cnequity.query.reader import ReaderError, load, scan
from cnequity.query.views import ensure_duckdb_views


def _bar(symbol, currency=None):
    row = {
        "symbol": symbol,
        "trade_date": date(2026, 10, 2),
        "open": 150.0,
        "high": 153.0,
        "low": 149.0,
        "close": 152.0,
        "volume": 1000,
        "amount": 151500.0,
        "source": "eastmoney",
        "data_version": "v2",
        "fetched_at": datetime(2026, 10, 3, tzinfo=timezone.utc),
    }
    if currency is not None:
        row["currency"] = currency
    return pl.DataFrame([row])


@pytest.mark.parametrize("symbol", ["600519.SH", "300750.SZ", "920001.BJ"])
def test_legacy_mainland_currency_is_cny(symbol):
    assert validate_dataframe(_bar(symbol), "daily_bars")["currency"].to_list() == ["CNY"]


@pytest.mark.parametrize("currency", [None, "CNY", "USD"])
def test_hk_currency_must_be_explicit_hkd(currency):
    with pytest.raises(SchemaValidationError, match="currency"):
        validate_dataframe(_bar("09992.HK", currency), "daily_bars")


def test_hk_rows_survive_mainland_holiday_sanitization():
    bars = pl.concat([_bar("09992.HK", "HKD"), _bar("600519.SH")], how="diagonal_relaxed")
    assert sanitize_dataset_rows(bars, "daily_bars")["symbol"].to_list() == ["09992.HK"]


@pytest.mark.parametrize("mixed", [False, True])
def test_native_public_readers_expose_legacy_and_hk_currency(tmp_path, mixed):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    _bar("600519.SH").write_parquet(root / "old.parquet")
    if mixed:
        _bar("09992.HK", "HKD").write_parquet(root / "hk.parquet")
    expected = [("09992.HK", "HKD"), ("600519.SH", "CNY")] if mixed else [("600519.SH", "CNY")]
    assert (
        load("daily_bars", config=cfg).select("symbol", "currency").sort("symbol").rows()
        == expected
    )
    assert (
        scan("daily_bars", config=cfg).select("symbol", "currency").sort("symbol").collect().rows()
        == expected
    )
    with duckdb.connect(str(ensure_duckdb_views(cfg)), read_only=True) as con:
        assert (
            con.execute("SELECT symbol, currency FROM daily_bars ORDER BY symbol").fetchall()
            == expected
        )
        assert con.execute("SELECT symbol, close FROM daily_bars ORDER BY symbol").fetchall() == [
            (symbol, 152.0) for symbol, _currency in expected
        ]


@pytest.mark.parametrize("currency", [None, "CNY"])
def test_invalid_hk_fragments_are_rejected_by_raw_scan_and_sql(tmp_path, currency):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    _bar("09992.HK", currency).write_parquet(root / "hk.parquet")
    with pytest.raises(SchemaValidationError, match="currency"):
        scan("daily_bars", config=cfg).select("close").collect()
    with duckdb.connect(str(ensure_duckdb_views(cfg)), read_only=True) as con:
        with pytest.raises(duckdb.InvalidInputException, match="currency"):
            con.execute("SELECT currency FROM daily_bars").fetchall()
        with pytest.raises(duckdb.InvalidInputException, match="currency"):
            con.execute("SELECT close FROM daily_bars").fetchall()


def test_mcp_raw_hk_response_carries_currency_and_supported_scope(tmp_path):
    from cnequity.mcp_server.tools import query_bars

    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    _bar("09992.HK", "HKD").write_parquet(root / "hk.parquet")
    payload = query_bars(cfg, symbols=["09992.HK"])
    assert payload["rows"][0][payload["columns"].index("currency")] == "HKD"
    assert "HK adjustment" in payload["warning"]


@pytest.mark.parametrize(
    "kwargs",
    [{"adjust": "hfq"}, {"adjust": "qfq"}, {"adjust": "total_return"}, {"universe": "all_a"}],
)
def test_explicit_hk_unsupported_research_requests_fail_clearly(tmp_path, kwargs):
    with pytest.raises(ReaderError, match="HK.*not supported"):
        load("daily_bars", symbols=["09992.HK"], config=Config(data_root=tmp_path), **kwargs)


def test_mixed_lake_adjustment_does_not_silently_give_hk_factor_one(tmp_path):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    _bar("09992.HK", "HKD").write_parquet(root / "hk.parquet")
    with pytest.raises(ReaderError, match="HK.*not supported"):
        load("daily_bars", adjust="hfq", config=cfg)


def test_mainland_universe_never_includes_hk_without_instruments(tmp_path):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    _bar("09992.HK", "HKD").write_parquet(root / "hk.parquet")
    assert load("daily_bars", universe="all_a", config=cfg).is_empty()


@pytest.mark.parametrize(
    "query",
    [
        "SELECT hfq_close FROM daily_bars_adj WHERE symbol='09992.HK'",
        "SELECT qfq_close FROM daily_bars_qfq(NULL, NULL) WHERE symbol='09992.HK'",
        "SELECT tr_close FROM daily_bars_total_return(NULL, NULL) WHERE symbol='09992.HK'",
    ],
)
def test_sql_adjustment_refuses_hk(tmp_path, query):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    _bar("09992.HK", "HKD").write_parquet(root / "hk.parquet")
    with duckdb.connect(str(ensure_duckdb_views(cfg)), read_only=True) as con:
        with pytest.raises(duckdb.InvalidInputException, match="HK.*not supported"):
            con.execute(query).fetchall()


def test_sql_qfq_mainland_scope_works_after_hk_is_added(tmp_path):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    _bar("600519.SH").write_parquet(root / "mainland.parquet")
    _bar("09992.HK", "HKD").write_parquet(root / "hk.parquet")
    with duckdb.connect(str(ensure_duckdb_views(cfg)), read_only=True) as con:
        assert con.execute(
            "SELECT symbol, qfq_close FROM daily_bars_qfq(NULL, NULL) WHERE symbol='600519.SH'"
        ).fetchall() == [("600519.SH", 152.0)]


@pytest.mark.parametrize(
    "relation,column,expected",
    [
        ("daily_bars_adj", "hfq_close", 304.0),
        ("daily_bars_adj", "qfq_close", 152.0),
        ("daily_bars_adj", "adj_close", 152.0),
        ("daily_bars_total_return(NULL, NULL)", "tr_close", 304.0),
        ("daily_bars_total_return(NULL, NULL)", "adj_close", 304.0),
    ],
)
def test_sql_mainland_adjustment_in_mixed_lake_keeps_verified_factors(
    tmp_path, relation, column, expected
):
    cfg = Config(data_root=tmp_path)
    root = cfg.curated_root / "daily_bars"
    root.mkdir(parents=True)
    _bar("600519.SH").write_parquet(root / "mainland.parquet")
    _bar("09992.HK", "HKD").write_parquet(root / "hk.parquet")
    factors = cfg.derived_root / "adj_factors"
    factors.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "trade_date": [date(2026, 10, 2)],
            "factor": [2.0],
            "adjust_type": ["hfq"],
        }
    ).write_parquet(factors / "factor.parquet")
    # An actual fund payout keeps the shared bars CTE's other consumers live;
    # an empty actions table can let the optimizer erase that execution path.
    _bar("510300.SH").write_parquet(root / "fund.parquet")
    instruments = cfg.curated_root / "instruments"
    instruments.mkdir(parents=True)
    pl.DataFrame({"symbol": ["510300.SH"], "asset_type": ["etf"]}).write_parquet(
        instruments / "fund.parquet"
    )
    actions = cfg.curated_root / "corporate_actions"
    actions.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["510300.SH"],
            "ex_date": [date(2026, 10, 2)],
            "action_type": ["cash_dividend"],
            "cash_dividend": [1.0],
        }
    ).write_parquet(actions / "payout.parquet")
    with duckdb.connect(str(ensure_duckdb_views(cfg)), read_only=True) as con:
        assert con.execute(
            f"SELECT symbol, {column} FROM {relation} WHERE symbol='600519.SH'"
        ).fetchall() == [("600519.SH", expected)]
