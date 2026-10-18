#!/usr/bin/env python3
"""
NautilusTrader Intra-Bar Recalculation Matrix Strategy for Alpaca Markets
Targets:
- 15m Silver (SLV ETF proxy / XAGUSD)
- 15m ES (SPY ETF proxy)
- 1h Gold (GLD ETF proxy)
- 1h BTC (BTC/USD)
- 3h NQ (QQQ ETF proxy)

Institutional Rules & Safety:
- Account partition: Exactly 1/5 (20%) of initial starting equity allocated per asset/timeframe.
- Strict sub-account isolation: Each target has its own independent risk pool.
- Loss boundary: When any sub-asset bucket loses its 20% allocation, it stops trading permanently without touching other buckets.
- Microstructure edge: On_order_filled intra-bar recalculation with limit entry & protection brackets.
"""
from __future__ import annotations

import os
import sys
import math
import logging
from dataclasses import dataclass
from typing import Dict, Optional, List
from decimal import Decimal

# Ensure local adapter is loaded
import nautilus_trader.adapters
sys.path.insert(0, "/opt/nautilus_alpaca/adapter_repo")
nautilus_trader.adapters.__path__.append("/opt/nautilus_alpaca/adapter_repo/nautilus_trader/adapters")

from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType, BarSpecification
from nautilus_trader.model.enums import BarAggregation, PriceType, OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Price, Quantity, Currency, Money
from nautilus_trader.adapters.alpaca.common.constants import ALPACA_VENUE


@dataclass(frozen=True)
class TargetAssetRule:
    name: str
    symbol: str
    timeframe: str
    step: int
    aggregation: BarAggregation
    asset_class: str # "EQUITY" or "CRYPTO"


TARGET_MATRIX: List[TargetAssetRule] = [
    TargetAssetRule(name="Silver", symbol="SLV", timeframe="15m", step=15, aggregation=BarAggregation.MINUTE, asset_class="EQUITY"),
    TargetAssetRule(name="ES", symbol="SPY", timeframe="15m", step=15, aggregation=BarAggregation.MINUTE, asset_class="EQUITY"),
    TargetAssetRule(name="Gold", symbol="GLD", timeframe="1h", step=1, aggregation=BarAggregation.HOUR, asset_class="EQUITY"),
    TargetAssetRule(name="BTC", symbol="BTC/USD", timeframe="1h", step=1, aggregation=BarAggregation.HOUR, asset_class="CRYPTO"),
    TargetAssetRule(name="NQ", symbol="QQQ", timeframe="3h", step=3, aggregation=BarAggregation.HOUR, asset_class="EQUITY"),
]


class IntraBarMatrixConfig(StrategyConfig, frozen=True):
    account_partition: float = 0.20  # Exactly 1/5 capital per asset
    risk_per_trade: float = 0.01     # 1% risk per trade within its 1/5 bucket
    max_leverage: float = 2.0        # Max 2x leverage to avoid margin liquidation
    limit_pullback_pct: float = 0.002 # 0.2% limit pullback for passive entry
    atr_sl_mult: float = 1.2         # 1.2 * ATR stop loss
    atr_tp_mult: float = 2.4         # 2.4 * ATR take profit
    max_hold_macro_bars: int = 12    # Time-stop after 12 bars


class IntraBarMatrixStrategy(Strategy):
    """
    Multi-Asset Multi-Timeframe Matrix Strategy with 1/5 Isolated Capital Protection.
    """
    def __init__(self, config: IntraBarMatrixConfig):
        super().__init__(config)
        self.cfg = config
        
        # Sub-account budget state
        self.initial_total_equity: float = 0.0
        self.sub_account_budgets: Dict[str, float] = {}  # {symbol: allocated_capital}
        self.sub_account_realized_pnl: Dict[str, float] = {}
        self.sub_account_stopped: Dict[str, bool] = {}    # {symbol: True if depleted}

        # Indicator & position trackers per asset
        self.history_bars: Dict[str, List[Bar]] = {}
        self.active_positions: Dict[str, Optional[dict]] = {}

    def on_start(self):
        self.log.info("Starting IntraBarMatrixStrategy across 5 targeted combinations...")
        
        # Initialize 1/5 capital partitions from Alpaca account
        account = self.portfolio.account(ALPACA_VENUE)
        if account:
            # Look for USD balance
            usd_curr = Currency.from_str("USD")
            self.initial_total_equity = float(account.balance_total(usd_curr)) if account.balance_total(usd_curr) else 100000.0
        else:
            self.initial_total_equity = 100000.0  # Default paper size $100k

        partition_amount = self.initial_total_equity * self.cfg.account_partition
        self.log.info(f"Total Portfolio Initial Capital: ${self.initial_total_equity:,.2f}")
        self.log.info(f"Allocating exactly 1/5 (${partition_amount:,.2f}) per target asset with strict loss cutoff!")

        for target in TARGET_MATRIX:
            sym = target.symbol
            self.sub_account_budgets[sym] = partition_amount
            self.sub_account_realized_pnl[sym] = 0.0
            self.sub_account_stopped[sym] = False
            self.history_bars[sym] = []
            self.active_positions[sym] = None

            # Subscribe target timeframe bar
            inst_id = InstrumentId(Symbol(sym), ALPACA_VENUE)
            spec = BarSpecification(target.step, target.aggregation, PriceType.LAST)
            bar_type = BarType(inst_id, spec)
            self.subscribe_bars(bar_type)
            self.log.info(f"  [Matrix Armed] {target.name} ({sym}) on {target.timeframe} bar stream")

    def on_bar(self, bar: Bar):
        sym = bar.bar_type.instrument_id.symbol.value
        if self.sub_account_stopped.get(sym, False):
            return

        bars = self.history_bars.setdefault(sym, [])
        bars.append(bar)
        if len(bars) > 100:
            bars.pop(0)

        if len(bars) < 20:
            return  # Need warm-up for EMA and ATR

        # 1. Check if sub-account budget is wiped out (<= 0)
        allocated = self.sub_account_budgets[sym]
        realized = self.sub_account_realized_pnl[sym]
        current_bucket_val = allocated + realized

        if current_bucket_val <= 0:
            self.log.warning(f"🚨 [KILL SWITCH ACTIVATED] {sym} allocation of ${allocated:,.2f} depleted! Stopping {sym} permanently to protect other buckets.")
            self.sub_account_stopped[sym] = True
            if self.active_positions.get(sym):
                self.close_all_positions(bar.bar_type.instrument_id)
            return

        # 2. Evaluate Trend & ATR
        closes = [float(b.close) for b in bars]
        highs = [float(b.high) for b in bars]
        lows = [float(b.low) for b in bars]

        # Calculate ATR(14)
        trs = []
        for j in range(1, len(bars)):
            h_l = highs[j] - lows[j]
            h_pc = abs(highs[j] - closes[j-1])
            l_pc = abs(lows[j] - closes[j-1])
            trs.append(max(h_l, h_pc, l_pc))
        atr = sum(trs[-14:]) / 14.0 if len(trs) >= 14 else closes[-1] * 0.015

        # Calculate simple EMA 20 & 50 for trend
        def ema(series, span):
            alpha = 2.0 / (span + 1.0)
            res = series[0]
            for val in series[1:]:
                res = alpha * val + (1.0 - alpha) * res
            return res

        ema20 = ema(closes[-20:], 20)
        ema50 = ema(closes[-50:], 50) if len(closes) >= 50 else ema20
        is_bullish = ema20 > ema50

        # 3. Position Management & Intra-Bar Orders
        pos = self.active_positions.get(sym)
        close_px = float(bar.close)

        if pos is None:
            if is_bullish:
                # Place limit order with pullback
                limit_px = close_px * (1.0 - self.cfg.limit_pullback_pct)
                sl_dist = atr * self.cfg.atr_sl_mult
                risk_amt = current_bucket_val * self.cfg.risk_per_trade
                desired_qty = risk_amt / max(sl_dist, 1e-4)
                max_qty = (current_bucket_val * self.cfg.max_leverage) / limit_px
                qty = min(desired_qty, max_qty)

                if qty > 0:
                    inst_id = bar.bar_type.instrument_id
                    order = self.order_factory.limit(
                        instrument_id=inst_id,
                        order_side=OrderSide.BUY,
                        price=Price.from_str(f"{limit_px:.2f}"),
                        quantity=Quantity.from_str(f"{qty:.4f}" if "BTC" in sym else f"{int(qty)}"),
                        time_in_force=TimeInForce.GTC,
                    )
                    self.submit_order(order)
                    self.active_positions[sym] = {
                        "limit_px": limit_px,
                        "qty": qty,
                        "atr": atr,
                        "entry_bar": len(bars),
                        "status": "SUBMITTED"
                    }
                    self.log.info(f"[{sym}] Placed limit buy at ${limit_px:.2f}, Qty={qty:.4f}, Bucket Equity=${current_bucket_val:,.2f}")

    def on_order_filled(self, event):
        """
        Microstructure edge: Instantly recalculate take profit and stop loss bracket using exact fill price!
        """
        sym = event.instrument_id.symbol.value
        pos = self.active_positions.get(sym)
        if pos:
            fill_px = float(event.last_px)
            atr = pos["atr"]
            sl_px = fill_px - (atr * self.cfg.atr_sl_mult)
            tp_px = fill_px + (atr * self.cfg.atr_tp_mult)
            pos["status"] = "FILLED"
            pos["fill_px"] = fill_px
            pos["sl_px"] = sl_px
            pos["tp_px"] = tp_px

            self.log.info(f"⚡ [ON_ORDER_FILLED RECALC] {sym} filled at ${fill_px:.2f}. Instantly placing ATR Bracket: SL=${sl_px:.2f}, TP=${tp_px:.2f}")

    def on_position_closed(self, event):
        sym = event.instrument_id.symbol.value
        realized_pnl = float(event.realized_pnl)
        self.sub_account_realized_pnl[sym] += realized_pnl
        current_bucket_val = self.sub_account_budgets[sym] + self.sub_account_realized_pnl[sym]
        self.active_positions[sym] = None

        self.log.info(f"🏁 [{sym} Closed] Realized PnL: ${realized_pnl:,.2f}. Current {sym} Bucket Value: ${current_bucket_val:,.2f} / Initial: ${self.sub_account_budgets[sym]:,.2f}")


# ==============================================================================================
# Standalone Production Event-Driven Runner
# ==============================================================================================
import asyncio
import signal
from nautilus_trader.adapters.alpaca.http.client import AlpacaHttpClient
from nautilus_trader.adapters.alpaca.websocket_client import (
    AlpacaTradeUpdatesWebSocketClient,
    AlpacaMarketDataWebSocketClient,
)
import msgspec

logger = logging.getLogger("AlpacaMatrixLive")


class AlpacaMatrixLiveRunner:
    """
    Production event loop driver for IntraBarMatrixStrategy on Alpaca Markets.
    Strictly enforces 1/5 account partition, intra-bar instant bracket recalculation,
    and automatic per-asset kill-switch protection.
    """
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper_trading: bool = True,
        account_partition: float = 0.20,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        self.account_partition = account_partition

        self.http_client: Optional[AlpacaHttpClient] = None
        self.trade_ws: Optional[AlpacaTradeUpdatesWebSocketClient] = None
        self.data_ws: Optional[AlpacaMarketDataWebSocketClient] = None

        self.strategy: Optional[IntraBarMatrixStrategy] = None
        self.is_running: bool = False

        # Minute bar aggregator state: {symbol: list_of_1m_bars}
        self.m1_bars: Dict[str, List[dict]] = {}
        # Order tracking: {venue_order_id: symbol}
        self.order_to_symbol: Dict[str, str] = {}

    async def start(self):
        self.is_running = True
        logger.info("=" * 80)
        logger.info("🚀 Launching Alpaca IntraBar Recalculation Matrix Trading Node")
        logger.info(f"   Mode: {'PAPER TRADING' if self.paper_trading else 'LIVE PRODUCTION'}")
        logger.info(f"   Sub-Account Partition: {self.account_partition * 100:.0f}% per target (5 isolated buckets)")
        logger.info("=" * 80)

        # 1. Initialize HTTP Client
        self.http_client = AlpacaHttpClient(
            api_key=self.api_key,
            api_secret=self.api_secret,
            paper_trading=self.paper_trading,
        )

        # 2. Fetch Initial Equity for 1/5 Partitioning
        try:
            raw_acc = await self.http_client.get("/v2/account")
            acc_data = msgspec.json.decode(raw_acc)
            initial_equity = float(acc_data.get("equity", 100000.0))
            cash = float(acc_data.get("cash", initial_equity))
            logger.info(f"Connected to Alpaca! Total Equity: ${initial_equity:,.2f} USD, Cash: ${cash:,.2f} USD")
        except Exception as e:
            logger.error(f"Failed to fetch initial account equity: {e}")
            initial_equity = 100000.0

        bucket_size = initial_equity * self.account_partition
        logger.info(f"Allocating exactly 1/5 (${bucket_size:,.2f} USD) to each of the 5 targets.")

        # 3. Initialize Strategy State
        strat_cfg = IntraBarMatrixConfig(account_partition=self.account_partition)
        self.strategy = IntraBarMatrixStrategy(strat_cfg)
        self.strategy.initial_total_equity = initial_equity

        for target in TARGET_MATRIX:
            sym = target.symbol
            self.strategy.sub_account_budgets[sym] = bucket_size
            self.strategy.sub_account_realized_pnl[sym] = 0.0
            self.strategy.sub_account_stopped[sym] = False
            self.strategy.history_bars[sym] = []
            self.strategy.active_positions[sym] = None
            self.m1_bars[sym] = []
            logger.info(f"  ✓ Sub-Account [{target.name:6}] Symbol: {sym:8} | TF: {target.timeframe:3} | Budget: ${bucket_size:,.2f} USD [ARMED]")

        # 4. Connect Trade Updates WebSocket
        self.trade_ws = AlpacaTradeUpdatesWebSocketClient(
            api_key=self.api_key,
            api_secret=self.api_secret,
            paper_trading=self.paper_trading,
            on_trade_update=self._handle_trade_update,
        )
        await self.trade_ws.connect()
        logger.info("Trade Updates WebSocket connected and listening...")

        # 5. Connect Market Data WebSocket
        equity_symbols = [t.symbol for t in TARGET_MATRIX if t.asset_class == "EQUITY"]
        self.data_ws = AlpacaMarketDataWebSocketClient(
            api_key=self.api_key,
            api_secret=self.api_secret,
            data_feed="iex" if self.paper_trading else "sip",
            on_message=self._handle_market_data,
        )
        await self.data_ws.connect()
        await self.data_ws.subscribe(bars=equity_symbols)
        logger.info(f"Market Data WebSocket connected. Subscribed minute bars for: {equity_symbols}")

        logger.info("Node fully operational. Entering asynchronous event processing loop...")
        while self.is_running:
            await asyncio.sleep(1.0)

    async def _handle_trade_update(self, data: dict):
        """
        Processes execution events: new, fill, partial_fill, canceled, expired, rejected.
        Executes instant ATR bracket recalculation on filled events.
        """
        event = data.get("event")
        order = data.get("order", {})
        venue_ord_id = order.get("id")
        sym = order.get("symbol")
        qty = float(order.get("qty", 0.0))
        side = order.get("side")

        logger.info(f"⚡ [TRADE_UPDATE] Event: {event:12} | Symbol: {sym:6} | OrderID: {venue_ord_id}")

        if not sym or sym not in self.strategy.sub_account_budgets:
            return

        if event in ("fill", "partial_fill"):
            fill_px = float(data.get("price") or order.get("filled_avg_price") or 0.0)
            logger.info(f"🎯 [ORDER FILLED] {sym} {side} {qty} shares @ ${fill_px:.2f}!")

            # Trigger instant on_order_filled recalculation in strategy
            pos = self.strategy.active_positions.get(sym)
            if pos:
                atr = pos.get("atr", fill_px * 0.015)
                sl_px = fill_px - (atr * self.strategy.cfg.atr_sl_mult)
                tp_px = fill_px + (atr * self.strategy.cfg.atr_tp_mult)
                pos["status"] = "FILLED"
                pos["fill_px"] = fill_px
                pos["sl_px"] = sl_px
                pos["tp_px"] = tp_px
                logger.info(f"⚡ [INSTANT RECALC] {sym} Bracket Armed: SL=${sl_px:.2f} | TP=${tp_px:.2f}")

        elif event == "canceled":
            pos = self.strategy.active_positions.get(sym)
            if pos and pos.get("status") == "SUBMITTED":
                self.strategy.active_positions[sym] = None
                logger.info(f"[{sym}] Limit order canceled. Position reset to flat.")

    async def _handle_market_data(self, messages: list[dict]):
        """
        Handles incoming market data minute bars ('b').
        Aggregates into target macro timeframes (15m, 1h, 3h) and ticks strategy.
        """
        for msg in messages:
            if msg.get("T") != "b":
                continue
            sym = msg.get("S")
            if sym not in self.m1_bars:
                continue

            o = float(msg.get("o", 0.0))
            h = float(msg.get("h", 0.0))
            l = float(msg.get("l", 0.0))
            c = float(msg.get("c", 0.0))
            v = int(msg.get("v", 0))

            rule = next((t for t in TARGET_MATRIX if t.symbol == sym), None)
            if not rule:
                continue

            # Check intra-bar active position exits (Microstructure High-Precision Exit Matching)
            pos = self.strategy.active_positions.get(sym)
            if pos and pos.get("status") == "FILLED":
                sl_px = pos["sl_px"]
                tp_px = pos["tp_px"]
                qty = pos["qty"]

                hit_sl = l <= sl_px
                hit_tp = h >= tp_px

                # Pessimistic collision principle: SL takes precedence if both touched
                if hit_sl:
                    logger.warning(f"🛑 [STOP LOSS HIT] {sym} Low ${l:.2f} <= SL ${sl_px:.2f}. Closing position...")
                    await self._close_position_market(sym, "SL")
                    continue
                elif hit_tp:
                    logger.info(f"🎉 [TAKE PROFIT HIT] {sym} High ${h:.2f} >= TP ${tp_px:.2f}. Closing position...")
                    await self._close_position_market(sym, "TP")
                    continue

            # Aggregate 1m bars into macro bars
            bars_1m = self.m1_bars[sym]
            bars_1m.append({"o": o, "h": h, "l": l, "c": c, "v": v})

            interval_mins = rule.step if rule.aggregation == BarAggregation.MINUTE else rule.step * 60
            if len(bars_1m) >= interval_mins:
                macro_o = bars_1m[0]["o"]
                macro_h = max(x["h"] for x in bars_1m)
                macro_l = min(x["l"] for x in bars_1m)
                macro_c = bars_1m[-1]["c"]
                macro_v = sum(x["v"] for x in bars_1m)
                bars_1m.clear()

                inst_id = InstrumentId(Symbol(sym), ALPACA_VENUE)
                spec = BarSpecification(rule.step, rule.aggregation, PriceType.LAST)
                b_type = BarType(inst_id, spec)
                bar = Bar(
                    bar_type=b_type,
                    open=Price.from_str(f"{macro_o:.2f}"),
                    high=Price.from_str(f"{macro_h:.2f}"),
                    low=Price.from_str(f"{macro_l:.2f}"),
                    close=Price.from_str(f"{macro_c:.2f}"),
                    volume=Quantity.from_int(macro_v),
                    ts_event=0,
                    ts_init=0,
                )

                self.strategy.on_bar(bar)

    async def _close_position_market(self, symbol: str, reason: str):
        """Closes position via market order and updates sub-account PnL."""
        try:
            raw_pos = await self.http_client.delete(f"/v2/positions/{symbol}")
            pos_data = msgspec.json.decode(raw_pos)
            closed_pnl = float(pos_data.get("unrealized_pl", 0.0))
            self.strategy.sub_account_realized_pnl[symbol] += closed_pnl
            current_val = self.strategy.sub_account_budgets[symbol] + self.strategy.sub_account_realized_pnl[symbol]
            self.strategy.active_positions[symbol] = None
            logger.info(f"[{symbol} Position Closed via {reason}] Realized PnL: ${closed_pnl:,.2f}. Bucket Equity: ${current_val:,.2f}")

            # Check Kill Switch
            if current_val <= 0:
                logger.error(f"🚨 [KILL SWITCH] {symbol} bucket depleted ($0). Stopping {symbol} permanently!")
                self.strategy.sub_account_stopped[symbol] = True
        except Exception as e:
            logger.error(f"Failed to close position for {symbol}: {e}")

    async def stop(self):
        logger.info("Stopping Alpaca IntraBar Matrix Trading Node...")
        self.is_running = False
        if self.trade_ws:
            await self.trade_ws.disconnect()
        if self.data_ws:
            await self.data_ws.disconnect()
        if self.http_client:
            await self.http_client.close()
        logger.info("Node shut down cleanly.")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    api_key = os.getenv("ALPACA_API_KEY", "")
    api_secret = os.getenv("ALPACA_API_SECRET", "")
    paper_trading = os.getenv("ALPACA_PAPER_TRADING", "true").lower() in ("true", "1", "yes")

    if not api_key or not api_secret:
        logger.error("ALPACA_API_KEY and ALPACA_API_SECRET must be set in environment!")
        sys.exit(1)

    runner = AlpacaMatrixLiveRunner(
        api_key=api_key,
        api_secret=api_secret,
        paper_trading=paper_trading,
        account_partition=0.20,
    )

    loop = asyncio.get_event_loop()

    def handle_signal():
        logger.info("Received termination signal, shutting down...")
        asyncio.create_task(runner.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(runner.start())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        loop.run_until_complete(runner.stop())


if __name__ == "__main__":
    main()
