from django import forms
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SECRET_REDACTED, SecretKeySettingsField, SettingsForm


class SecretTextareaWidget(forms.Textarea):
    """Textarea variant of pretix' SecretKeySettingsWidget.

    Renders SECRET_REDACTED in place of the stored value so the PEM key
    is never echoed back to the page once saved. A user-supplied value
    (i.e. one being submitted now) is reflected back on form re-render
    so validation errors don't wipe the input.
    """

    def __init__(self, attrs=None):
        attrs = dict(attrs or {})
        attrs.setdefault("autocomplete", "new-password")
        self.__reflect_value = False
        super().__init__(attrs)

    def value_from_datadict(self, data, files, name):
        value = super().value_from_datadict(data, files, name)
        self.__reflect_value = bool(value) and value != SECRET_REDACTED
        return value

    def get_context(self, name, value, attrs):
        if value and not self.__reflect_value:
            value = SECRET_REDACTED
        return super().get_context(name, value, attrs)


class SecretTextareaField(SecretKeySettingsField):
    widget = SecretTextareaWidget


class EnableBankingSettingsForm(SettingsForm):
    enablebanking_app_id = forms.CharField(
        label=_("Application ID"),
        required=False,
        help_text=_("Your Enable Banking application ID."),
    )
    enablebanking_private_key = SecretTextareaField(
        label=_("Private Key (PEM)"),
        required=False,
        widget=SecretTextareaWidget(attrs={"rows": 10, "style": "font-family: monospace;"}),
        help_text=_("Your RSA private key in PEM format for Enable Banking API authentication."),
    )
    enablebanking_fetch_interval = forms.ChoiceField(
        label=_("Automatic fetch interval"),
        choices=(
            ("0", _("Disabled")),
            ("60", _("Every hour")),
            ("240", _("Every 4 hours")),
            ("720", _("Every 12 hours")),
            ("1440", _("Every 24 hours")),
        ),
        initial="0",
        required=False,
        help_text=_("How often to automatically fetch new transactions."),
    )
    enablebanking_country = forms.ChoiceField(
        label=_("Country"),
        required=False,
        initial="DE",
        choices=[
            ("AT", _("Austria")),
            ("BE", _("Belgium")),
            ("BG", _("Bulgaria")),
            ("HR", _("Croatia")),
            ("CY", _("Cyprus")),
            ("CZ", _("Czech Republic")),
            ("DK", _("Denmark")),
            ("EE", _("Estonia")),
            ("FI", _("Finland")),
            ("FR", _("France")),
            ("DE", _("Germany")),
            ("GR", _("Greece")),
            ("HU", _("Hungary")),
            ("IS", _("Iceland")),
            ("IE", _("Ireland")),
            ("IT", _("Italy")),
            ("LV", _("Latvia")),
            ("LI", _("Liechtenstein")),
            ("LT", _("Lithuania")),
            ("LU", _("Luxembourg")),
            ("MT", _("Malta")),
            ("NL", _("Netherlands")),
            ("NO", _("Norway")),
            ("PL", _("Poland")),
            ("PT", _("Portugal")),
            ("RO", _("Romania")),
            ("SK", _("Slovakia")),
            ("SI", _("Slovenia")),
            ("ES", _("Spain")),
            ("SE", _("Sweden")),
        ],
        help_text=_("Country to filter available banks."),
    )
