# Daily prices: explicit currency and scoped Hong Kong support

## Change

`daily_bars` schema version 2 adds `currency` and changes price/turnover units
from a dataset-wide CNY assumption to the currency carried by each row. Existing
volume values keep their v2 meaning: shares. Data-version v2 is unchanged.

## Migration

No destructive data migration is required. All public readers and compaction
infer CNY only for legacy `.SH`, `.SZ`, and `.BJ` rows. New `.HK` rows must
explicitly carry HKD; missing or conflicting currency is an error. Legacy
Parquet can coexist with new files. Consumers selecting all columns must accept
the additional column; monetary aggregation across currencies requires an
explicit conversion outside this raw-price dataset.

The first audited HK ingestion scope is Pop Mart `09992.HK`, with verified 2026
sessions only. It uses the existing daily-price storage/revision pipeline.
HK rows never establish mainland session coverage or advance its watermark.
Other HK currencies/products, historical listing/suspension evidence, adjustment
factors and HK research universes remain unsupported and must not be inferred.

## Rollback

Retain the preceding code release and immutable lake revisions before upgrading.
To roll back, select the pre-upgrade daily-bars revision and run that preceding
release against the matching lake snapshot. Do not pass HK rows to older code
that assumes CNY, and do not strip the currency column from mixed-market data.
