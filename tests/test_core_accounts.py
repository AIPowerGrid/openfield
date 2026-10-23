import json
from contextlib import contextmanager

import httpx
import pytest

from aipg_cinema.core_accounts import (
    CORE_URL,
    MAX_RESPONSE,
    CoreAccountError,
    CoreAccounts,
    TokenGrant,
)

ACCOUNT = "a0e2f13f-c2f7-4eca-ab22-416f03d0d235"
OTHER = "abbc19a0-a57d-4639-8ea8-139090efc089"
SUBJECT = "studio:" + "1" * 32
ADDRESS = "0x" + "a" * 40
MODEL = "LTX-2.5 Distilled BF16"
GRANT = TokenGrant(ACCOUNT, "delegated-token", 900)


def grant_data(**updates):
    return {
        "account_id": ACCOUNT,
        "access_token": "delegated-token",
        "expires_in": 900,
        "token_type": "Bearer",
        **updates,
    }


def quote_data():
    return {
        "account_id": ACCOUNT,
        "charging_enabled": True,
        "estimate": {
            "model": MODEL,
            "modality": "video",
            "n": 1,
            "frames": 121,
            "fps": 24,
            "priced": True,
            "cost_micro": 100834,
            "balance_sufficient": True,
        },
    }


@contextmanager
def core(response=None, *, status=200, raw=None, error=None):
    requests = []

    def handle(request):
        requests.append(request)
        if error:
            raise error
        if raw is not None:
            return httpx.Response(status, content=raw)
        return httpx.Response(status, json=response)

    client = CoreAccounts("service-key", transport=httpx.MockTransport(handle))
    try:
        yield client, requests
    finally:
        client.close()


def test_google_and_refresh_pin_authority_and_keep_credentials_server_side():
    with core(grant_data()) as (client, requests):
        grant = client.google("google-proof", SUBJECT)
        assert grant == GRANT
        assert client.refresh(SUBJECT) == GRANT
    assert str(requests[0].url) == CORE_URL + "/auth/google/exchange"
    assert json.loads(requests[0].content) == {
        "id_token": "google-proof",
        "app_subject": SUBJECT,
    }
    assert json.loads(requests[1].content) == {"subject": SUBJECT}
    assert all(r.headers["apikey"] == "service-key" for r in requests)
    assert all("x-grid-user-token" not in r.headers for r in requests)
    assert "delegated-token" not in repr(grant)


@pytest.mark.parametrize(
    "updates",
    [
        {"account_id": "../another-account"},
        {"account_id": "00000000-0000-0000-0000-000000000000"},
        {"account_id": ACCOUNT.upper()},
        {"account_id": None},
        {"access_token": ""},
        {"access_token": "injected\r\nheader"},
        {"access_token": "not a token"},
        {"access_token": "injected\x7f"},
        {"token_type": "Basic"},
        {"expires_in": True},
        {"expires_in": 0},
        {"expires_in": 3601},
        {"expires_in": "900"},
    ],
)
def test_malformed_grants_never_become_sessions(updates):
    with (
        core(grant_data(**updates)) as (client, _),
        pytest.raises(CoreAccountError) as caught,
    ):
        client.google("google-proof", SUBJECT)
    assert caught.value.status == 502


@pytest.mark.parametrize(
    "status", [301, 302, 307, 308, 400, 401, 403, 409, 422, 429, 500]
)
def test_no_redirect_retry_or_upstream_private_error_disclosure(status):
    with (
        core({"detail": "private-proof-in-error"}, status=status) as (client, requests),
        pytest.raises(CoreAccountError) as caught,
    ):
        client.google("google-proof", SUBJECT)
    assert len(requests) == 1
    assert "private-proof" not in str(caught.value)
    assert caught.value.status == (
        status if status in (400, 401, 403, 409, 422, 429) else 503
    )


@pytest.mark.parametrize(
    "raw", [b"{bad-json", b"null", b"[]", b"\xff", b"x" * (MAX_RESPONSE + 1)]
)
def test_bounded_structured_responses(raw):
    with core(raw=raw) as (client, _), pytest.raises(CoreAccountError) as caught:
        client.google("google-proof", SUBJECT)
    assert caught.value.status == 502


def test_transport_errors_are_sanitized_and_not_retried():
    with (
        core(error=httpx.ReadTimeout("private-proof")) as (client, requests),
        pytest.raises(CoreAccountError) as caught,
    ):
        client.google("google-proof", SUBJECT)
    assert len(requests) == 1
    assert caught.value.status == 503
    assert "private-proof" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_ownership_requires_authoritative_matching_unique_accounts():
    with core({"account_id": ACCOUNT, "account_aliases": [OTHER]}) as (
        client,
        requests,
    ):
        ownership = client.ownership(GRANT)
    assert ownership.all_accounts == (ACCOUNT, OTHER)
    assert requests[0].headers["x-grid-user-token"] == GRANT.access_token
    assert requests[0].method == "GET"
    assert not requests[0].content


@pytest.mark.parametrize(
    "data",
    [
        {"account_id": OTHER, "account_aliases": []},
        {"account_id": ACCOUNT, "account_aliases": [ACCOUNT]},
        {"account_id": ACCOUNT, "account_aliases": [OTHER, OTHER]},
        {"account_id": ACCOUNT, "account_aliases": ["../another"]},
        {"account_id": ACCOUNT, "account_aliases": [None]},
        {"account_id": ACCOUNT, "account_aliases": [OTHER] * 128},
        {"account_id": ACCOUNT, "account_aliases": {}},
        {"account_id": ACCOUNT},
    ],
)
def test_forged_or_ambiguous_ownership_fails_closed(data):
    with (
        core(data) as (client, _),
        pytest.raises(CoreAccountError, match="unavailable"),
    ):
        client.ownership(GRANT)


def test_wallet_challenge_uses_configured_origin_and_server_owned_subject():
    challenge = {
        "message": "Sign this message.",
        "nonce": "a" * 32,
        "chain_id": 8453,
        "expires_in": 300,
    }
    with core({**challenge, "private_extra": "do-not-forward"}) as (client, requests):
        assert (
            client.wallet_challenge(ADDRESS, SUBJECT, "https://studio.example")
            == challenge
        )
    assert json.loads(requests[0].content) == {
        "address": ADDRESS,
        "app_subject": SUBJECT,
        "domain": "studio.example",
        "uri": "https://studio.example",
        "chain_id": 8453,
    }


@pytest.mark.parametrize(
    "origin",
    [
        "http://studio.example",
        "https://user@studio.example",
        "https://studio.example/path",
        "https://studio.example?x=y",
        "https://studio.example#fragment",
        "https://studio.example:bad",
        "https://studio. example",
    ],
)
def test_wallet_origins_are_validated_before_network(origin):
    with core({}) as (client, requests), pytest.raises(ValueError):
        client.wallet_challenge(ADDRESS, SUBJECT, origin)
    assert not requests


def test_wallet_exchange_and_invalid_proofs():
    with core(grant_data()) as (client, requests):
        assert client.wallet(ADDRESS, "Core challenge", "0xaabb", SUBJECT) == GRANT
        for signature in ("0xaab", "0xzz", "0x", None):
            with pytest.raises(ValueError):
                client.wallet(ADDRESS, "Core challenge", signature, SUBJECT)
    assert len(requests) == 1
    assert json.loads(requests[0].content)["message"] == "Core challenge"


@pytest.mark.parametrize(
    "field,value",
    [
        ("message", None),
        ("message", ""),
        ("nonce", "not-a-nonce"),
        ("chain_id", 1),
        ("chain_id", 8453.0),
        ("expires_in", True),
        ("expires_in", 901),
    ],
)
def test_malformed_wallet_challenges_are_not_forwarded(field, value):
    challenge = {
        "message": "Sign this message.",
        "nonce": "a" * 32,
        "chain_id": 8453,
        "expires_in": 300,
    }
    challenge[field] = value
    with core(challenge) as (client, _), pytest.raises(CoreAccountError) as caught:
        client.wallet_challenge(ADDRESS, SUBJECT, "https://studio.example")
    assert caught.value.status == 502


def test_quote_binds_account_model_frames_fps_count_and_cost():
    with core(quote_data()) as (client, requests):
        quote = client.video_quote(GRANT, MODEL, 121)
    assert quote.account_id == ACCOUNT
    assert (quote.frames, quote.fps, quote.cost_micro, quote.balance_sufficient) == (
        121,
        24,
        100834,
        True,
    )
    assert requests[0].headers["x-grid-user-token"] == GRANT.access_token
    assert json.loads(requests[0].content) == {
        "model": MODEL,
        "modality": "video",
        "n": 1,
        "frames": 121,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", OTHER),
        ("charging_enabled", False),
        ("charging_enabled", 1),
        ("estimate", None),
    ],
)
def test_quote_rejects_account_mismatch_or_disabled_charging(field, value):
    data = quote_data()
    data[field] = value
    with core(data) as (client, _), pytest.raises(CoreAccountError):
        client.video_quote(GRANT, MODEL, 121)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "different-model"),
        ("modality", "image"),
        ("frames", 129),
        ("frames", 121.0),
        ("fps", 30),
        ("fps", 24.0),
        ("n", 2),
        ("n", True),
        ("priced", False),
        ("priced", 1),
        ("cost_micro", 0),
        ("cost_micro", -1),
        ("cost_micro", True),
        ("cost_micro", 1.0),
        ("cost_micro", 2**63),
        ("balance_sufficient", 1),
    ],
)
def test_quote_rejects_inexact_or_unpriced_commitments(field, value):
    data = quote_data()
    data["estimate"][field] = value
    with core(data) as (client, _), pytest.raises(CoreAccountError):
        client.video_quote(GRANT, MODEL, 121)


def test_insufficient_balance_is_an_explicit_quote_not_successful_payment():
    data = quote_data()
    data["estimate"]["balance_sufficient"] = False
    with core(data) as (client, _):
        assert not client.video_quote(GRANT, MODEL, 121).balance_sufficient


@pytest.mark.parametrize("frames", [0, 8, 120, 626, True, 121.0])
def test_unsupported_frame_requests_never_hit_core(frames):
    with core({}) as (client, requests), pytest.raises(ValueError):
        client.video_quote(GRANT, MODEL, frames)
    assert not requests


def test_subjects_and_keys_cannot_be_urls_or_header_injections():
    with core({}) as (client, requests):
        for value in ("someone-else", "https://other.example", "studio:" + "A" * 32):
            with pytest.raises(ValueError):
                client.refresh(value)
    assert not requests
    with pytest.raises(ValueError, match="credential"):
        CoreAccounts("bad\r\nkey")
