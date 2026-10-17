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
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.config import LiveDataClientConfig
from nautilus_trader.config import LiveExecClientConfig
from nautilus_trader.config import PositiveInt
from nautilus_trader.model.identifiers import Venue


class AlpacaInstrumentProviderConfig(InstrumentProviderConfig, frozen=True):
    """
    Configuration for ``AlpacaInstrumentProvider`` instances.

    Parameters
    ----------
    load_all : bool, default False
        If all venue instruments should be loaded on start.
    load_ids : frozenset[InstrumentId], optional
        The list of instrument IDs to be loaded on start (if `load_all` is False).
    filters : frozendict or dict[str, Any], optional
        The venue specific instrument loading filters to apply.
    filter_callable : str, optional
        A fully qualified path to a callable that takes a single argument, `instrument`
        and returns a bool, indicating whether the instrument should be loaded.
    log_warnings : bool, default True
        If parser warnings should be logged.
    asset_classes : frozenset[AlpacaAssetClass], optional
        The asset classes to load instruments for.
        If None, defaults to US_EQUITY only for the MVP.
    option_underlying_symbols : frozenset[str], optional
        The underlying symbols to load option contracts for.
        Required when loading options. E.g. frozenset({"AAPL", "MSFT"}).

    """

    asset_classes: frozenset[AlpacaAssetClass] | None = None
    option_underlying_symbols: frozenset[str] | None = None


class AlpacaDataClientConfig(LiveDataClientConfig, frozen=True):
    """
    Configuration for ``AlpacaDataClient`` instances.

    Parameters
    ----------
    venue : Venue, default ALPACA_VENUE
        The venue for the client.
    api_key : str, optional
        The Alpaca API public key.
        If ``None``, will attempt to read from ALPACA_API_KEY environment variable.
    api_secret : str, optional
        The Alpaca API secret key.
        If ``None``, will attempt to read from ALPACA_API_SECRET environment variable.
    data_feed : AlpacaDataFeed, default AlpacaDataFeed.IEX
        The market data feed subscription level.
        IEX is free tier, SIP is paid tier with real-time data.
    paper_trading : bool, default True
        If the client should connect to paper trading endpoints.
        Defaults to True for safety - set to False for live trading.
    base_url_http : str, optional
        The HTTP client custom endpoint override.
    base_url_ws : str, optional
        The WebSocket client custom endpoint override.
    proxy_url : str, optional
        The proxy URL for HTTP requests.
    http_timeout_secs : PositiveInt or None, default 30
        The timeout (seconds) for HTTP requests.
    update_instruments_interval_mins : PositiveInt or None, default 60
        The interval (minutes) between instrument updates.
        If None, instrument updates are disabled after initial load.

    """

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


class AlpacaExecClientConfig(LiveExecClientConfig, frozen=True):
    """
    Configuration for ``AlpacaExecutionClient`` instances.

    Parameters
    ----------
    venue : Venue, default ALPACA_VENUE
        The venue for the client.
    api_key : str, optional
        The Alpaca API public key.
        If ``None``, will attempt to read from ALPACA_API_KEY environment variable.
    api_secret : str, optional
        The Alpaca API secret key.
        If ``None``, will attempt to read from ALPACA_API_SECRET environment variable.
    paper_trading : bool, default True
        If the client should connect to paper trading endpoints.
        Defaults to True for safety - set to False for live trading.
    base_url_http : str, optional
        The HTTP client custom endpoint override.
    base_url_ws : str, optional
        The WebSocket client custom endpoint override.
    proxy_url : str, optional
        The proxy URL for HTTP requests.
    http_timeout_secs : PositiveInt or None, default 30
        The timeout (seconds) for HTTP requests.
    max_retries : PositiveInt or None, default 3
        The maximum number of times to retry submitting an order on failure.
    retry_delay_secs : float, default 1.0
        The delay (seconds) between order submit retries.

    """

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