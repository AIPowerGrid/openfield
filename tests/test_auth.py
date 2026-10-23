import json

import httpx
import pytest
from fastapi.testclient import TestClient

from aipg_cinema import sessions as sessions_module
from aipg_cinema.auth import (
    LOGIN_COOKIE,
    MAX_AUTH_BODY,
    SESSION_COOKIE,
    create_auth_app,
)
from aipg_cinema.core_accounts import CoreAccounts
from aipg_cinema.hosted import create_hosted_app
from aipg_cinema.sessions import IDLE_SECONDS, AccountSessions

ACCOUNT = "a0e2f13f-c2f7-4eca-ab22-416f03d0d235"
OTHER = "abbc19a0-a57d-4639-8ea8-139090efc089"
ADDRESS = "0x" + "a" * 40
ORIGIN = "https://studio.example"


@pytest.fixture
def login_api(tmp_path):
    calls, bindings, tokens, overrides = [], {}, {}, {}
    now = [1000000.0]

    def grant(account):
        token = "delegated-secret-" + str(len(calls))
        tokens[token] = account
        return {
            "account_id": account,
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": 900,
        }

    def authority(request):
        calls.append(request)
        path = request.url.path.removeprefix("/v1")
        assert str(request.url).startswith("https://api.aipowergrid.io/v1/")
        assert request.headers["apikey"] == "server-only-service-key"
        if path in overrides:
            return httpx.Response(
                overrides[path], json={"detail": "private-upstream-detail"}
            )
        body = json.loads(request.content) if request.content else {}
        if path == "/auth/google/exchange":
            if body["id_token"] not in ("proof-a", "proof-b"):
                return httpx.Response(401, json={"detail": "private-invalid-proof"})
            account = ACCOUNT if body["id_token"] == "proof-a" else OTHER
            bindings[body["app_subject"]] = account
            return httpx.Response(200, json=grant(account))
        if path == "/auth/wallet/challenge":
            return httpx.Response(
                200,
                json={
                    "message": "Exact server-owned challenge",
                    "nonce": "a" * 32,
                    "chain_id": 8453,
                    "expires_in": 300,
                },
            )
        if path == "/auth/wallet/exchange":
            assert body["message"] == "Exact server-owned challenge"
            assert body["address"] == ADDRESS
            assert body["signature"] == "0xaabb"
            bindings[body["app_subject"]] = ACCOUNT
            return httpx.Response(200, json=grant(ACCOUNT))
        if path == "/auth/service/exchange":
            return httpx.Response(200, json=grant(bindings[body["subject"]]))
        if path == "/account/ownership":
            return httpx.Response(
                200,
                json={
                    "account_id": tokens[request.headers["x-grid-user-token"]],
                    "account_aliases": [],
                },
            )
        raise AssertionError("Login API must never execute inference or funding.")

    core = CoreAccounts(
        "server-only-service-key", transport=httpx.MockTransport(authority)
    )

    def open_client(*, hosted=False, cache=None):
        accounts = AccountSessions(
            tmp_path / "auth", core, origin=ORIGIN, clock=lambda: now[0]
        )
        app = (
            create_hosted_app(
                accounts,
                tmp_path / "workspaces",
                origin=ORIGIN,
                google_client_id="public-google-client",
                cache=cache,
            )
            if hosted
            else create_auth_app(
                accounts, origin=ORIGIN, google_client_id="public-google-client"
            )
        )
        return TestClient(app, base_url=ORIGIN)

    try:
        yield open_client(), calls, now, overrides, open_client
    finally:
        core.close()


def post(client, path, body, csrf):
    return client.post(
        path, json=body, headers={"origin": ORIGIN, "x-studio-csrf": csrf}
    )


def google(client, proof="proof-a"):
    state = client.get("/auth/session").json()
    return post(client, "/auth/google", {"id_token": proof}, state["csrf"])


def assert_private(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    for value in (
        "server-only-service-key",
        "delegated-secret",
        "proof-a",
        "studio:",
        "private-upstream",
        "private-invalid",
    ):
        assert value not in response.text


def test_google_login_is_cookie_based_and_survives_reload_and_restart(login_api):
    client, calls, _, _, reopen = login_api
    initial = client.get("/auth/session")
    assert initial.json()["authenticated"] is False
    assert initial.json()["google_client_id"] == "public-google-client"
    flow_handle = client.cookies.get(LOGIN_COOKIE)
    logged_in = post(
        client, "/auth/google", {"id_token": "proof-a"}, initial.json()["csrf"]
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["authenticated"] is True
    assert logged_in.json()["account_id"] == ACCOUNT
    assert logged_in.json()["csrf"] != initial.json()["csrf"]
    assert client.cookies.get(SESSION_COOKIE) != flow_handle
    assert not client.cookies.get(LOGIN_COOKIE)
    cookie = logged_in.headers.get_list("set-cookie")[0]
    assert all(
        part in cookie for part in ("Secure", "HttpOnly", "SameSite=lax", "Path=/")
    )
    assert "Domain=" not in cookie
    assert client.cookies.get(SESSION_COOKIE) not in logged_in.text
    assert_private(initial)
    assert_private(logged_in)
    calls.clear()
    recovered = reopen()
    recovered.cookies.update(client.cookies)
    assert recovered.get("/auth/session").json() == logged_in.json()
    assert not calls


def test_anonymous_reload_reuses_pending_cookie_and_csrf_without_rpc(login_api):
    client, calls, now, _, reopen = login_api
    initial = client.get("/auth/session")
    cookie = client.cookies.get(LOGIN_COOKIE)
    assert cookie.startswith("v1.") and len(cookie) == 90
    assert cookie not in initial.text
    assert cookie.split(".")[1] not in initial.text
    now[0] += 12.5
    again = client.get("/auth/session")
    assert again.json() == initial.json()
    assert client.cookies.get(LOGIN_COOKIE) == cookie
    assert "Max-Age=588" in again.headers["set-cookie"]
    reopened = reopen()
    reopened.cookies.update(client.cookies)
    assert reopened.get("/auth/session").json() == initial.json()
    assert not calls


def test_capacity_returns_private_retryable_backpressure_without_breaking_sessions(
    login_api, monkeypatch
):
    client, calls, _, _, reopen = login_api
    signed_in = google(client).json()
    calls.clear()
    monkeypatch.setattr(sessions_module, "MAX_PENDING_LOGINS", 2)
    first, second, third = reopen(), reopen(), reopen()
    state = first.get("/auth/session").json()
    assert second.get("/auth/session").status_code == 200
    denied = third.get("/auth/session")
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "600"
    assert "set-cookie" not in denied.headers
    assert first.get("/auth/session").json() == state
    assert client.get("/auth/session").json() == signed_in
    assert not calls
    assert_private(denied)
    assert (
        post(first, "/auth/google", {"id_token": "proof-a"}, state["csrf"]).status_code
        == 200
    )
    assert third.get("/auth/session").status_code == 200


def test_cookie_csrf_tampering_cannot_consume_the_real_pending_flow(login_api):
    client, calls, _, _, reopen = login_api
    state = client.get("/auth/session").json()
    original = client.cookies.get(LOGIN_COOKIE)
    attacker = reopen()
    attacker.cookies.set(LOGIN_COOKIE, original.rsplit(".", 1)[0] + "." + "x" * 43)
    assert (
        post(
            attacker, "/auth/google", {"id_token": "proof-a"}, state["csrf"]
        ).status_code
        == 401
    )
    assert not calls
    assert client.get("/auth/session").json() == state
    assert (
        post(client, "/auth/google", {"id_token": "proof-a"}, state["csrf"]).status_code
        == 200
    )


def test_reload_after_wallet_challenge_requires_a_new_explicit_challenge(
    login_api, monkeypatch
):
    client, calls, _, _, reopen = login_api
    monkeypatch.setattr(sessions_module, "MAX_PENDING_LOGINS", 1)
    state = client.get("/auth/session").json()
    cookie = client.cookies.get(LOGIN_COOKIE)
    assert (
        post(
            client, "/auth/wallet/challenge", {"address": ADDRESS}, state["csrf"]
        ).status_code
        == 200
    )
    calls.clear()
    restored = client.get("/auth/session")
    assert restored.status_code == 200
    assert restored.json()["csrf"] != state["csrf"]
    stale = reopen()
    stale.cookies.set(LOGIN_COOKIE, cookie)
    assert (
        post(stale, "/auth/wallet", {"signature": "0xaabb"}, state["csrf"]).status_code
        == 401
    )
    assert not calls


def test_legacy_cookie_rotates_without_a_proof_or_schema_migration(login_api):
    client, calls, _, _, _ = login_api
    client.cookies.set(LOGIN_COOKIE, "a" * 43)
    response = client.get("/auth/session")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert client.cookies.get(LOGIN_COOKIE, domain="studio.example").startswith("v1.")
    assert not calls


def test_expired_core_token_refresh_does_not_require_another_sign_in(login_api):
    client, calls, now, _, _ = login_api
    signed_in = google(client).json()
    handle = client.cookies.get(SESSION_COOKIE)
    now[0] += 901
    calls.clear()
    response = client.get("/auth/session")
    assert response.json()["authenticated"] is True
    assert response.json()["csrf"] == signed_in["csrf"]
    assert client.cookies.get(SESSION_COOKIE) == handle
    assert [r.url.path for r in calls] == [
        "/v1/auth/service/exchange",
        "/v1/account/ownership",
    ]
    assert_private(response)


def test_wallet_login_uses_saved_proof_and_never_auto_connects_on_reload(login_api):
    client, calls, _, _, _ = login_api
    csrf = client.get("/auth/session").json()["csrf"]
    challenge = post(client, "/auth/wallet/challenge", {"address": ADDRESS}, csrf)
    assert challenge.status_code == 200
    response = post(client, "/auth/wallet", {"signature": "0xaabb"}, csrf)
    assert response.status_code == 200
    assert response.json()["account_id"] == ACCOUNT
    calls.clear()
    assert client.get("/auth/session").json()["authenticated"] is True
    assert not calls
    assert_private(response)


def test_logout_is_a_real_durable_revocation_not_a_ui_disconnect(login_api):
    client, calls, _, _, reopen = login_api
    state = google(client).json()
    old_handle = client.cookies.get(SESSION_COOKIE)
    assert post(client, "/auth/logout", {}, "a" * 43).status_code == 401
    assert client.get("/auth/session").json()["authenticated"] is True
    response = post(client, "/auth/logout", {}, state["csrf"])
    assert response.status_code == 200
    assert not client.cookies.get(SESSION_COOKIE)
    assert not client.cookies.get(LOGIN_COOKIE)
    attacker = reopen()
    attacker.cookies.set(SESSION_COOKIE, old_handle)
    calls.clear()
    assert attacker.get("/auth/session").json()["authenticated"] is False
    assert not calls
    assert_private(response)


def test_expired_idle_session_can_still_sign_out_explicitly(login_api):
    client, _, now, _, _ = login_api
    state = google(client).json()
    now[0] += IDLE_SECONDS
    assert post(client, "/auth/logout", {}, state["csrf"]).status_code == 200
    assert not client.cookies.get(SESSION_COOKIE)


@pytest.mark.parametrize(
    "origin", [None, "https://attacker.example", "null", "https://other.studio.example"]
)
def test_cross_origin_and_missing_origin_mutations_are_rejected(login_api, origin):
    client, calls, _, _, _ = login_api
    csrf = client.get("/auth/session").json()["csrf"]
    headers = {"x-studio-csrf": csrf}
    if origin is not None:
        headers["origin"] = origin
    response = client.post(
        "/auth/google", json={"id_token": "proof-a"}, headers=headers
    )
    assert response.status_code == 403
    assert not calls
    assert_private(response)


def test_cross_site_reads_and_untrusted_hosts_cannot_create_flows(login_api):
    client, calls, _, _, _ = login_api
    for headers, status in (
        ({"sec-fetch-site": "cross-site"}, 403),
        ({"origin": "https://attacker.example"}, 403),
        ({"host": "attacker.example"}, 400),
    ):
        response = client.get("/auth/session", headers=headers)
        assert response.status_code == status
        assert "set-cookie" not in response.headers
        assert_private(response)
    assert not calls


@pytest.mark.parametrize(
    "body,status",
    [
        (b"[]", 400),
        (b"null", 400),
        (b"{broken", 400),
        (b"\xff", 400),
        (b"[" * 2000, 400),
        (b"x" * (MAX_AUTH_BODY + 1), 413),
    ],
)
def test_invalid_and_oversize_requests_fail_before_core(login_api, body, status):
    client, calls, _, _, _ = login_api
    response = client.post(
        "/auth/google",
        content=body,
        headers={"origin": ORIGIN, "content-type": "application/json"},
    )
    assert response.status_code == status
    assert not calls
    assert_private(response)


@pytest.mark.parametrize(
    "extra",
    [
        {"account_id": OTHER},
        {"app_subject": "studio:" + "a" * 32},
        {"access_token": "forged"},
    ],
)
def test_browser_cannot_choose_subject_account_or_delegated_token(login_api, extra):
    client, calls, _, _, _ = login_api
    csrf = client.get("/auth/session").json()["csrf"]
    response = post(client, "/auth/google", {"id_token": "proof-a", **extra}, csrf)
    assert response.status_code == 401
    assert not calls


def test_rejected_proofs_and_replays_are_sanitized(login_api):
    client, calls, _, _, _ = login_api
    csrf = client.get("/auth/session").json()["csrf"]
    response = post(client, "/auth/google", {"id_token": "invalid-proof"}, csrf)
    assert response.status_code == 401
    assert_private(response)
    assert len(calls) == 1
    assert (
        post(client, "/auth/google", {"id_token": "proof-a"}, csrf).status_code == 401
    )
    assert len(calls) == 1


def test_core_outage_does_not_logout_or_issue_another_wallet_prompt(login_api):
    client, _, now, overrides, _ = login_api
    state = google(client).json()
    handle = client.cookies.get(SESSION_COOKIE)
    now[0] += 901
    overrides["/auth/service/exchange"] = 503
    response = client.get("/auth/session")
    assert response.status_code == 503
    assert_private(response)
    assert "set-cookie" not in response.headers
    assert client.cookies.get(SESSION_COOKIE) == handle
    assert not client.cookies.get(LOGIN_COOKIE)
    overrides.clear()
    assert client.get("/auth/session").json()["csrf"] == state["csrf"]


def test_auth_app_does_not_expose_single_user_assets_or_start_jobs(login_api):
    client, calls, _, _, _ = login_api
    for path in (
        "/",
        "/api/config",
        "/api/projects",
        "/api/sources/" + "a" * 32,
        "/api/takes",
    ):
        assert client.get(path).status_code == 404
    assert (
        client.post("/api/takes", json={}, headers={"origin": ORIGIN}).status_code
        == 404
    )
    assert not calls


@pytest.mark.parametrize(
    "origin",
    [
        "http://studio.example",
        "https://studio.example/",
        "https://user@studio.example",
        "https://studio.example:443",
        "https://other.example",
    ],
)
def test_origin_misconfiguration_cannot_start_auth_app(login_api, tmp_path, origin):
    # No account service or rendering app is mounted on an unapproved authority.
    accounts = AccountSessions(tmp_path / "other-auth", object(), origin=ORIGIN)
    with pytest.raises(ValueError):
        create_auth_app(accounts, origin=origin, google_client_id="public-client")
