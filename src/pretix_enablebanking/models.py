from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _


class EnableBankingConnection(models.Model):
    STATE_UNCONFIGURED = "unconfigured"
    STATE_AWAITING_AUTH = "awaiting_auth"
    STATE_ACTIVE = "active"
    STATE_EXPIRED = "expired"
    STATE_ERROR = "error"
    STATES = (
        (STATE_UNCONFIGURED, _("Unconfigured")),
        (STATE_AWAITING_AUTH, _("Awaiting authorization")),
        (STATE_ACTIVE, _("Active")),
        (STATE_EXPIRED, _("Expired")),
        (STATE_ERROR, _("Error")),
    )

    organizer = models.OneToOneField(
        "pretixbase.Organizer",
        on_delete=models.CASCADE,
        related_name="enablebanking_connection",
    )
    session_id = models.CharField(max_length=255, blank=True, default="")
    aspsp_name = models.CharField(max_length=255, blank=True, default="")
    aspsp_country = models.CharField(max_length=10, blank=True, default="")
    state = models.CharField(max_length=32, choices=STATES, default=STATE_UNCONFIGURED)
    auth_link = models.URLField(max_length=500, blank=True, default="")
    auth_state = models.CharField(max_length=64, blank=True, default="")
    connection_expires_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "pretix_enablebanking"

    def __str__(self):
        return f"EnableBankingConnection for {self.organizer} ({self.state})"


class EnableBankingAccount(models.Model):
    connection = models.ForeignKey(
        EnableBankingConnection,
        on_delete=models.CASCADE,
        related_name="accounts",
    )
    account_uid = models.CharField(max_length=255)
    account_name = models.CharField(max_length=255, blank=True, default="")
    iban = models.CharField(max_length=34, blank=True, default="")
    currency = models.CharField(max_length=10, default="EUR")
    is_active = models.BooleanField(default=True)
    last_fetched = models.DateTimeField(null=True, blank=True)
    last_fetch_date = models.DateField(null=True, blank=True)

    class Meta:
        app_label = "pretix_enablebanking"
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["connection", "account_uid"],
                name="enablebanking_account_unique_uid_per_connection",
            ),
        ]

    def __str__(self):
        return f"{self.account_name} ({self.iban})"


class EnableBankingImportJob(models.Model):
    """Links a pretix BankImportJob to the EnableBankingAccount that produced it.

    Used so "clear history" only deletes jobs created by this plugin, not
    CSV uploads or other banktransfer sources.
    """

    bank_import_job = models.OneToOneField(
        "banktransfer.BankImportJob",
        on_delete=models.CASCADE,
        related_name="enablebanking_source",
    )
    account = models.ForeignKey(
        EnableBankingAccount,
        on_delete=models.SET_NULL,
        related_name="import_jobs",
        null=True,
        blank=True,
    )
    organizer = models.ForeignKey(
        "pretixbase.Organizer",
        on_delete=models.CASCADE,
        related_name="enablebanking_import_jobs",
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "pretix_enablebanking"
