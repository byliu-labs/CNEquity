# 泡泡玛特港股日线

首个港股采集范围仅限 **泡泡玛特 `09992.HK`**，支持 **2026 年**已结束的交易日。这是有明确范围的原始价格试点，不是完整港股股票池，也不是复权收益数据集。

## 配置与下载

沿用现有配置与数据湖。SSD 数据湖的相关配置如下：

```toml
[data]
root = "/Volumes/SSD-lby/stock-data/cnequity"

[sources.eastmoney]
enabled = true
```

请把这些设置合并到现有配置中；这不是完整配置文件。运行前确认 SSD 已挂载。先预览明确的日期范围：

```sh
uv run cne backfill daily_bars --config configs/cnequity.toml \
  --symbols 09992.HK --start 2026-09-01 --end 2026-10-09 --plan
```

下载时移除 HTTP、HTTPS 与全协议代理环境变量：

```sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  uv run cne backfill daily_bars --config configs/cnequity.toml \
  --symbols 09992.HK --start 2026-09-01 --end 2026-10-09
```

只请求指定证券。运行会保留源响应，核验全部应有交易日，暂存证券身份与日线，再通过现有数据湖版本机制发布；不会扫描全部 A 股或港股。其他受支持的已结束日期范围可重复运行上述命令；目前没有配置港股自动日更。

## 数据与查询

`daily_bars` 中的泡泡玛特 OHLC 为未复权价格，`volume` 单位为**股**，`amount` 单位为**港元**。每条港股记录必须明确携带 `currency="HKD"`。东财港股成交量本来就是股，不能套用大陆市场乘以 100 的换算。价格和成交额不能未经汇率转换就与人民币值汇总。

```python
from cnequity.query import load

prices = load(
    "daily_bars", data_root="/Volumes/SSD-lby/stock-data/cnequity",
    symbols=["09992.HK"], start="2026-09-01", end="2026-10-09",
)
print(prices.select("symbol", "trade_date", "close", "volume", "currency"))
```

SQL 的 `daily_bars` 视图及 MCP `query_bars` 也提供相同原始记录与币种。旧版大陆 Parquet 缺少 `currency` 时，仅对 `.SH`、`.SZ`、`.BJ` 补为 CNY。模式版本 2 新增币种列；成交量的数据版本 v2 仍表示股，含义不变。

目前不支持港股复权因子、公司行为历史、历史上市与停牌证据及研究股票池筛选。明确指定港股并请求复权或股票池时会报错，不会用因子 1 或大陆规则替代。大陆股票池查询排除港股；在混合数据湖中，单独限定大陆证券的复权查询仍然可用。

## 交易日历与失败处理

日历仅覆盖已核验的 2026 年香港证券交易日。香港可以在大陆国庆休市期间交易，例如 2026 年 10 月 2 日。日历还包含 4 月 7 日复活节补假，以及 2 月 16 日、12 月 24 日和 12 月 31 日的半日市。

当日采集以 **Asia/Hong_Kong 16:15** 为全日市完成时间，半日市为 **12:15**；均在收市竞价最晚结束时间后留出五分钟缓冲，不沿用大陆 15:05 截止时间。

未覆盖的日历年份、币种或产品类型未核验的其他港股、缺失或冲突的港股币种、尚未结束的交易日及混合港股和大陆下载范围都会明确失败。数据源缺失、日期异常、应有交易日缺行或证券身份未确认时，不发布新的港股价格行。由于还没有独立的港股停牌历史，不能把缺行默认为停牌。原始响应证据与失败记录可保留用于诊断，已发布的数据湖版本仍然保留。

扩展年份前，必须核对官方证券市场日历并增加回归测试。数据商返回的日线只是观察结果，不能授权系统臆造交易日。

官方依据：

- [港交所 2026 年证券市场假期通告](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf)
- [香港政府 2026 年公众假期](https://www.gov.hk/en/about/abouthk/holiday/2026.htm)
- [港交所收市竞价交易时段常见问题](https://www.hkex.com.hk/Global/Exchange/FAQ/Securities-Market/Trading/CAS?sc_lang=en#collapse-5)
