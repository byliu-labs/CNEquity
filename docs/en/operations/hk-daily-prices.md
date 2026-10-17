# Pop Mart Hong Kong daily prices

The first Hong Kong ingestion scope is **Pop Mart `09992.HK` only**, with completed sessions in **2026**. This is a bounded raw-price pilot, not a Hong Kong market universe or an adjusted-return dataset.

## Configure and download

Use your existing configuration and lake. For an SSD lake, the relevant configuration is:

```toml
[data]
root = "/Volumes/SSD-lby/stock-data/cnequity"

[sources.eastmoney]
enabled = true
```

These are settings to merge into your configuration, not a complete configuration file. Keep the SSD mounted before running. Preview an explicit window first:

```sh
uv run cne backfill daily_bars --config configs/cnequity.toml \
  --symbols 09992.HK --start 2026-09-01 --end 2026-10-09 --plan
```

Download without HTTP, HTTPS or all-protocol proxy environment variables:

```sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  uv run cne backfill daily_bars --config configs/cnequity.toml \
  --symbols 09992.HK --start 2026-09-01 --end 2026-10-09
```

Only the named instrument is requested. The run records the source response, validates every expected session, stages the instrument identity and prices, and publishes them through the existing lake revisions. It does not sweep the mainland or HK market. Repeat this explicit command for another supported completed window; automatic HK daily updates are not configured.

## Data and queries

`daily_bars` holds unadjusted OHLC, `volume` in **shares**, and `amount` in **HKD** for Pop Mart. Every HK row must carry `currency="HKD"`. EastMoney's HK volume is already shares: applying the mainland multiplication by 100 corrupts it. Prices and turnover must not be aggregated with CNY values without an explicit exchange-rate conversion.

```python
from cnequity.query import load

prices = load(
    "daily_bars", data_root="/Volumes/SSD-lby/stock-data/cnequity",
    symbols=["09992.HK"], start="2026-09-01", end="2026-10-09",
)
print(prices.select("symbol", "trade_date", "close", "volume", "currency"))
```

The same raw rows and currency are available through the `daily_bars` SQL view and MCP `query_bars`. Existing mainland Parquet without `currency` reads as CNY only for `.SH`, `.SZ` and `.BJ`. Schema version 2 adds the currency column; volume data version v2 retains its existing shares meaning.

HK adjustment factors, corporate-action histories, historical listing/suspension evidence and research-universe filters are not supported. Explicit HK adjusted or universe requests fail instead of substituting factor 1 or mainland rules. Mainland universe reads exclude HK; separately scoped mainland adjusted reads continue to work in a mixed lake.

## Calendar and failure behavior

The calendar is bounded to verified 2026 HK securities sessions. Hong Kong can trade during mainland National Day closures, including October 2, 2026. The calendar also includes the April 7 Easter substitute holiday and half sessions on February 16, December 24 and December 31.

For current-day ingestion, a full session becomes final at **16:15 Asia/Hong_Kong**, and a half session at **12:15**. These include a five-minute buffer after the latest possible closing-auction end. They are not the mainland 15:05 cutoff.

Unknown calendar years, other HK symbols with unverified currency/product type, missing or conflicting HK currency, unfinished sessions and mixed HK/mainland download scopes fail explicitly. A missing feed, unexpected date, missing expected session or unconfirmed instrument identity publishes no new HK price rows. A gap cannot be silently treated as a suspension because independent HK suspension history is not implemented. Raw response evidence and failure receipts can remain for diagnosis; existing published lake revisions are retained.

Calendar updates require checking the official securities-market calendar and adding regression coverage before extending the year range. Vendor bars are observations, not authority to invent trading sessions.

Official references:

- [HKEX 2026 securities-market holiday circular](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf)
- [Hong Kong Government general holidays for 2026](https://www.gov.hk/en/about/abouthk/holiday/2026.htm)
- [HKEX Closing Auction Session FAQ](https://www.hkex.com.hk/Global/Exchange/FAQ/Securities-Market/Trading/CAS?sc_lang=en#collapse-5)
