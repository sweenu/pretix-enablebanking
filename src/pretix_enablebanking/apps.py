from django.utils.translation import gettext_lazy

from . import __version__

try:
    from pretix.base.plugins import PLUGIN_LEVEL_ORGANIZER, PluginConfig
except ImportError:
    raise ImportError("Please use pretix 2026.3 or above to run this plugin!") from None


class PluginApp(PluginConfig):
    default = True
    name = "pretix_enablebanking"
    verbose_name = "Enable Banking"
    default_auto_field = "django.db.models.BigAutoField"

    class PretixPluginMeta:
        name = gettext_lazy("Enable Banking")
        author = "Nico Knoll"
        description = gettext_lazy(
            "Automatically import bank transactions via Enable Banking (PSD2/Open Banking) "
            "into the pretix bank transfer pipeline."
        )
        visible = True
        version = __version__
        category = "PAYMENT"
        compatibility = "pretix>=2026.3.0"
        level = PLUGIN_LEVEL_ORGANIZER

    def uninstalled(self, organizer):
        from .models import EnableBankingConnection

        for key in (
            "enablebanking_app_id",
            "enablebanking_private_key",
            "enablebanking_fetch_interval",
            "enablebanking_country",
        ):
            organizer.settings.delete(key)

        EnableBankingConnection.objects.filter(organizer=organizer).delete()

    def ready(self):
        from . import signals  # NOQA
