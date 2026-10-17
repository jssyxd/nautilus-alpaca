"""
Compatibility shim for both NautilusTrader 1.x and 2.x
"""
import sys
import types
import nautilus_trader.model as m

# Submodules consolidated into nautilus_trader.model in 2.x
for sub in ["identifiers", "enums", "objects", "data", "instruments"]:
    full_name = f"nautilus_trader.model.{sub}"
    if full_name not in sys.modules:
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
