from __future__ import annotations

import pytest
from pretix.base.forms import SECRET_REDACTED

from pretix_enablebanking.forms import (
    EnableBankingSettingsForm,
    SecretTextareaWidget,
)

pytestmark = pytest.mark.django_db


class TestSecretTextareaWidget:
    def test_redacts_stored_value(self):
        widget = SecretTextareaWidget()
        ctx = widget.get_context("key", "stored-secret", {})
        assert ctx["widget"]["value"] == SECRET_REDACTED

    def test_no_value_does_not_redact(self):
        widget = SecretTextareaWidget()
        ctx = widget.get_context("key", "", {})
        assert ctx["widget"]["value"] != SECRET_REDACTED

    def test_reflects_user_submitted_value(self):
        widget = SecretTextareaWidget()
        # Simulate a form re-render where user just submitted a new value.
        value = widget.value_from_datadict({"key": "new-secret"}, {}, "key")
        assert value == "new-secret"
        ctx = widget.get_context("key", value, {})
        assert ctx["widget"]["value"] == "new-secret"

    def test_redacted_resubmission_does_not_reflect(self):
        widget = SecretTextareaWidget()
        widget.value_from_datadict({"key": SECRET_REDACTED}, {}, "key")
        ctx = widget.get_context("key", "stored", {})
        assert ctx["widget"]["value"] == SECRET_REDACTED

    def test_autocomplete_attr_default(self):
        widget = SecretTextareaWidget()
        assert widget.attrs.get("autocomplete") == "new-password"


class TestEnableBankingSettingsForm:
    @pytest.fixture
    def form(self, organizer):
        return EnableBankingSettingsForm(obj=organizer)

    def test_has_expected_fields(self, form):
        for f in (
            "enablebanking_app_id",
            "enablebanking_private_key",
            "enablebanking_fetch_interval",
            "enablebanking_country",
        ):
            assert f in form.fields

    def test_save_persists_values(self, organizer):
        form = EnableBankingSettingsForm(
            data={
                "enablebanking_app_id": "myid",
                "enablebanking_private_key": "PEM",
                "enablebanking_fetch_interval": "240",
                "enablebanking_country": "FR",
            },
            obj=organizer,
        )
        assert form.is_valid(), form.errors
        form.save()
        assert organizer.settings.get("enablebanking_app_id") == "myid"
        assert organizer.settings.get("enablebanking_country") == "FR"

    def test_redacted_secret_keeps_stored_value(self, organizer):
        organizer.settings.set("enablebanking_private_key", "REAL-KEY")
        form = EnableBankingSettingsForm(
            data={
                "enablebanking_app_id": "id",
                "enablebanking_private_key": SECRET_REDACTED,
                "enablebanking_fetch_interval": "0",
                "enablebanking_country": "DE",
            },
            obj=organizer,
        )
        assert form.is_valid(), form.errors
        form.save()
        assert organizer.settings.get("enablebanking_private_key") == "REAL-KEY"
