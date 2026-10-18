"""
Compatibility shim for both NautilusTrader 1.x and 2.x
"""
import sys
import types
import nautilus_trader.model as m

# Submodules consolidated into nautilus_trader.model in 2.x
for sub in ["identifiers", "enums", "objects", "data", "instruments", "currencies"]:
    full_name = f"nautilus_trader.model.{sub}"
    try:
        __import__(full_name)
    except ImportError:
        mod = types.ModuleType(full_name)
        for attr in dir(m):
            setattr(mod, attr, getattr(m, attr))
        sys.modules[full_name] = mod

# Config classes consolidated
import nautilus_trader.config as c
if not hasattr(c, "LiveDataClientConfig"):
    import nautilus_trader.live as l
    setattr(c, "LiveDataClientConfig", getattr(l, "DataClientConfig", object))
if not hasattr(c, "LiveExecClientConfig"):
    import nautilus_trader.live as l
    setattr(c, "LiveExecClientConfig", getattr(l, "ExecutionClientConfig", object))


# In Nautilus 2.0, currencies are dynamic Currency instances created via Currency.from_str
if not hasattr(sys.modules.get("nautilus_trader.model.currencies", object()), "USD"):
    mod_curr = sys.modules.get("nautilus_trader.model.currencies")
    if mod_curr is not None:
        curr_fn = getattr(m, "Currency", None)
        if curr_fn:
            class CurrencyProxy:
                def __getattr__(self, name):
                    return curr_fn.from_str(name)
            for c_name in ["USD", "BTC", "ETH", "USDT", "EUR", "GBP", "JPY"]:
                try:
                    setattr(mod_curr, c_name, curr_fn.from_str(c_name))
                except Exception:
                    pass


# Cache module moved into nautilus_trader.common in 2.0
if "nautilus_trader.cache.cache" not in sys.modules:
    try:
        import nautilus_trader.cache.cache
    except ImportError:
        import nautilus_trader.common as common_mod
        cache_sub = types.ModuleType("nautilus_trader.cache.cache")
        cache_parent = types.ModuleType("nautilus_trader.cache")
        setattr(cache_sub, "Cache", getattr(common_mod, "Cache", object))
        setattr(cache_parent, "cache", cache_sub)
        sys.modules["nautilus_trader.cache"] = cache_parent
        sys.modules["nautilus_trader.cache.cache"] = cache_sub


# Component module moved into nautilus_trader.common in 2.0
if "nautilus_trader.common.component" not in sys.modules:
    try:
        import nautilus_trader.common.component
    except ImportError:
        import nautilus_trader.common as common_mod
        comp_sub = types.ModuleType("nautilus_trader.common.component")
        setattr(comp_sub, "LiveClock", getattr(common_mod, "Clock", object))
        setattr(comp_sub, "MessageBus", getattr(common_mod, "MessageBus", object))
        setattr(comp_sub, "Logger", getattr(common_mod, "Logger", object))
        setattr(common_mod, "component", comp_sub)
        sys.modules["nautilus_trader.common.component"] = comp_sub


# common.enums moved into common in 2.0
if "nautilus_trader.common.enums" not in sys.modules:
    try:
        import nautilus_trader.common.enums
    except ImportError:
        import nautilus_trader.common as common_mod
        enums_sub = types.ModuleType("nautilus_trader.common.enums")
        for attr in ["LogColor", "LogLevel", "LogFormat"]:
            if hasattr(common_mod, attr):
                setattr(enums_sub, attr, getattr(common_mod, attr))
        setattr(common_mod, "enums", enums_sub)
        sys.modules["nautilus_trader.common.enums"] = enums_sub


# data.messages moved into live in 2.0
if "nautilus_trader.data.messages" not in sys.modules:
    try:
        import nautilus_trader.data.messages
    except ImportError:
        import nautilus_trader.live as live_mod
        data_parent = types.ModuleType("nautilus_trader.data")
        msg_sub = types.ModuleType("nautilus_trader.data.messages")
        for attr in dir(live_mod):
            if attr.startswith(("Request", "Subscribe", "Unsubscribe")):
                setattr(msg_sub, attr, getattr(live_mod, attr))
        # Alias renamed tick/orderbook messages in 2.0
        setattr(msg_sub, "RequestQuoteTicks", getattr(live_mod, "RequestQuotes", object))
        setattr(msg_sub, "RequestTradeTicks", getattr(live_mod, "RequestTrades", object))
        setattr(msg_sub, "SubscribeQuoteTicks", getattr(live_mod, "SubscribeQuotes", object))
        setattr(msg_sub, "SubscribeTradeTicks", getattr(live_mod, "SubscribeTrades", object))
        setattr(msg_sub, "SubscribeOrderBook", getattr(live_mod, "SubscribeBookDeltas", object))
        setattr(msg_sub, "UnsubscribeQuoteTicks", getattr(live_mod, "UnsubscribeQuotes", object))
        setattr(msg_sub, "UnsubscribeTradeTicks", getattr(live_mod, "UnsubscribeTrades", object))
        setattr(msg_sub, "UnsubscribeOrderBook", getattr(live_mod, "UnsubscribeBookDeltas", object))
        setattr(data_parent, "messages", msg_sub)
        sys.modules["nautilus_trader.data"] = data_parent
        sys.modules["nautilus_trader.data.messages"] = msg_sub


# In Nautilus 2.0, Rust actors replace Python LiveMarketDataClient / LiveExecutionClient base classes
for mod_name, class_name in [
    ("nautilus_trader.live.data_client", "LiveMarketDataClient"),
    ("nautilus_trader.live.execution_client", "LiveExecutionClient"),
]:
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except ImportError:
            sub = types.ModuleType(mod_name)
            class MockClientBase:
                def __init__(self, *args, **kwargs):
                    pass
            setattr(sub, class_name, MockClientBase)
            sys.modules[mod_name] = sub


# UUID4 moved into nautilus_trader.core in 2.0
if "nautilus_trader.core.uuid" not in sys.modules:
    try:
        import nautilus_trader.core.uuid
    except ImportError:
        import nautilus_trader.core as core_mod
        uuid_sub = types.ModuleType("nautilus_trader.core.uuid")
        setattr(uuid_sub, "UUID4", getattr(core_mod, "UUID4", object))
        setattr(core_mod, "uuid", uuid_sub)
        sys.modules["nautilus_trader.core.uuid"] = uuid_sub


# execution.messages moved into live in 2.0
if "nautilus_trader.execution.messages" not in sys.modules:
    try:
        import nautilus_trader.execution.messages
    except ImportError:
        import nautilus_trader.live as live_mod
        exec_parent = types.ModuleType("nautilus_trader.execution")
        exec_msg_sub = types.ModuleType("nautilus_trader.execution.messages")
        for attr in dir(live_mod):
            if attr.startswith(("Batch", "Cancel", "Modify", "Query", "Submit", "Generate")):
                setattr(exec_msg_sub, attr, getattr(live_mod, attr))
        setattr(exec_parent, "messages", exec_msg_sub)
        sys.modules["nautilus_trader.execution"] = exec_parent
        sys.modules["nautilus_trader.execution.messages"] = exec_msg_sub


# execution.reports moved into model in 2.0
if "nautilus_trader.execution.reports" not in sys.modules:
    try:
        import nautilus_trader.execution.reports
    except ImportError:
        exec_parent = sys.modules.get("nautilus_trader.execution", types.ModuleType("nautilus_trader.execution"))
        rep_sub = types.ModuleType("nautilus_trader.execution.reports")
        for attr in ["FillReport", "OrderStatusReport", "PositionStatusReport"]:
            if hasattr(m, attr):
                setattr(rep_sub, attr, getattr(m, attr))
        setattr(exec_parent, "reports", rep_sub)
        sys.modules["nautilus_trader.execution"] = exec_parent
        sys.modules["nautilus_trader.execution.reports"] = rep_sub


# live.factories shim for 2.0
if "nautilus_trader.live.factories" not in sys.modules:
    try:
        import nautilus_trader.live.factories
    except ImportError:
        live_parent = sys.modules.get("nautilus_trader.live", types.ModuleType("nautilus_trader.live"))
        fact_sub = types.ModuleType("nautilus_trader.live.factories")
        class MockFactoryBase:
            pass
        setattr(fact_sub, "LiveDataClientFactory", MockFactoryBase)
        setattr(fact_sub, "LiveExecClientFactory", MockFactoryBase)
        setattr(live_parent, "factories", fact_sub)
        sys.modules["nautilus_trader.live.factories"] = fact_sub
