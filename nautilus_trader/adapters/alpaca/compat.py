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
