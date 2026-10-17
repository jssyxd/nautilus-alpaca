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
Tests for Alpaca instrument provider.
"""

import pkgutil

import pytest

from nautilus_trader.adapters.alpaca import AlpacaAssetClass
from nautilus_trader.adapters.alpaca.common.constants import ALPACA_VENUE
from nautilus_trader.adapters.alpaca.config import AlpacaInstrumentProviderConfig
from nautilus_trader.adapters.alpaca.http.client import AlpacaHttpClient
from nautilus_trader.adapters.alpaca.providers import AlpacaInstrumentProvider
from nautilus_trader.common.component import LiveClock
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.instruments import OptionContract


class TestAlpacaInstrumentProvider:
    """
    Tests for AlpacaInstrumentProvider.
    """

    def setup_method(self):
        self.clock = LiveClock()

    @pytest.mark.asyncio
    async def test_load_crypto_assets(
        self,
        alpaca_http_client,
        live_logger,
        monkeypatch,
    ):
        """
        Test loading cryptocurrency assets.
        """
        # Arrange: prepare data for monkey patch
        crypto_response = pkgutil.get_data(
            package="tests.integration_tests.adapters.alpaca.resources.http_responses",
            resource="http_assets_crypto.json",
        )

        async def mock_get(self, path: str, params: dict | None = None) -> bytes:
            if "asset_class=crypto" in path or (params and params.get("asset_class") == "crypto"):
                return crypto_response
            return b"[]"

        monkeypatch.setattr(AlpacaHttpClient, "get", mock_get)

        config = AlpacaInstrumentProviderConfig(
            asset_classes=frozenset({AlpacaAssetClass.CRYPTO}),
        )

        provider = AlpacaInstrumentProvider(
            client=alpaca_http_client,
            clock=self.clock,
            config=config,
        )

        # Act
        await provider.load_all_async()

        # Assert
        assert provider.count == 2

        btc = provider.find(InstrumentId(Symbol("BTC/USD"), ALPACA_VENUE))
        assert btc is not None
        assert isinstance(btc, CurrencyPair)
        assert btc.base_currency.code == "BTC"
        assert btc.quote_currency.code == "USD"

        eth = provider.find(InstrumentId(Symbol("ETH/USD"), ALPACA_VENUE))
        assert eth is not None
        assert isinstance(eth, CurrencyPair)
        assert eth.base_currency.code == "ETH"
        assert eth.quote_currency.code == "USD"

    @pytest.mark.asyncio
    async def test_load_option_contracts(
        self,
        alpaca_http_client,
        live_logger,
        monkeypatch,
    ):
        """
        Test loading option contracts.
        """
        # Arrange: prepare data for monkey patch
        options_response = pkgutil.get_data(
            package="tests.integration_tests.adapters.alpaca.resources.http_responses",
            resource="http_option_contracts.json",
        )

        async def mock_get(self, path: str, params: dict | None = None) -> bytes:
            if "/v2/options/contracts" in path:
                return options_response
            return b"[]"

        monkeypatch.setattr(AlpacaHttpClient, "get", mock_get)

        config = AlpacaInstrumentProviderConfig(
            asset_classes=frozenset({AlpacaAssetClass.OPTION}),
            option_underlying_symbols=frozenset({"AAPL"}),
        )

        provider = AlpacaInstrumentProvider(
            client=alpaca_http_client,
            clock=self.clock,
            config=config,
        )

        # Act
        await provider.load_all_async()

        # Assert
        assert provider.count == 2

        call_option = provider.find(InstrumentId(Symbol("AAPL250117C00200000"), ALPACA_VENUE))
        assert call_option is not None
        assert isinstance(call_option, OptionContract)

        put_option = provider.find(InstrumentId(Symbol("AAPL250117P00200000"), ALPACA_VENUE))
        assert put_option is not None
        assert isinstance(put_option, OptionContract)

    @pytest.mark.asyncio
    async def test_crypto_symbol_format_conversion(
        self,
        alpaca_http_client,
        live_logger,
        monkeypatch,
    ):
        """
        Test that crypto symbols are correctly converted from BTCUSD to BTC/USD.
        """
        crypto_response = pkgutil.get_data(
            package="tests.integration_tests.adapters.alpaca.resources.http_responses",
            resource="http_assets_crypto.json",
        )

        async def mock_get(self, path: str, params: dict | None = None) -> bytes:
            return crypto_response

        monkeypatch.setattr(AlpacaHttpClient, "get", mock_get)

        config = AlpacaInstrumentProviderConfig(
            asset_classes=frozenset({AlpacaAssetClass.CRYPTO}),
        )

        provider = AlpacaInstrumentProvider(
            client=alpaca_http_client,
            clock=self.clock,
            config=config,
        )

        # Act
        await provider.load_all_async()

        # Assert - symbols should be in BTC/USD format, not BTCUSD
        btc = provider.find(InstrumentId(Symbol("BTC/USD"), ALPACA_VENUE))
        assert btc is not None
        assert btc.id.symbol.value == "BTC/USD"

        # Should NOT find with Alpaca's raw format
        btc_raw = provider.find(InstrumentId(Symbol("BTCUSD"), ALPACA_VENUE))
        assert btc_raw is None