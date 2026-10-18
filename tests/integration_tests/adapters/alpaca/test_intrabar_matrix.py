import pytest
from unittest.mock import MagicMock
from decimal import Decimal

from nautilus_trader.adapters.alpaca.intrabar_matrix_live import (
    IntraBarMatrixStrategy,
    IntraBarMatrixConfig,
    TARGET_MATRIX,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.data import Bar, BarType, BarSpecification
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.objects import Price, Quantity

class TestIntraBarMatrixPartitionAndSafety:

    def test_sub_account_partition_math(self):
        cfg = IntraBarMatrixConfig(account_partition=0.20)
        strat = MagicMock(spec=IntraBarMatrixStrategy)
        strat.cfg = cfg
        strat.initial_total_equity = 100000.0
        strat.sub_account_budgets = {}
        strat.sub_account_realized_pnl = {}
        strat.sub_account_stopped = {}
        strat.history_bars = {}
        strat.active_positions = {}
        strat.log = MagicMock()
        strat.portfolio = MagicMock()
        strat.portfolio.account.return_value = None

        IntraBarMatrixStrategy.on_start(strat)

        assert len(strat.sub_account_budgets) == 5
        for target in TARGET_MATRIX:
            sym = target.symbol
            assert strat.sub_account_budgets[sym] == 20000.0  # Exactly 1/5
            assert strat.sub_account_realized_pnl[sym] == 0.0
            assert strat.sub_account_stopped[sym] is False

    def test_kill_switch_trigger_on_budget_depletion(self):
        cfg = IntraBarMatrixConfig(account_partition=0.20)
        strat = MagicMock(spec=IntraBarMatrixStrategy)
        strat.cfg = cfg
        strat.sub_account_budgets = {"SLV": 20000.0, "SPY": 20000.0}
        strat.sub_account_realized_pnl = {"SLV": -20001.0, "SPY": -500.0}
        strat.sub_account_stopped = {"SLV": False, "SPY": False}
        strat.history_bars = {"SLV": []}
        strat.active_positions = {"SLV": None}
        strat.log = MagicMock()

        inst_id = InstrumentId(Symbol("SLV"), Venue("ALPACA"))
        spec = BarSpecification(15, BarAggregation.MINUTE, PriceType.LAST)
        bar_type = BarType(inst_id, spec)
        bar = Bar(
            bar_type=bar_type,
            open=Price.from_str("30.00"),
            high=Price.from_str("30.50"),
            low=Price.from_str("29.80"),
            close=Price.from_str("30.20"),
            volume=Quantity.from_int(100),
            ts_event=1700000000000000000,
            ts_init=1700000000000000000,
        )

        for _ in range(25):
            IntraBarMatrixStrategy.on_bar(strat, bar)

        # SLV depleted, stopped permanently
        assert strat.sub_account_stopped["SLV"] is True
        # SPY remains operational, strictly isolated
        assert strat.sub_account_stopped["SPY"] is False
