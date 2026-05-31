from __future__ import annotations

from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ImproperlyConfigured

from pretix_enablebanking.enablebanking_client import (
    EnableBankingClient,
    get_enablebanking_client,
)


@pytest.fixture
def client(rsa_private_key_pem) -> EnableBankingClient:
    return EnableBankingClient("app-id", rsa_private_key_pem)


def _public_key_pem(private_key_pem: str) -> bytes:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"), password=None
    )
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _mock_response(status_code=200, json_data=None, ok=True):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = ok
    resp.json.return_value = json_data or {}
    if ok:
        resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock(side_effect=requests.HTTPError(response=resp))
    return resp


class TestCreateJWT:
    def test_jwt_signed_with_app_id_as_kid(self, client, rsa_private_key_pem):
        token = client._create_jwt()
        decoded = pyjwt.decode(
            token,
            _public_key_pem(rsa_private_key_pem),
            algorithms=["RS256"],
            audience="api.enablebanking.com",
        )
        assert decoded["iss"] == "enablebanking.com"
        assert decoded["aud"] == "api.enablebanking.com"
        assert decoded["exp"] - decoded["iat"] == 3600

        header = pyjwt.get_unverified_header(token)
        assert header["kid"] == "app-id"
        assert header["alg"] == "RS256"

    def test_headers_carry_bearer_token(self, client):
        headers = client._headers()
        assert headers["Authorization"].startswith("Bearer ")


class TestListAspsps:
    def test_returns_aspsps_list(self, client):
        with patch("pretix_enablebanking.enablebanking_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(
                json_data={"aspsps": [{"name": "Bank1"}, {"name": "Bank2"}]}
            )
            result = client.list_aspsps(country="DE")
            assert result == [{"name": "Bank1"}, {"name": "Bank2"}]
            assert mock_get.call_args.kwargs["params"] == {"country": "DE"}

    def test_no_country_param(self, client):
        with patch("pretix_enablebanking.enablebanking_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(json_data={"aspsps": []})
            client.list_aspsps()
            assert mock_get.call_args.kwargs["params"] == {}

    def test_http_error_is_logged(self, client, caplog):
        with patch("pretix_enablebanking.enablebanking_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(status_code=500, ok=False)
            with pytest.raises(requests.HTTPError):
                client.list_aspsps()
        assert any("HTTP 500" in rec.message for rec in caplog.records)


class TestCreateAuth:
    def test_uses_aspsp_maximum_consent_validity(self, client):
        with patch("pretix_enablebanking.enablebanking_client.requests.post") as mock_post:
            mock_post.return_value = _mock_response(json_data={"url": "https://auth"})
            client.create_auth(
                "BankX", "DE", "https://cb", "state-123", maximum_consent_validity=3600
            )
            body = mock_post.call_args.kwargs["json"]
            assert body["aspsp"] == {"name": "BankX", "country": "DE"}
            assert body["redirect_url"] == "https://cb"
            assert body["state"] == "state-123"
            assert body["psu_type"] == "personal"
            # valid_until is ~1h ahead; we don't check exact value
            assert body["access"]["valid_until"].endswith("+00:00")

    def test_defaults_to_90_days_when_no_mcv(self, client):
        with patch("pretix_enablebanking.enablebanking_client.requests.post") as mock_post:
            mock_post.return_value = _mock_response(json_data={"url": "https://auth"})
            client.create_auth("BankY", "DE", "https://cb", "s")
            assert mock_post.called

    def test_logs_http_error(self, client, caplog):
        with patch("pretix_enablebanking.enablebanking_client.requests.post") as mock_post:
            mock_post.return_value = _mock_response(status_code=400, ok=False)
            with pytest.raises(requests.HTTPError):
                client.create_auth("B", "DE", "https://cb", "s")
        assert any("HTTP 400" in rec.message for rec in caplog.records)


class TestCreateSession:
    def test_posts_code(self, client):
        with patch("pretix_enablebanking.enablebanking_client.requests.post") as mock_post:
            mock_post.return_value = _mock_response(json_data={"session_id": "abc"})
            assert client.create_session("authcode") == {"session_id": "abc"}
            assert mock_post.call_args.kwargs["json"] == {"code": "authcode"}


class TestGetTransactions:
    def test_single_page(self, client):
        with patch("pretix_enablebanking.enablebanking_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(
                json_data={"transactions": [{"id": 1}, {"id": 2}]}
            )
            result = client.get_transactions("uid")
            assert result == {"booked": [{"id": 1}, {"id": 2}], "pending": []}
            assert mock_get.call_count == 1

    def test_pagination_follows_continuation_key(self, client):
        responses = [
            _mock_response(
                json_data={"transactions": [{"id": 1}], "continuation_key": "tok"}
            ),
            _mock_response(json_data={"transactions": [{"id": 2}]}),
        ]
        with patch(
            "pretix_enablebanking.enablebanking_client.requests.get", side_effect=responses
        ) as mock_get:
            result = client.get_transactions("uid", date_from="2024-01-01")
            assert result["booked"] == [{"id": 1}, {"id": 2}]
            assert mock_get.call_count == 2
            second_params = mock_get.call_args_list[1].kwargs["params"]
            assert second_params["continuation_key"] == "tok"
            assert second_params["date_from"] == "2024-01-01"

    def test_pagination_cap_warns(self, client, caplog, monkeypatch):
        monkeypatch.setattr(EnableBankingClient, "MAX_TRANSACTION_PAGES", 3)
        with patch("pretix_enablebanking.enablebanking_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(
                json_data={"transactions": [{"id": 1}], "continuation_key": "always"}
            )
            result = client.get_transactions("uid")
        assert mock_get.call_count == 3
        assert len(result["booked"]) == 3
        assert any("3-page cap" in rec.message for rec in caplog.records)


class TestGetEnablebankingClient:
    def test_returns_client_when_configured(self, configured_organizer):
        client = get_enablebanking_client(configured_organizer)
        assert isinstance(client, EnableBankingClient)
        assert client.app_id == "app-123"

    @pytest.mark.parametrize(
        "app_id,private_key",
        [
            ("", "key"),
            ("id", ""),
            ("", ""),
        ],
    )
    def test_raises_when_missing(self, organizer, app_id, private_key):
        organizer.settings.set("enablebanking_app_id", app_id)
        organizer.settings.set("enablebanking_private_key", private_key)
        with pytest.raises(ImproperlyConfigured):
            get_enablebanking_client(organizer)
