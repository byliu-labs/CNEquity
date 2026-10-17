from datetime import date

import pytest

from cnequity.adapters.tdx_protocol.minute_bars import (
    TdxMinuteBarsError,
    fetch_minute_bars_paginated,
)


@pytest.mark.parametrize("symbol", ["09992.HK", "09992.hk", "09992.UNKNOWN"])
def test_unsupported_intraday_market_is_rejected_before_request(symbol):
    class Client:
        called = False

        def bars(self, **kwargs):
            self.called = True
            return []

    client = Client()
    with pytest.raises(TdxMinuteBarsError, match="TDX serves no"):
        fetch_minute_bars_paginated(client, symbol, date(2026, 10, 2), date(2026, 10, 2))
    assert not client.called
