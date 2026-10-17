# Pop Mart native daily-price validation

The proxy-free EastMoney download published 28 unadjusted HKD daily bars for
`09992.HK`, September 1–October 9, 2026, through the real CLI, HTTP client,
staging writer, compaction and revision store. Both the native reader and
DuckDB returned the prices. This is a scoped Pop Mart pilot, with verified
2026 sessions only.

## Evidence

| Check | Observed result |
| --- | --- |
| Live download run | `11d3f85a-6b0d-498c-b4a0-ee60e2a1d5a8`: success, published |
| Live trial lake | `/Volumes/SSD-lby/stock-data/trials/2026-10-17-hk-native/lake` |
| Working lake | `/Volumes/SSD-lby/stock-data/cnequity` |
| Retained publication run | `5a6c57f2-a290-45dc-84d6-f7c1862c9f6c`: success |
| Public SQL counts | `09992.HK/HKD: 28`, `300750.SZ/CNY: 23`, `600519.SH/CNY: 23` |
| October 9 HK close | HKD 152.30 |
| October 9 volume | 4,224,829 shares |
| October 9 turnover | HKD 639,923,680 |
| Mainland isolation | Bars, instrument identities and covered dates match backup |
| Unsupported HK adjustment | Reader rejects `adjust='hfq'` |

The first live request succeeded. A repeat request and a later working-lake
request disconnected without a response; both failed without publishing and
retained the source circuit breaker. No request was made to bypass that breaker.
The working lake was therefore populated from the successful trial's verified
native rows through `StagingWriter` and `step_compact`, preserving original
source and `fetched_at`. This publication made no HTTP request and is not claimed
as another successful download.

Raw gzip archive SHA-256:
`00184b4eaeb8727912a730df23afef7fc880e6de2eecc7056c538f79b36071c9`.
The archive and its metadata remain in the trial lake's `meta/raw/daily_bars/`.
The local `receipt.json` and `publish_retained.py` beside that lake retain the
checks and publication procedure. Before publication, lake and configuration
were copied to `backups/cnequity-before-hk-2026-10-17/` on the same SSD.

## Reproduction

Use the `feat/hk-daily-prices` worktree and its frozen SSD runtime. Configuration
enables EastMoney, disables TDX mocks, and limits DuckDB to one thread/512 MB.
The download process removes uppercase and lowercase HTTP/HTTPS/ALL proxy
variables; the user's shell settings are unchanged.

```sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    UV_PROJECT_ENVIRONMENT=/Volumes/SSD-lby/stock-data/cnequity-hk-runtime \
    uv run --no-sync cne backfill daily_bars \
      --config /Volumes/SSD-lby/stock-data/configs/cnequity.toml \
      --symbols 09992.HK --start 2026-09-01 --end 2026-10-09 --plan
```

Remove `--plan` to request the bounded download when the provider is available.
Run the read-only SQL query in the [HK runbook](../en/operations/hk-daily-prices.md)
to inspect existing prices without another provider request. The SSD README
records the currency-aware runtime and the preserved pre-HK backup.

## Behavior coverage

| Behavior | Tests |
| --- | --- |
| HK identities, shares, HKD, sessions, half-day finality, unknown-year rejection | `tests/unit/test_hk_prices.py` |
| Native publication, raw archive, repeated-run deduplication, incomplete-feed rejection | `tests/integration/test_hk_price_backfill.py` |
| Legacy CNY and mixed Parquet reads, SQL units, unsupported HK adjustments/universes | `tests/unit/test_hk_reader_contract.py` |
| HK dates do not create mainland coverage debt or advance mainland watermarks | `tests/integration/test_hk_mainland_publication_isolation.py` |
| Scoped identity snapshots cannot delist mainland instruments | `tests/unit/test_hk_publication_rules.py` |
| HK cannot be routed to mainland TDX intraday | `tests/unit/test_hk_tdx_boundary.py` |
| Legacy partial batches salvage good rows and quarantine original input | `tests/unit/test_partial_staging.py` |

The tests use actual Parquet/DuckDB and real HTTP client objects with a controlled
transport. The separate successful live request above verifies the real provider;
the provider's subsequent disconnect is an availability limitation. Calendar
sources and unsupported features are documented in the bilingual runbook.
