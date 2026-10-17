# 独立审计员 2 号报告：订单状态机、事件幂等与对账恢复 (Reconciliation) 审计

- **审计角色**：订单状态机与可靠性独立审计员 (Auditor-02)
- **审查基准**：NautilusTrader 核心状态机规范 + Alpaca Trade Updates 官方事件定义
- **比对官方 Adapter 参考**：BinanceCommonExecutionClient & CoinbaseExecutionClient
- **审计日期**：2026-10-17

---

### 一、订单状态机流转映射核验

| Alpaca 推送事件 (`event`) | 对应 Alpaca 订单状态 | NautilusTrader 目标事件方法 | 状态机是否单调合法 | 审计结论 | 边界说明 |
|---|---|---|---|---|---|
| `new` | `new` / `accepted` | `generate_order_accepted` | 是 | ✅ **合规** | 确认交易所已接单并生成 `venue_order_id`。 |
| `fill` | `filled` | `generate_order_filled` | 是 | ✅ **合规** | 记录累计与单次成交量，防范超额扣减。 |
| `partial_fill` | `partially_filled` | `generate_order_filled` | 是 | ✅ **合规** | 按单次 `qty` 和 `price` 进行增量推进。 |
| `canceled` | `canceled` | `generate_order_canceled` | 是 | ✅ **合规** | 终态事件，冻结保证金解冻。 |
| `expired` | `expired` | `generate_order_expired` | 是 | ✅ **合规** | 终态事件，TIF 过期关闭。 |
| `rejected` | `rejected` | `generate_order_rejected` | 是 | ✅ **合规** | 包含 `reason` 溯源字段。 |
| `pending_cancel` | `pending_cancel` | 内部状态记录 | 是 | ✅ **合规** | 避免竞态下状态倒退。 |

---

### 二、关键高危可靠性场景审计

1. **成交事件幂等性与去重 (Trade Deduplication)**：
   - **风险**：网络重连或服务端重推时，相同成交若多次触发 `generate_order_filled`，会导致头寸与盈亏被严重虚增。
   - **实现核查**：在 `AlpacaExecutionClient._handle_trade_update` 中引入了 `_processed_trade_ids` 集合，依据 `execution_id` 做严格去重保护。
   - **实测证据**：测试用例 `test_trade_update_fill_event_and_deduplication` 注入相同报文，验证第二次被完全忽略，`generate_order_filled.call_count` 恒等于 1。

2. **断线状态恢复 (Post-Reconnect Reconciliation)**：
   - **风险**：网络断开期间如果产生异步成交或被交易所强制取消，仅凭 WebSocket 重连无法感知在途状态变化。
   - **实现核查**：在 `AlpacaTradeUpdatesWebSocketClient` 重连握手成功后，自动回调 `_reconcile_after_reconnect`，并行核对：
     1. 最新账户资金（`AccountState`）；
     2. 交易所全量订单报告（`OrderStatusReport`）；
     3. 交易所全量持仓报告（`PositionStatusReport`）。
   - **实测证据**：测试用例 `test_order_reconciliation_logic` 验证 100% 成功生成对账事件。

---

### 三、审计结论与复核签署
本审计员确认：适配器状态机流转清晰，严格满足幂等去重与网络异常断线后的状态自愈要求。

**审计员签字**：Auditor-02 (Order State Machine & Reliability Auditor)
