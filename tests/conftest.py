from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import RequestFactory
from django_scopes import scopes_disabled
from pretix.base.models import Organizer, Team, User

from pretix_enablebanking.models import (
    EnableBankingAccount,
    EnableBankingConnection,
)


# Generate one RSA key per test session - real RS256 signing without slowing tests.
@pytest.fixture(scope="session")
def rsa_private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


@pytest.fixture
def organizer(db) -> Organizer:
    with scopes_disabled():
        return Organizer.objects.create(name="Test Orga", slug="test")


@pytest.fixture
def configured_organizer(organizer, rsa_private_key_pem) -> Organizer:
    organizer.settings.set("enablebanking_app_id", "app-123")
    organizer.settings.set("enablebanking_private_key", rsa_private_key_pem)
    return organizer


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user("test@example.com", "password")


@pytest.fixture
def admin_team(organizer, user) -> Team:
    with scopes_disabled():
        team = Team.objects.create(
            organizer=organizer,
            all_events=True,
            can_change_organizer_settings=True,
        )
        team.members.add(user)
        return team


@pytest.fixture
def connection(organizer) -> EnableBankingConnection:
    with scopes_disabled():
        return EnableBankingConnection.objects.create(
            organizer=organizer,
            state=EnableBankingConnection.STATE_ACTIVE,
            session_id="sess-1",
            aspsp_name="Test Bank",
            aspsp_country="DE",
            connection_expires_at=datetime.now(tz=UTC) + timedelta(days=60),
        )


@pytest.fixture
def account(connection) -> EnableBankingAccount:
    with scopes_disabled():
        return EnableBankingAccount.objects.create(
            connection=connection,
            account_uid="uid-1",
            account_name="Main",
            iban="DE89370400440532013000",
            currency="EUR",
            is_active=True,
        )


@pytest.fixture
def mock_eb_client(monkeypatch) -> MagicMock:
    """Replace get_enablebanking_client with a MagicMock client.

    tasks.py imports get_enablebanking_client lazily inside the task, so we
    patch the source location.
    """
    client = MagicMock()
    monkeypatch.setattr(
        "pretix_enablebanking.enablebanking_client.get_enablebanking_client",
        lambda _organizer: client,
    )
    return client


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def sample_transaction() -> dict:
    return {
        "credit_debit_indicator": "CRDT",
        "transaction_amount": {"amount": "42.50", "currency": "EUR"},
        "remittance_information": ["Order ABC123"],
        "debtor": {"name": "John Doe"},
        "debtor_account": {"iban": "DE12345", "bic": "TESTBIC"},
        "booking_date": "2024-01-15",
        "value_date": "2024-01-15",
        "entry_reference": "TX-001",
        "transaction_id": "TX-001-ID",
        "reference_number": "RN-001",
    }
