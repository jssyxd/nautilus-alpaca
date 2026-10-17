# 独立审计员 3 号报告：WebSocket 长连接、行情订阅与断线重试机制审计

- **审计角色**：WebSocket 通讯与行情数据流控独立审计员 (Auditor-03)
- **审查基准**：Alpaca Streaming Real-time Data & Trade Updates 官方规范 (`wss://stream.data.alpaca.markets`, `wss://paper-api.alpaca.markets/stream`)
- **比对官方 Adapter 参考**：NautilusTrader OKX / Bybit WebSocket Clients
- **审计日期**：2026-10-17

---

### 一、连接生命周期与协议鉴权审计

| 审计维度 | 官方文档规范要求 | 当前适配器实现核查 | 审计结论 |
|---|---|---|---|
| **Trade Updates 协议** | 发送 `{"action": "authenticate", "data": {"key_id": "...", "secret_key": "..."}}`，等待 `authorization` 响应后发送 `listen` | `AlpacaTradeUpdatesWebSocketClient._run_loop` 严格遵循该两阶段握手协议 | ✅ **合规 (Pass)** |
| **Market Data 协议** | 发送 `{"action": "auth", "key": "...", "secret": "..."}`，校验 `[{"T":"success","msg":"authenticated"}]` 响应 | `AlpacaMarketDataWebSocketClient._run_loop` 严格按数组 JSON 校验鉴权 | ✅ **合规 (Pass)** |
| **心跳保活 (Keep-Alive)** | 客户端需保持常规 ping-pong 心跳，防范中间网关静默丢弃连接 | 设置 `websockets.connect(..., ping_interval=20, ping_timeout=20)` | ✅ **合规 (Pass)** |
| **指数退避重连 (Backoff)** | 断线不可高频冲击 API，应按指数增长并设置上限 | 基础延迟 1.0s，每次乘以 2，最高锁定在 30.0s (`_max_reconnect_delay`) | ✅ **合规 (Pass)** |

---

### 二、行情订阅池管理与断线自动重订 (Resubscribe)

1. **动态订阅池跟踪**：
   - 数据客户端支持对 `trades`、`quotes`、`bars` 三类数据源的独立增删。
   - 适配器在内存中维系了 `_subscribed_trades`、`_subscribed_quotes`、`_subscribed_bars` 集合。
2. **重连后全量自动下发**：
   - 官方开发文档强调：WebSocket 连接断开重连后，远端连接通道是全新的，历史订阅全部失效。
   - 实现验证：当重连握手成功后，自动组装全量订阅包 `{"action": "subscribe", "trades": [...], "quotes": [...], "bars": [...]}` 一并下发。
   - **实测证据**：测试用例 `test_market_data_ws_resubscribes_on_reconnect` 验证全量重订逻辑精确触发。
3. **K线 (Bars) 实时数据解析**：
   - **【整改项】** 补齐了对消息类型 `T: "b"`（分钟Bar）的解包与派发，正确构造 Nautilus 标准 `Bar` 对象送入量化引擎。

---

### 三、审计结论与复核签署
本审计员确认：双通道 WebSocket 架构设计清晰，重连防雪崩与动态订阅恢复逻辑完整，具备高可靠生产级网络通信能力。

**审计员签字**：Auditor-03 (WebSocket & Market Data Auditor)
