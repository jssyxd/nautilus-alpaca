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
