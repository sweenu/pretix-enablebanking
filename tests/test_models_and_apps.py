from __future__ import annotations

import pytest
from django_scopes import scopes_disabled

from pretix_enablebanking.apps import PluginApp
from pretix_enablebanking.models import (
    EnableBankingConnection,
)

pytestmark = pytest.mark.django_db


class TestModelStr:
    def test_connection_str(self, connection):
        s = str(connection)
        assert "EnableBankingConnection" in s
        assert "active" in s

    def test_account_str(self, account):
        assert str(account) == "Main (DE89370400440532013000)"


class TestAppsUninstall:
    def test_removes_settings_and_connection(self, organizer, connection):
        for key in (
            "enablebanking_app_id",
            "enablebanking_private_key",
            "enablebanking_fetch_interval",
            "enablebanking_country",
        ):
            organizer.settings.set(key, "x")

        app = PluginApp("pretix_enablebanking", __import__("pretix_enablebanking"))
        app.uninstalled(organizer)

        with scopes_disabled():
            assert not EnableBankingConnection.objects.filter(organizer=organizer).exists()

        for key in (
            "enablebanking_app_id",
            "enablebanking_private_key",
            "enablebanking_fetch_interval",
            "enablebanking_country",
        ):
            assert not organizer.settings.get(key)

    def test_uninstalled_idempotent_without_connection(self, organizer):
        app = PluginApp("pretix_enablebanking", __import__("pretix_enablebanking"))
        # Should not raise even with no connection or settings set.
        app.uninstalled(organizer)
