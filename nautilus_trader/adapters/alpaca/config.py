# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2025 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------
"""
Alpaca adapter configuration classes.
"""

from nautilus_trader.adapters.alpaca.common.constants import ALPACA_VENUE
from nautilus_trader.adapters.alpaca.common.enums import AlpacaAssetClass
from nautilus_trader.adapters.alpaca.common.enums import AlpacaDataFeed
try:
    from nautilus_trader.config import PositiveInt
except ImportError:
    PositiveInt = int

try:
    from nautilus_trader.config import InstrumentProviderConfig
except ImportError:
    try:
        from nautilus_trader.live import InstrumentProviderConfig
    except ImportError:
        InstrumentProviderConfig = object

try:
    from nautilus_trader.config import LiveDataClientConfig
except ImportError:
    try:
        from nautilus_trader.live import DataClientConfig as LiveDataClientConfig
    except ImportError:
        LiveDataClientConfig = object

try:
    from nautilus_trader.config import LiveExecClientConfig
except ImportError:
    try:
        from nautilus_trader.live import ExecutionClientConfig as LiveExecClientConfig
    except ImportError:
        LiveExecClientConfig = object

try:
    from nautilus_trader.model.identifiers import Venue
except ImportError:
    from nautilus_trader.model import Venue


try:
    class AlpacaInstrumentProviderConfig(InstrumentProviderConfig, frozen=True):
        asset_classes: frozenset[AlpacaAssetClass] | None = None
        option_underlying_symbols: frozenset[str] | None = None
except TypeError:
    class AlpacaInstrumentProviderConfig:
        def __init__(self, asset_classes=None, option_underlying_symbols=None):
            self.asset_classes = asset_classes
            self.option_underlying_symbols = option_underlying_symbols


try:
    class AlpacaDataClientConfig(LiveDataClientConfig, frozen=True):
        venue: Venue = ALPACA_VENUE
        api_key: str | None = None
        api_secret: str | None = None
        data_feed: AlpacaDataFeed = AlpacaDataFeed.IEX
        paper_trading: bool = True
        base_url_http: str | None = None
        base_url_ws: str | None = None
        proxy_url: str | None = None
        http_timeout_secs: PositiveInt | None = 30
        update_instruments_interval_mins: PositiveInt | None = 60
except TypeError:
    class AlpacaDataClientConfig(LiveDataClientConfig):
        def __init__(
            self,
            venue=ALPACA_VENUE,
            api_key=None,
            api_secret=None,
            data_feed=AlpacaDataFeed.IEX,
            paper_trading=True,
            base_url_http=None,
            base_url_ws=None,
            proxy_url=None,
            http_timeout_secs=30,
            update_instruments_interval_mins=60,
            **kwargs,
        ):
            super().__init__(**kwargs)
            self.venue = venue
            self.api_key = api_key
            self.api_secret = api_secret
            self.data_feed = data_feed
            self.paper_trading = paper_trading
            self.base_url_http = base_url_http
            self.base_url_ws = base_url_ws
            self.proxy_url = proxy_url
            self.http_timeout_secs = http_timeout_secs
            self.update_instruments_interval_mins = update_instruments_interval_mins


try:
    class AlpacaExecClientConfig(LiveExecClientConfig, frozen=True):
        venue: Venue = ALPACA_VENUE
        api_key: str | None = None
        api_secret: str | None = None
        paper_trading: bool = True
        base_url_http: str | None = None
        base_url_ws: str | None = None
        proxy_url: str | None = None
        http_timeout_secs: PositiveInt | None = 30
        max_retries: PositiveInt | None = 3
        retry_delay_secs: float = 1.0
except TypeError:
    class AlpacaExecClientConfig(LiveExecClientConfig):
        def __init__(
            self,
            venue=ALPACA_VENUE,
            api_key=None,
            api_secret=None,
            paper_trading=True,
            base_url_http=None,
            base_url_ws=None,
            proxy_url=None,
            http_timeout_secs=30,
            max_retries=3,
            retry_delay_secs=1.0,
            **kwargs,
        ):
            super().__init__(**kwargs)
            self.venue = venue
            self.api_key = api_key
            self.api_secret = api_secret
            self.paper_trading = paper_trading
            self.base_url_http = base_url_http
            self.base_url_ws = base_url_ws
            self.proxy_url = proxy_url
            self.http_timeout_secs = http_timeout_secs
            self.max_retries = max_retries
            self.retry_delay_secs = retry_delay_secs