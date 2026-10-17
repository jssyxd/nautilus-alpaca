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
Alpaca adapter factory functions.
"""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache

from nautilus_trader.adapters.alpaca.config import AlpacaDataClientConfig
from nautilus_trader.adapters.alpaca.config import AlpacaExecClientConfig
from nautilus_trader.adapters.alpaca.data import AlpacaDataClient
from nautilus_trader.adapters.alpaca.execution import AlpacaExecutionClient
from nautilus_trader.adapters.alpaca.http.client import AlpacaHttpClient
from nautilus_trader.adapters.alpaca.providers import AlpacaInstrumentProvider
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.live.factories import LiveDataClientFactory
from nautilus_trader.live.factories import LiveExecClientFactory


@lru_cache(1)
def get_cached_alpaca_http_client(
    api_key: str | None = None,
    api_secret: str | None = None,
    paper_trading: bool = True,
    timeout_secs: int | None = None,
) -> AlpacaHttpClient:
    """
    Cache and return an Alpaca HTTP client with the given parameters.

    If a cached client with matching parameters already exists, the cached client will be returned.

    Parameters
    ----------
    api_key : str, optional
        The Alpaca API key.
        If ``None`` then will source the `ALPACA_API_KEY` environment variable.
    api_secret : str, optional
        The Alpaca API secret.
        If ``None`` then will source the `ALPACA_API_SECRET` environment variable.
    paper_trading : bool, default True
        If True, use paper trading endpoints. If False, use live trading.
    timeout_secs : int, optional
        The timeout (seconds) for HTTP requests.

    Returns
    -------
    AlpacaHttpClient
        The Alpaca HTTP client instance.

    Raises
    ------
    ValueError
        If API key or secret is not provided and not found in environment.

    """
    # Source credentials from environment if not provided
    if api_key is None:
        api_key = os.environ.get("ALPACA_API_KEY")
    if api_secret is None:
        api_secret = os.environ.get("ALPACA_API_SECRET")

    if not api_key:
        raise ValueError(
            "Alpaca API key not provided and ALPACA_API_KEY environment variable not set",
        )
    if not api_secret:
        raise ValueError(
            "Alpaca API secret not provided and ALPACA_API_SECRET environment variable not set",
        )

    return AlpacaHttpClient(
        api_key=api_key,
        api_secret=api_secret,
        paper_trading=paper_trading,
        timeout_secs=timeout_secs,
    )


@lru_cache(1)
def get_cached_alpaca_instrument_provider(
    client: AlpacaHttpClient,
    clock: LiveClock,
    config: InstrumentProviderConfig | None = None,
) -> AlpacaInstrumentProvider:
    """
    Cache and return an Alpaca instrument provider.

    If a cached provider already exists, then that provider will be returned.

    Parameters
    ----------
    client : AlpacaHttpClient
        The Alpaca HTTP client.
    clock : LiveClock
        The clock for the provider.
    config : InstrumentProviderConfig, optional
        The instrument provider configuration.

    Returns
    -------
    AlpacaInstrumentProvider

    """
    return AlpacaInstrumentProvider(
        client=client,
        clock=clock,
        config=config,
    )


class AlpacaLiveDataClientFactory(LiveDataClientFactory):
    """
    Provides an Alpaca live data client factory.
    """

    @staticmethod
    def create(  # type: ignore
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: AlpacaDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> AlpacaDataClient:
        """
        Create a new Alpaca data client.

        Parameters
        ----------
        loop : asyncio.AbstractEventLoop
            The event loop for the client.
        name : str
            The custom client ID.
        config : AlpacaDataClientConfig
            The client configuration.
        msgbus : MessageBus
            The message bus for the client.
        cache : Cache
            The cache for the client.
        clock : LiveClock
            The clock for the client.

        Returns
        -------
        AlpacaDataClient

        """
        client = get_cached_alpaca_http_client(
            api_key=config.api_key,
            api_secret=config.api_secret,
            paper_trading=config.paper_trading,
            timeout_secs=config.http_timeout_secs,
        )
        provider = get_cached_alpaca_instrument_provider(
            client=client,
            clock=clock,
            config=config.instrument_provider,
        )
        return AlpacaDataClient(
            loop=loop,
            client=client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
            name=name,
        )


class AlpacaLiveExecClientFactory(LiveExecClientFactory):
    """
    Provides an Alpaca live execution client factory.
    """

    @staticmethod
    def create(  # type: ignore
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: AlpacaExecClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> AlpacaExecutionClient:
        """
        Create a new Alpaca execution client.

        Parameters
        ----------
        loop : asyncio.AbstractEventLoop
            The event loop for the client.
        name : str
            The custom client ID.
        config : AlpacaExecClientConfig
            The client configuration.
        msgbus : MessageBus
            The message bus for the client.
        cache : Cache
            The cache for the client.
        clock : LiveClock
            The clock for the client.

        Returns
        -------
        AlpacaExecutionClient

        """
        client = get_cached_alpaca_http_client(
            api_key=config.api_key,
            api_secret=config.api_secret,
            paper_trading=config.paper_trading,
            timeout_secs=config.http_timeout_secs,
        )
        provider = get_cached_alpaca_instrument_provider(
            client=client,
            clock=clock,
            config=config.instrument_provider,
        )
        return AlpacaExecutionClient(
            loop=loop,
            client=client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
            name=name,
        )