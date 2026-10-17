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
Alpaca adapter constants.
"""

from nautilus_trader.model.identifiers import Venue


ALPACA_VENUE = Venue("ALPACA")

# Trading API URLs
ALPACA_TRADING_URL_LIVE = "https://api.alpaca.markets"
ALPACA_TRADING_URL_PAPER = "https://paper-api.alpaca.markets"

# Market Data API URL
ALPACA_DATA_URL = "https://data.alpaca.markets"

# WebSocket URLs for market data
ALPACA_WS_STOCKS_IEX = "wss://stream.data.alpaca.markets/v2/iex"
ALPACA_WS_STOCKS_SIP = "wss://stream.data.alpaca.markets/v2/sip"
ALPACA_WS_CRYPTO = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"
ALPACA_WS_OPTIONS = "wss://stream.data.alpaca.markets/v1beta1/options"

# WebSocket URLs for trading updates
ALPACA_WS_TRADING_LIVE = "wss://api.alpaca.markets/stream"
ALPACA_WS_TRADING_PAPER = "wss://paper-api.alpaca.markets/stream"