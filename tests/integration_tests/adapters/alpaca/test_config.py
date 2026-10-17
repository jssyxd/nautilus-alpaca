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
Tests for Alpaca adapter configuration.
"""

from nautilus_trader.adapters.alpaca import ALPACA_VENUE
from nautilus_trader.adapters.alpaca import AlpacaAssetClass
from nautilus_trader.adapters.alpaca import AlpacaDataClientConfig
from nautilus_trader.adapters.alpaca import AlpacaDataFeed
from nautilus_trader.adapters.alpaca import AlpacaExecClientConfig
from nautilus_trader.adapters.alpaca import AlpacaInstrumentProviderConfig


class TestAlpacaVenue:
    """
    Tests for ALPACA_VENUE constant.
    """

    def test_venue_value(self):
        assert ALPACA_VENUE.value == "ALPACA"


class TestAlpacaAssetClass:
    """
    Tests for AlpacaAssetClass enum.
    """

    def test_us_equity_value(self):
        assert AlpacaAssetClass.US_EQUITY.value == "us_equity"

    def test_crypto_value(self):
        assert AlpacaAssetClass.CRYPTO.value == "crypto"

    def test_option_value(self):
        assert AlpacaAssetClass.OPTION.value == "option"


class TestAlpacaDataFeed:
    """
    Tests for AlpacaDataFeed enum.
    """

    def test_iex_value(self):
        assert AlpacaDataFeed.IEX.value == "iex"

    def test_sip_value(self):
        assert AlpacaDataFeed.SIP.value == "sip"


class TestAlpacaDataClientConfig:
    """
    Tests for AlpacaDataClientConfig.
    """

    def test_default_config(self):
        config = AlpacaDataClientConfig()
        assert config.venue == ALPACA_VENUE
        assert config.paper_trading is True
        assert config.data_feed == AlpacaDataFeed.IEX

    def test_config_with_credentials(self):
        config = AlpacaDataClientConfig(
            api_key="test_key",
            api_secret="test_secret",
            paper_trading=False,
            data_feed=AlpacaDataFeed.SIP,
        )
        assert config.api_key == "test_key"
        assert config.api_secret == "test_secret"
        assert config.paper_trading is False
        assert config.data_feed == AlpacaDataFeed.SIP


class TestAlpacaExecClientConfig:
    """
    Tests for AlpacaExecClientConfig.
    """

    def test_default_config(self):
        config = AlpacaExecClientConfig()
        assert config.venue == ALPACA_VENUE
        assert config.paper_trading is True

    def test_config_with_credentials(self):
        config = AlpacaExecClientConfig(
            api_key="test_key",
            api_secret="test_secret",
            paper_trading=False,
        )
        assert config.api_key == "test_key"
        assert config.api_secret == "test_secret"
        assert config.paper_trading is False


class TestAlpacaInstrumentProviderConfig:
    """
    Tests for AlpacaInstrumentProviderConfig.
    """

    def test_default_config(self):
        config = AlpacaInstrumentProviderConfig()
        assert config.asset_classes is None

    def test_config_with_asset_classes(self):
        config = AlpacaInstrumentProviderConfig(
            asset_classes=frozenset({AlpacaAssetClass.US_EQUITY}),
        )
        assert AlpacaAssetClass.US_EQUITY in config.asset_classes