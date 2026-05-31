__version__ = "1.1.0"

try:
    from pretix_enablebanking.apps import PluginApp

    PretixPluginMeta = PluginApp.PretixPluginMeta
except ImportError:
    pass
