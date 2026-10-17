"""Native HK command -> real staging/Parquet/revisions -> reader and SQL."""

import json
from datetime import date

import duckdb
import httpx
import polars as pl
from click.testing import CliRunner

from cnequity.adapters.eastmoney.em_auth import EastMoneyClient
from cnequity.cli.main import cli
from cnequity.config import load_config
from cnequity.config.bootstrap import path_for_toml
from cnequity.query import load
from cnequity.query.views import ensure_duckdb_views


def _config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'[data]\nroot="{path_for_toml(tmp_path / "lake")}"\nprofile="demo"\n'
        "[orchestrator]\nworkers=1\n[sources.eastmoney]\nenabled=true\n"
        "[tdx_protocol]\nenabled=false\nallow_mock=false\n"
    )
    return path


def _args(config, *extra):
    return [
        "backfill",
        "daily_bars",
        "--config",
        str(config),
        "--symbols",
        "09992.HK",
        "--start",
        "2026-10-02",
        "--end",
        "2026-10-05",
        *extra,
    ]


def test_hk_plan_is_bounded_market_aware_and_writes_nothing(tmp_path):
    config = _config(tmp_path)
    result = CliRunner().invoke(cli, _args(config, "--plan"))
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["market"] == "HK"
    assert plan["currency"] == "HKD"
    assert plan["sessions"] == 2
    assert plan["source"] == "eastmoney"
    assert not (tmp_path / "lake").exists()


def test_pop_mart_backfill_survives_cn_holidays_and_repeat_download(tmp_path, monkeypatch):
    calls = []

    def respond(request):
        calls.append(request.url)
        assert request.url.params["secid"] == "116.09992"
        return httpx.Response(
            200,
            json={
                "data": {
                    "code": "09992",
                    "market": 116,
                    "name": "泡泡玛特",
                    "klines": [
                        "2026-10-02,151.2,149.2,152.3,147.5,4324247,645130400",
                        "2026-10-05,149.2,149.9,152.1,147.7,3315615,497456784",
                    ],
                }
            },
        )

    monkeypatch.setattr(
        EastMoneyClient,
        "_make_client",
        lambda self, **kwargs: httpx.Client(transport=httpx.MockTransport(respond)),
    )
    config = _config(tmp_path)
    for _ in range(2):
        result = CliRunner().invoke(cli, _args(config))
        assert result.exit_code == 0, result.output
    cfg = load_config(config)
    bars = load("daily_bars", config=cfg, symbols=["09992.HK"])
    assert bars.height == 2
    assert set(bars["currency"]) == {"HKD"}
    assert set(bars["trade_date"]) == {date(2026, 10, 2), date(2026, 10, 5)}
    assert bars.filter(pl.col("trade_date") == date(2026, 10, 2))["volume"][0] == 4324247
    instruments = load("instruments", config=cfg)
    assert instruments["name"].to_list() == ["泡泡玛特"]
    with duckdb.connect(str(ensure_duckdb_views(cfg)), read_only=True) as con:
        assert con.execute("SELECT DISTINCT symbol, currency FROM daily_bars").fetchall() == [
            ("09992.HK", "HKD")
        ]
    assert len(calls) == 2
    assert list((cfg.meta_root / "raw" / "daily_bars").rglob("*.gz"))


def test_hk_backfill_refuses_incomplete_response_without_publishing(tmp_path, monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
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
    )
    monkeypatch.setattr(
        EastMoneyClient, "_make_client", lambda self, **kwargs: httpx.Client(transport=transport)
    )
    config = _config(tmp_path)
    result = CliRunner().invoke(cli, _args(config))
    assert result.exit_code != 0
    assert not list((tmp_path / "lake" / "curated" / "daily_bars").rglob("*.parquet"))


def test_hk_rejects_mixed_scope_before_any_download(tmp_path):
    config = _config(tmp_path)
    args = _args(config)
    args[args.index("09992.HK")] = "09992.HK,600519.SH"
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "separate" in result.output.lower()
