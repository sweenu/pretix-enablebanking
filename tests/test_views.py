from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import requests
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from django_scopes import scopes_disabled

from pretix_enablebanking.models import (
    EnableBankingAccount,
    EnableBankingConnection,
    EnableBankingImportJob,
)
from pretix_enablebanking.views import (
    EnableBankingCallbackView,
    EnableBankingImportView,
    EnableBankingSettingsView,
)

pytestmark = pytest.mark.django_db


def _prep_messages(request, user=None):
    request.session = MagicMock(session_key="test")
    request._messages = FallbackStorage(request)
    # The Stripe nav signal (triggered via OrganizerDetailViewMixin) reaches
    # into request.user; supply a dummy that says it has no permissions.
    if user is None:
        user = MagicMock()
        user.has_active_staff_session.return_value = False
        user.has_organizer_permission.return_value = False
    request.user = user
    return request


@pytest.fixture
def settings_url(organizer):
    return reverse(
        "plugins:pretix_enablebanking:settings", kwargs={"organizer": organizer.slug}
    )


@pytest.fixture
def import_url(organizer):
    return reverse(
        "plugins:pretix_enablebanking:import", kwargs={"organizer": organizer.slug}
    )


def _make_view(view_cls, request, **url_kwargs):
    view = view_cls()
    view.request = request
    view.kwargs = url_kwargs
    return view


@pytest.fixture
def settings_view(rf, organizer, settings_url):
    def _build(method="get", data=None):
        req = (
            rf.get(settings_url)
            if method == "get"
            else rf.post(settings_url, data=data or {})
        )
        req.organizer = organizer
        _prep_messages(req)
        return _make_view(EnableBankingSettingsView, req, organizer=organizer.slug)

    return _build


@pytest.fixture
def import_view(rf, organizer, import_url):
    def _build(method="get", data=None):
        req = (
            rf.get(import_url)
            if method == "get"
            else rf.post(import_url, data=data or {})
        )
        req.organizer = organizer
        _prep_messages(req)
        return _make_view(EnableBankingImportView, req, organizer=organizer.slug)

    return _build


@pytest.fixture
def callback_view(rf, organizer):
    def _build(query=""):
        url = reverse(
            "plugins:pretix_enablebanking:callback",
            kwargs={"organizer": organizer.slug},
        )
        req = rf.get(f"{url}?{query}")
        req.organizer = organizer
        _prep_messages(req)
        return _make_view(EnableBankingCallbackView, req, organizer=organizer.slug)

    return _build


class TestSettingsViewContext:
    def test_no_connection_no_credentials(self, settings_view):
        view = settings_view()
        view.object_list = []
        ctx = view.get_context_data()
        assert ctx["connection"] is None
        assert ctx["accounts"] == []
        assert ctx["has_credentials"] is False
        assert ctx["country"] == "DE"
        assert ctx["aspsps"] == []

    def test_credentials_configured_lists_aspsps(
        self, settings_view, configured_organizer, monkeypatch
    ):
        view = settings_view()
        client = MagicMock()
        client.list_aspsps.return_value = [{"name": "BankA"}]
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        ctx = view.get_context_data()
        assert ctx["has_credentials"] is True
        assert ctx["aspsps"] == [{"name": "BankA"}]
        assert ctx["country"] == "DE"

    def test_http_error_listing_aspsps(
        self, settings_view, configured_organizer, monkeypatch
    ):
        view = settings_view()
        client = MagicMock()
        client.list_aspsps.side_effect = requests.exceptions.HTTPError("auth failed")
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        ctx = view.get_context_data()
        assert ctx["credentials_error"] == "auth failed"
        assert ctx["aspsps"] == []

    def test_active_connection_skips_aspsps_fetch(
        self, settings_view, connection, account, monkeypatch
    ):
        view = settings_view()
        client = MagicMock()
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        ctx = view.get_context_data()
        assert ctx["connection"] == connection
        assert list(ctx["accounts"]) == [account]
        client.list_aspsps.assert_not_called()


class TestSettingsViewPost:
    def test_disconnect_removes_connection(self, settings_view, connection):
        view = settings_view("post", data={"action": "disconnect"})
        resp = view.post(view.request)
        assert resp.status_code == 302
        with scopes_disabled():
            assert not EnableBankingConnection.objects.filter(pk=connection.pk).exists()

    def test_update_accounts_with_no_connection_redirects(self, settings_view):
        view = settings_view("post", data={"action": "update_accounts"})
        resp = view.post(view.request)
        assert resp.status_code == 302

    def test_update_accounts_toggles_is_active(self, settings_view, connection, account):
        view = settings_view(
            "post", data={"action": "update_accounts", "active_accounts": []}
        )
        view.post(view.request)
        with scopes_disabled():
            account.refresh_from_db()
        assert account.is_active is False

        view = settings_view(
            "post",
            data={"action": "update_accounts", "active_accounts": [str(account.pk)]},
        )
        view.post(view.request)
        with scopes_disabled():
            account.refresh_from_db()
        assert account.is_active is True

    def test_connect_bank_missing_credentials(self, settings_view, monkeypatch):
        def _raise(_):
            raise ImproperlyConfigured("missing")

        monkeypatch.setattr("pretix_enablebanking.views.get_enablebanking_client", _raise)
        view = settings_view(
            "post",
            data={"action": "connect_bank", "aspsp_name": "B", "aspsp_country": "DE"},
        )
        resp = view.post(view.request)
        assert resp.status_code == 302

    def test_connect_bank_create_auth_fails(
        self, settings_view, configured_organizer, monkeypatch
    ):
        client = MagicMock()
        client.create_auth.side_effect = RuntimeError("api down")
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        view = settings_view(
            "post",
            data={
                "action": "connect_bank",
                "aspsp_name": "B",
                "aspsp_country": "DE",
            },
        )
        resp = view.post(view.request)
        assert resp.status_code == 302

    def test_connect_bank_success_redirects_to_auth_url(
        self, settings_view, configured_organizer, monkeypatch
    ):
        client = MagicMock()
        client.create_auth.return_value = {"url": "https://auth.example.com/x"}
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        view = settings_view(
            "post",
            data={
                "action": "connect_bank",
                "aspsp_name": "MyBank",
                "aspsp_country": "DE",
                "maximum_consent_validity": "3600",
            },
        )
        resp = view.post(view.request)
        assert resp.status_code == 302
        assert resp.url == "https://auth.example.com/x"
        with scopes_disabled():
            conn = EnableBankingConnection.objects.get(organizer=configured_organizer)
        assert conn.state == EnableBankingConnection.STATE_AWAITING_AUTH
        assert conn.aspsp_name == "MyBank"
        # MCV was passed through as int
        assert client.create_auth.call_args.kwargs["maximum_consent_validity"] == 3600

    def test_connect_bank_non_digit_mcv(
        self, settings_view, configured_organizer, monkeypatch
    ):
        client = MagicMock()
        client.create_auth.return_value = {"url": "https://x"}
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        view = settings_view(
            "post",
            data={
                "action": "connect_bank",
                "aspsp_name": "B",
                "aspsp_country": "DE",
                "maximum_consent_validity": "garbage",
            },
        )
        view.post(view.request)
        assert client.create_auth.call_args.kwargs["maximum_consent_validity"] is None


class TestSettingsViewFormSave:
    def test_form_valid_persists_settings(self, rf, organizer, settings_url):
        req = rf.post(
            settings_url,
            data={
                "enablebanking_app_id": "abc",
                "enablebanking_private_key": "PEM",
                "enablebanking_fetch_interval": "60",
                "enablebanking_country": "ES",
            },
        )
        req.organizer = organizer
        _prep_messages(req)
        view = _make_view(EnableBankingSettingsView, req, organizer=organizer.slug)
        resp = view.post(view.request)
        assert resp.status_code == 302
        assert organizer.settings.get("enablebanking_app_id") == "abc"


class TestImportViewContext:
    def test_no_connection(self, import_view):
        view = import_view()
        ctx = view.get_context_data()
        assert ctx["connection"] is None
        assert ctx["accounts"] == []
        assert ctx["has_active_connection"] is False
        assert ctx["sandbox_mode"] is False
        assert ctx["connection_expiry_warning"] is False

    def test_active_connection(self, import_view, connection, account):
        view = import_view()
        ctx = view.get_context_data()
        assert ctx["has_active_connection"] is True
        assert ctx["sandbox_mode"] is False

    def test_sandbox_mode_detected(self, import_view, organizer):
        with scopes_disabled():
            EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_ACTIVE,
                aspsp_name="Mock ASPSP",
            )
        view = import_view()
        ctx = view.get_context_data()
        assert ctx["sandbox_mode"] is True

    def test_expiry_warning(self, import_view, organizer):
        with scopes_disabled():
            EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_ACTIVE,
                connection_expires_at=datetime.now(tz=UTC) + timedelta(days=2),
            )
        view = import_view()
        ctx = view.get_context_data()
        assert ctx["connection_expiry_warning"] is True

    def test_date_from_default_uses_oldest_last_fetch(
        self, import_view, connection
    ):
        from datetime import date

        with scopes_disabled():
            EnableBankingAccount.objects.create(
                connection=connection,
                account_uid="a1",
                iban="x",
                last_fetch_date=date(2024, 1, 10),
            )
            EnableBankingAccount.objects.create(
                connection=connection,
                account_uid="a2",
                iban="y",
                last_fetch_date=date(2024, 1, 5),
            )
        view = import_view()
        ctx = view.get_context_data()
        assert ctx["date_from_default"] == "2024-01-05"


class TestImportViewPost:
    @pytest.fixture
    def patch_apply_async(self, monkeypatch):
        mock = MagicMock()
        monkeypatch.setattr(
            "pretix_enablebanking.views.fetch_enablebanking_transactions.apply_async",
            mock,
        )
        return mock

    def test_unknown_action(self, import_view):
        view = import_view("post", data={"action": "what"})
        resp = view.post(view.request)
        assert resp.status_code == 302

    def test_fetch_now_without_connection_errors(self, import_view, patch_apply_async):
        view = import_view("post", data={"action": "fetch_now"})
        view.post(view.request)
        patch_apply_async.assert_not_called()

    def test_fetch_now_with_active_connection(
        self, import_view, connection, account, patch_apply_async
    ):
        view = import_view(
            "post",
            data={
                "action": "fetch_now",
                "date_from": "2024-05-01",
                "account_id": str(account.pk),
            },
        )
        view.post(view.request)
        patch_apply_async.assert_called_once()
        kw = patch_apply_async.call_args.kwargs["kwargs"]
        assert kw["date_from"] == "2024-05-01"
        assert kw["account_id"] == account.pk

    def test_fetch_now_with_unknown_account(
        self, import_view, connection, account, patch_apply_async
    ):
        view = import_view(
            "post", data={"action": "fetch_now", "account_id": "9999"}
        )
        view.post(view.request)
        patch_apply_async.assert_not_called()

    def test_fetch_now_no_account_filter(
        self, import_view, connection, account, patch_apply_async
    ):
        view = import_view("post", data={"action": "fetch_now"})
        view.post(view.request)
        patch_apply_async.assert_called_once()
        kw = patch_apply_async.call_args.kwargs["kwargs"]
        assert "account_id" not in kw

    def test_clear_history_deletes_plugin_jobs(
        self, import_view, connection, account, organizer
    ):
        from pretix.plugins.banktransfer.models import BankImportJob

        with scopes_disabled():
            job = BankImportJob.objects.create(organizer=organizer, currency="EUR")
            EnableBankingImportJob.objects.create(
                bank_import_job=job, account=account, organizer=organizer
            )
            other_job = BankImportJob.objects.create(organizer=organizer, currency="EUR")

        view = import_view("post", data={"action": "clear_history"})
        view.post(view.request)
        with scopes_disabled():
            assert not BankImportJob.objects.filter(pk=job.pk).exists()
            assert BankImportJob.objects.filter(pk=other_job.pk).exists()

    def test_disconnect_removes_connection(self, import_view, connection):
        view = import_view("post", data={"action": "disconnect"})
        view.post(view.request)
        with scopes_disabled():
            assert not EnableBankingConnection.objects.filter(pk=connection.pk).exists()


class TestCallbackView:
    def test_no_pending_connection(self, callback_view):
        view = callback_view(query="state=x&code=y")
        resp = view.get(view.request)
        assert resp.status_code == 302

    def test_state_mismatch(self, callback_view, organizer):
        with scopes_disabled():
            EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_AWAITING_AUTH,
                auth_state="correct-state",
            )
        view = callback_view(query="state=wrong-state&code=y")
        resp = view.get(view.request)
        assert resp.status_code == 302

    def test_empty_returned_state_rejected(self, callback_view, organizer):
        with scopes_disabled():
            EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_AWAITING_AUTH,
                auth_state="correct-state",
            )
        view = callback_view(query="code=y")
        resp = view.get(view.request)
        assert resp.status_code == 302

    def test_missing_code(self, callback_view, organizer):
        with scopes_disabled():
            EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_AWAITING_AUTH,
                auth_state="s",
            )
        view = callback_view(query="state=s")
        resp = view.get(view.request)
        assert resp.status_code == 302

    def test_client_not_configured(self, callback_view, organizer, monkeypatch):
        with scopes_disabled():
            EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_AWAITING_AUTH,
                auth_state="s",
            )

        def _raise(_):
            raise ImproperlyConfigured("missing")

        monkeypatch.setattr("pretix_enablebanking.views.get_enablebanking_client", _raise)
        view = callback_view(query="state=s&code=c")
        resp = view.get(view.request)
        assert resp.status_code == 302

    def test_create_session_fails(self, callback_view, organizer, monkeypatch):
        with scopes_disabled():
            EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_AWAITING_AUTH,
                auth_state="s",
            )
        client = MagicMock()
        client.create_session.side_effect = RuntimeError("boom")
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        view = callback_view(query="state=s&code=c")
        resp = view.get(view.request)
        assert resp.status_code == 302

    def test_successful_callback_creates_accounts(
        self, callback_view, organizer, monkeypatch
    ):
        with scopes_disabled():
            conn = EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_AWAITING_AUTH,
                auth_state="s",
            )

        client = MagicMock()
        client.create_session.return_value = {
            "session_id": "sess-xyz",
            "access": {"valid_until": "2030-01-01T00:00:00+00:00"},
            "accounts": [
                {
                    "uid": "uid-A",
                    "account_id": {"iban": "DE-A"},
                    "name": "Main",
                    "details": "Detail",
                    "currency": "EUR",
                },
                # Missing iban -> skipped
                {"uid": "uid-B", "account_id": {}},
                # Missing uid -> skipped
                {"account_id": {"iban": "DE-C"}},
            ],
        }
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        view = callback_view(query="state=s&code=c")
        resp = view.get(view.request)
        assert resp.status_code == 302

        with scopes_disabled():
            conn.refresh_from_db()
            accounts = list(EnableBankingAccount.objects.filter(connection=conn))
        assert conn.state == EnableBankingConnection.STATE_ACTIVE
        assert conn.session_id == "sess-xyz"
        assert conn.auth_state == ""
        assert len(accounts) == 1
        assert accounts[0].account_uid == "uid-A"
        assert accounts[0].account_name == "Main – Detail"
        assert accounts[0].iban == "DE-A"

    def test_invalid_valid_until_falls_back_to_90_days(
        self, callback_view, organizer, monkeypatch
    ):
        with scopes_disabled():
            conn = EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_AWAITING_AUTH,
                auth_state="s",
            )
        client = MagicMock()
        client.create_session.return_value = {
            "session_id": "x",
            "access": {"valid_until": "garbage"},
            "accounts": [],
        }
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        view = callback_view(query="state=s&code=c")
        view.get(view.request)
        with scopes_disabled():
            conn.refresh_from_db()
        assert conn.connection_expires_at is not None

    def test_no_valid_until_falls_back_to_90_days(
        self, callback_view, organizer, monkeypatch
    ):
        with scopes_disabled():
            conn = EnableBankingConnection.objects.create(
                organizer=organizer,
                state=EnableBankingConnection.STATE_AWAITING_AUTH,
                auth_state="s",
            )
        client = MagicMock()
        client.create_session.return_value = {
            "session_id": "x",
            "access": {},
            "accounts": [],
        }
        monkeypatch.setattr(
            "pretix_enablebanking.views.get_enablebanking_client", lambda _: client
        )
        view = callback_view(query="state=s&code=c")
        view.get(view.request)
        with scopes_disabled():
            conn.refresh_from_db()
        assert conn.connection_expires_at is not None
