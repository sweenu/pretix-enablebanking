from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests
from django_scopes import scopes_disabled
from pretix.plugins.banktransfer.models import BankImportJob

from pretix_enablebanking.models import (
    EnableBankingAccount,
    EnableBankingConnection,
    EnableBankingImportJob,
)
from pretix_enablebanking.tasks import fetch_enablebanking_transactions

pytestmark = pytest.mark.django_db


@pytest.fixture
def patch_process_banktransfers(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(
        "pretix.plugins.banktransfer.tasks.process_banktransfers.apply_async", mock
    )
    return mock


@pytest.fixture
def run_task(patch_process_banktransfers):
    """Invoke the task synchronously, returning the wrapped function call."""
    return fetch_enablebanking_transactions


class TestFetchTransactions:
    def test_unknown_organizer_returns_silently(self, run_task, caplog):
        result = run_task(organizer_id=999999)
        assert result is None
        assert any("Organizer 999999 not found" in r.message for r in caplog.records)

    def test_no_active_connection(self, organizer, run_task, caplog):
        result = run_task(organizer_id=organizer.pk)
        assert result is None
        assert any("No active" in r.message for r in caplog.records)

    def test_no_active_accounts(
        self, organizer, connection, run_task, mock_eb_client, caplog
    ):
        result = run_task(organizer_id=organizer.pk)
        assert result is None
        assert any("No active accounts" in r.message for r in caplog.records)
        mock_eb_client.get_transactions.assert_not_called()

    def test_filter_by_account_id(
        self, organizer, connection, account, run_task, mock_eb_client
    ):
        mock_eb_client.get_transactions.return_value = {"booked": [], "pending": []}
        run_task(organizer_id=organizer.pk, account_id=account.pk)
        mock_eb_client.get_transactions.assert_called_once()

    def test_filter_by_unknown_account_id(
        self, organizer, connection, account, run_task, mock_eb_client, caplog
    ):
        run_task(organizer_id=organizer.pk, account_id=99999)
        assert any("No active accounts" in r.message for r in caplog.records)

    def test_explicit_date_from_used(
        self, organizer, connection, account, run_task, mock_eb_client
    ):
        mock_eb_client.get_transactions.return_value = {"booked": []}
        run_task(organizer_id=organizer.pk, date_from="2024-06-15")
        mock_eb_client.get_transactions.assert_called_with(
            account.account_uid, date_from=date(2024, 6, 15)
        )

    def test_last_fetch_date_overlaps_one_day(
        self, organizer, connection, account, run_task, mock_eb_client
    ):
        with scopes_disabled():
            account.last_fetch_date = date(2024, 6, 10)
            account.save()
        mock_eb_client.get_transactions.return_value = {"booked": []}
        run_task(organizer_id=organizer.pk)
        mock_eb_client.get_transactions.assert_called_with(
            account.account_uid, date_from=date(2024, 6, 9)
        )

    def test_default_30_day_lookback(
        self, organizer, connection, account, run_task, mock_eb_client
    ):
        mock_eb_client.get_transactions.return_value = {"booked": []}
        run_task(organizer_id=organizer.pk)
        called_date = mock_eb_client.get_transactions.call_args.kwargs["date_from"]
        assert called_date == date.today() - timedelta(days=30)

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_consent_revoked_marks_error(
        self, organizer, connection, account, run_task, mock_eb_client, status_code, caplog
    ):
        resp = MagicMock(status_code=status_code)
        mock_eb_client.get_transactions.side_effect = requests.HTTPError(response=resp)

        run_task(organizer_id=organizer.pk)

        with scopes_disabled():
            connection.refresh_from_db()
        assert connection.state == EnableBankingConnection.STATE_ERROR
        assert any("refused account" in r.message for r in caplog.records)

    def test_other_http_error_triggers_retry(
        self, organizer, connection, account, run_task, mock_eb_client
    ):
        resp = MagicMock(status_code=500)
        mock_eb_client.get_transactions.side_effect = requests.HTTPError(response=resp)
        with patch.object(fetch_enablebanking_transactions, "retry") as retry:
            retry.side_effect = RuntimeError("retry")
            with pytest.raises(RuntimeError):
                run_task(organizer_id=organizer.pk)
        retry.assert_called_once()

    def test_request_exception_triggers_retry(
        self, organizer, connection, account, run_task, mock_eb_client
    ):
        mock_eb_client.get_transactions.side_effect = requests.ConnectionError("boom")
        with patch.object(fetch_enablebanking_transactions, "retry") as retry:
            retry.side_effect = RuntimeError("retry")
            with pytest.raises(RuntimeError):
                run_task(organizer_id=organizer.pk)
        retry.assert_called_once()

    def test_unknown_exception_continues_next_account(
        self, organizer, connection, run_task, mock_eb_client, caplog
    ):
        with scopes_disabled():
            a1 = EnableBankingAccount.objects.create(
                connection=connection, account_uid="bad", iban="DE1", is_active=True
            )
            a2 = EnableBankingAccount.objects.create(
                connection=connection, account_uid="good", iban="DE2", is_active=True
            )

        def side_effect(uid, date_from=None):
            if uid == "bad":
                raise ValueError("boom")
            return {"booked": []}

        mock_eb_client.get_transactions.side_effect = side_effect
        run_task(organizer_id=organizer.pk)
        assert any("Failed to fetch transactions" in r.message for r in caplog.records)

    def test_no_transactions_updates_last_fetched_only(
        self, organizer, connection, account, run_task, mock_eb_client
    ):
        mock_eb_client.get_transactions.return_value = {"booked": []}
        before = account.last_fetched
        run_task(organizer_id=organizer.pk)
        with scopes_disabled():
            account.refresh_from_db()
        assert account.last_fetched is not None
        assert account.last_fetched != before
        # last_fetch_date NOT bumped when there are no transactions
        assert account.last_fetch_date is None

    def test_creates_jobs_and_normalizes_transactions(
        self,
        organizer,
        connection,
        account,
        run_task,
        mock_eb_client,
        patch_process_banktransfers,
        sample_transaction,
    ):
        # Mix: 1 CRDT (kept), 1 DBIT (filtered out)
        debit = dict(sample_transaction, credit_debit_indicator="DBIT")
        mock_eb_client.get_transactions.return_value = {
            "booked": [sample_transaction, debit]
        }

        run_task(organizer_id=organizer.pk)

        with scopes_disabled():
            jobs = list(BankImportJob.objects.filter(organizer=organizer))
            links = list(EnableBankingImportJob.objects.filter(organizer=organizer))
            account.refresh_from_db()

        assert len(jobs) == 1
        assert jobs[0].currency == "EUR"
        assert len(links) == 1
        assert links[0].bank_import_job_id == jobs[0].pk
        assert account.last_fetch_date == date.today()
        assert account.last_fetched is not None

        patch_process_banktransfers.assert_called_once()
        data = patch_process_banktransfers.call_args.kwargs["kwargs"]["data"]
        assert len(data) == 1
        row = data[0]
        assert row["amount"] == "42.50"
        # reference_number RN-001 is appended (not already present)
        assert row["reference"] == "Order ABC123 RN-001"
        assert row["payer"] == "John Doe"
        assert row["iban"] == "DE12345"
        assert row["bic"] == "TESTBIC"
        assert row["external_id"] == "TX-001"
        assert row["date"] == "2024-01-15"

    def test_remittance_as_string(
        self, organizer, connection, account, run_task, mock_eb_client, patch_process_banktransfers
    ):
        tx = {
            "credit_debit_indicator": "CRDT",
            "transaction_amount": {"amount": "5"},
            "remittance_information": "single string ref",
        }
        mock_eb_client.get_transactions.return_value = {"booked": [tx]}
        run_task(organizer_id=organizer.pk)
        data = patch_process_banktransfers.call_args.kwargs["kwargs"]["data"]
        assert data[0]["reference"] == "single string ref"

    def test_reference_number_already_in_remittance(
        self, organizer, connection, account, run_task, mock_eb_client, patch_process_banktransfers
    ):
        tx = {
            "credit_debit_indicator": "CRDT",
            "transaction_amount": {"amount": "5"},
            "remittance_information": ["Order ABC RN-9"],
            "reference_number": "RN-9",
        }
        mock_eb_client.get_transactions.return_value = {"booked": [tx]}
        run_task(organizer_id=organizer.pk)
        data = patch_process_banktransfers.call_args.kwargs["kwargs"]["data"]
        # No duplication
        assert data[0]["reference"] == "Order ABC RN-9"

    def test_falls_back_to_value_date_and_transaction_id(
        self, organizer, connection, account, run_task, mock_eb_client, patch_process_banktransfers
    ):
        tx = {
            "credit_debit_indicator": "CRDT",
            "transaction_amount": {"amount": "5"},
            "remittance_information": [],
            "booking_date": "",
            "value_date": "2024-02-02",
            "entry_reference": "",
            "transaction_id": "TXID-1",
        }
        mock_eb_client.get_transactions.return_value = {"booked": [tx]}
        run_task(organizer_id=organizer.pk)
        data = patch_process_banktransfers.call_args.kwargs["kwargs"]["data"]
        assert data[0]["date"] == "2024-02-02"
        assert data[0]["external_id"] == "TXID-1"

    def test_all_dbit_creates_job_with_empty_data(
        self, organizer, connection, account, run_task, mock_eb_client, patch_process_banktransfers
    ):
        tx = {"credit_debit_indicator": "DBIT", "transaction_amount": {"amount": "5"}}
        mock_eb_client.get_transactions.return_value = {"booked": [tx]}
        run_task(organizer_id=organizer.pk)
        with scopes_disabled():
            assert BankImportJob.objects.filter(organizer=organizer).count() == 1
        data = patch_process_banktransfers.call_args.kwargs["kwargs"]["data"]
        assert data == []
