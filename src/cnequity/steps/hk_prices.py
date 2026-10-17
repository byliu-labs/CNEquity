"""Explicit HK raw-price scopes through the existing lake publication pipeline."""

from datetime import date

import polars as pl

from cnequity.adapters.eastmoney.bars import HKD_PRICE_SYMBOLS, fetch_daily_bars
from cnequity.config import Config
from cnequity.domain.hk_market import hk_sessions, is_hk_session_final
from cnequity.domain.schemas import data_version_for, validate_dataframe, with_provenance
from cnequity.domain.symbols import parse_symbol
from cnequity.orchestrator.registry import register_step
from cnequity.storage.parquet import StagingWriter
from cnequity.storage.raw_archive import RawPayloadArchive


def hk_backfill_plan(symbols: list[str], start: date | None, end: date | None) -> dict:
    if start is None or end is None:
        raise ValueError("HK prices require explicit --start and --end")
    if not 1 <= len(symbols) <= 50:
        raise ValueError("HK prices require between 1 and 50 explicit symbols")
    if any(parse_symbol(symbol).exchange != "HK" for symbol in symbols):
        raise ValueError("HK and mainland prices require separate scoped runs")
    if not set(symbols) <= HKD_PRICE_SYMBOLS:
        raise ValueError("HK currency/type is unverified; this price pilot supports 09992.HK only")
    if (end - start).days > 366:
        raise ValueError("HK price requests are limited to 366 calendar days")
    sessions = hk_sessions(start, end)
    if not sessions or not is_hk_session_final(sessions[-1]):
        raise ValueError("HK window must contain completed trading sessions")
    return {
        "dataset": "daily_bars",
        "market": "HK",
        "currency": "HKD",
        "source": "eastmoney",
        "adjustment": "unadjusted",
        "symbols": symbols,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sessions": len(sessions),
        "requests": len(symbols),
        "calendar_coverage": "2026",
    }


def _validate_scope(frame: pl.DataFrame, symbols: list[str], sessions: list[date]) -> None:
    expected = {(symbol, day) for symbol in symbols for day in sessions}
    actual = set(frame.select("symbol", "trade_date").rows()) if not frame.is_empty() else set()
    if actual != expected:
        raise RuntimeError(
            f"HK prices have incomplete or unexpected sessions: "
            f"missing={len(expected - actual)}, unexpected={len(actual - expected)}; "
            "no rows were staged; suspension/listing history is not yet supported"
        )


@register_step("hk_daily_bars", group="core", parallelizable=False)
def step_hk_daily_bars(config: Config, trade_date: date, run_id: str, context: dict) -> dict:
    symbols = config._backfill_symbols
    start, end = config._backfill_start, config._backfill_end
    plan = hk_backfill_plan(symbols, start, end)
    if not config.sources.get("eastmoney", False):
        raise ValueError("HK daily prices require [sources.eastmoney].enabled=true")
    archive = RawPayloadArchive(
        config.meta_root,
        datasets=["daily_bars"],
        compression=config.raw_archive_compression,
        max_payload_bytes=config.raw_archive_max_payload_bytes,
    )
    diagnostics: dict = {}
    bars = fetch_daily_bars(
        symbols, start, end, config=config, diagnostics=diagnostics, archive=archive, run_id=run_id
    )
    _validate_scope(bars, symbols, hk_sessions(start, end))
    identities = diagnostics["instruments_by_symbol"]
    if set(identities) != set(symbols) or any(not row["name"] for row in identities.values()):
        raise RuntimeError("HK source did not confirm every requested instrument identity")
    bars = validate_dataframe(
        with_provenance(bars, "eastmoney", data_version_for("daily_bars")), "daily_bars"
    )
    instruments = validate_dataframe(
        with_provenance(
            pl.DataFrame(list(identities.values())),
            "eastmoney_hk_scoped",
            data_version_for("instruments"),
        ),
        "instruments",
    )
    writer = StagingWriter(config.staging_root)
    writer.write_batch("instruments", run_id, "hk-instruments", instruments)
    writer.write_batch("daily_bars", run_id, "hk-prices", bars)
    return {
        "dataset": "daily_bars",
        "rows_read": bars.height,
        "rows_written": bars.height,
        "instrument_rows": instruments.height,
        "market": "HK",
        "currency": "HKD",
        "adjustment": "unadjusted",
        "scope": plan,
    }
