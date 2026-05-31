from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from django.urls import reverse
from django_scopes import scopes_disabled

from pretix_enablebanking.models import (
    EnableBankingConnection,
)
from pretix_enablebanking.signals import control_nav_orga, periodic_fetch

pytestmark = pytest.mark.django_db


@pytest.fixture
def perm_request(rf, organizer, user):
    """A request with a user that has organizer permission."""
    request = rf.get(reverse("plugins:banktransfer:import", kwargs={"organizer": organizer.slug}))
    request.user = user
    request.organizer = organizer
    user.has_organizer_permission = MagicMock(return_value=True)
    return request


@pytest.fixture
def no_perm_request(rf, organizer, user):
    request = rf.get(reverse("plugins:banktransfer:import", kwargs={"organizer": organizer.slug}))
    request.user = user
    request.organizer = organizer
    user.has_organizer_permission = MagicMock(return_value=False)
    return request


class TestControlNavOrga:
    def test_user_without_permission_gets_empty_nav(self, no_perm_request):
        result = control_nav_orga(sender=None, request=no_perm_request)
        assert result == []

    def test_user_with_permission_gets_nav_items(self, perm_request):
        result = control_nav_orga(sender=None, request=perm_request)
        assert len(result) == 2
        labels = [str(entry["label"]) for entry in result]
        assert "Automatic import" in labels
        assert "Enable Banking settings" in labels

    def test_active_flag_on_import_page(self, rf, organizer, user):
        import_url = reverse(
            "plugins:pretix_enablebanking:import",
            kwargs={"organizer": organizer.slug},
        )
        request = rf.get(import_url)
        request.user = user
        request.organizer = organizer
        user.has_organizer_permission = MagicMock(return_value=True)

        nav = control_nav_orga(sender=None, request=request)
        # The "Automatic import" item should be marked active.
        import_entry = next(e for e in nav if str(e["label"]) == "Automatic import")
        assert import_entry["active"] is True


class TestPeriodicFetch:
    @pytest.fixture
    def patch_task(self, monkeypatch):
        mock = MagicMock()
        monkeypatch.setattr(
            "pretix_enablebanking.tasks.fetch_enablebanking_transactions.apply_async",
            mock,
        )
        return mock

    def test_expired_connection_marked(self, organizer, patch_task):
        with scopes_disabled():
            connection = EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_ACTIVE,
                connection_expires_at=datetime.now(tz=UTC) - timedelta(days=1),
            )
        periodic_fetch.__wrapped__(sender=None)
        with scopes_disabled():
            connection.refresh_from_db()
        assert connection.state == EnableBankingConnection.STATE_EXPIRED
        patch_task.assert_not_called()

    def test_no_interval_skips(self, organizer, connection, account, patch_task):
        organizer.settings.set("enablebanking_fetch_interval", "0")
        periodic_fetch.__wrapped__(sender=None)
        patch_task.assert_not_called()

    def test_invalid_interval_logged(self, organizer, connection, account, patch_task, caplog):
        organizer.settings.set("enablebanking_fetch_interval", "not-a-number")
        periodic_fetch.__wrapped__(sender=None)
        patch_task.assert_not_called()
        assert any("Invalid enablebanking_fetch_interval" in r.message for r in caplog.records)

    def test_interval_due_dispatches_task(self, organizer, connection, account, patch_task):
        organizer.settings.set("enablebanking_fetch_interval", "60")
        # last_fetched is None -> always due
        periodic_fetch.__wrapped__(sender=None)
        patch_task.assert_called_once()
        kw = patch_task.call_args.kwargs["kwargs"]
        assert kw["organizer_id"] == organizer.pk
        assert kw["account_id"] == account.pk

    def test_recently_fetched_account_skipped(self, organizer, connection, account, patch_task):
        organizer.settings.set("enablebanking_fetch_interval", "60")
        with scopes_disabled():
            account.last_fetched = datetime.now(tz=UTC)
            account.save()
        periodic_fetch.__wrapped__(sender=None)
        patch_task.assert_not_called()

    def test_inactive_account_skipped(self, organizer, connection, account, patch_task):
        organizer.settings.set("enablebanking_fetch_interval", "60")
        with scopes_disabled():
            account.is_active = False
            account.save()
        periodic_fetch.__wrapped__(sender=None)
        patch_task.assert_not_called()
