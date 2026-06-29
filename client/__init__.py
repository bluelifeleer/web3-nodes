import importlib
import sys
import types


if "client.main" in sys.modules:
    _main_module = importlib.reload(sys.modules["client.main"])
else:
    _main_module = importlib.import_module("client.main")
from client.main import *  # noqa: F401,F403,E402


class _ClientPackage(types.ModuleType):
    def __getattr__(self, name):
        return getattr(_main_module, name)

    def __setattr__(self, name, value):
        if not name.startswith("__"):
            setattr(_main_module, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _ClientPackage
