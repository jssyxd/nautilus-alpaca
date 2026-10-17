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
Alpaca adapter enumeration types.
"""

from enum import Enum


class AlpacaAssetClass(Enum):
    """
    Alpaca asset class types.
    """

    US_EQUITY = "us_equity"
    CRYPTO = "crypto"
    OPTION = "option"


class AlpacaDataFeed(Enum):
    """
    Alpaca market data feed subscription levels.

    IEX is the free tier (may be delayed for some data). SIP is the paid tier with real-
    time consolidated data.

    """

    IEX = "iex"
    SIP = "sip"


class AlpacaOrderSide(Enum):
    """
    Alpaca order side.
    """

    BUY = "buy"
    SELL = "sell"


class AlpacaOrderType(Enum):
    """
    Alpaca order types.
    """

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"


class AlpacaTimeInForce(Enum):
    """
    Alpaca time-in-force options for orders.
    """

    DAY = "day"
    GTC = "gtc"
    OPG = "opg"
    CLS = "cls"
    IOC = "ioc"
    FOK = "fok"


class AlpacaOrderStatus(Enum):
    """
    Alpaca order status values.
    """

    NEW = "new"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    PENDING_CANCEL = "pending_cancel"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PENDING_REPLACE = "pending_replace"
    REPLACED = "replaced"
    PENDING_NEW = "pending_new"
    STOPPED = "stopped"
    SUSPENDED = "suspended"
    CALCULATED = "calculated"
    HELD = "held"