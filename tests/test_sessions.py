import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event, get_ident

import pytest

from aipg_cinema import sessions as sessions_module
from aipg_cinema.core_accounts import CoreAccountError, Ownership, TokenGrant
from aipg_cinema.sessions import (
    IDLE_SECONDS,
    LOGIN_SECONDS,
    SESSION_SECONDS,
    AccountSessions,
    LoginCapacity,
    LoginFlow,
    SessionError,
    WorkspaceConflict,
)

ACCOUNT = "a0e2f13f-c2f7-4eca-ab22-416f03d0d235"
OTHER = "abbc19a0-a57d-4639-8ea8-139090efc089"
ADDRESS = "0x" + "a" * 40


class FakeCore:
    def __init__(self):
        self.calls = []
        self.grant = TokenGrant(ACCOUNT, "delegated-secret", 900)
        self.aliases = ()

    def google(self, proof, subject):
        self.calls.append(("google", proof, subject))
        return self.grant

    def wallet_challenge(self, address, subject, origin):
        self.calls.append(("challenge", address, subject, origin))
        return {
            "message": "The exact Core challenge",
            "expires_in": 300,
            "nonce": "a" * 32,
            "chain_id": 8453,
        }

    def wallet(self, address, message, signature, subject):
        self.calls.append(("wallet", address, message, signature, subject))
        return self.grant

    def refresh(self, subject):
        self.calls.append(("refresh", subject))
        return self.grant

    def ownership(self, grant):
        self.calls.append(("ownership", grant.account_id))
        return Ownership(grant.account_id, self.aliases)


@pytest.fixture
def accounts(tmp_path):
    now = [1000000.0]
    core = FakeCore()
    root = tmp_path / "private-auth"

    def open_store():
        return AccountSessions(
            root, core, origin="https://studio.example", clock=lambda: now[0]
        )

    return open_store(), core, now, open_store, root


def sign_in(store):
    return store.google(store.begin(), "verified-google-proof")


def test_login_rotates_handle_and_survives_restart_without_another_prompt(accounts):
    store, core, _, reopen, root = accounts
    flow = store.begin()
    signed_in = store.google(flow, "verified-google-proof")
    assert signed_in.handle != flow.handle
    assert signed_in.csrf != flow.csrf
    assert signed_in.ownership.account_id == ACCOUNT
    core.calls.clear()
    recovered = reopen().resolve(signed_in.handle)
    assert recovered == signed_in
    assert not core.calls
    for value in (
        flow.handle,
        flow.csrf,
        signed_in.handle,
        signed_in.csrf,
        core.grant.access_token,
    ):
        assert value not in repr(flow)
        assert value not in repr(signed_in)
    contents = (root / "sessions.sqlite3").read_bytes()
    assert signed_in.handle.encode() not in contents
    assert flow.handle.encode() not in contents
    assert os.stat(root).st_mode & 0o777 == 0o700
    assert os.stat(root / "sessions.sqlite3").st_mode & 0o777 == 0o600


def test_fresh_login_flow_reuses_exact_capability_without_extending_expiry(accounts):
    store, core, now, reopen, root = accounts
    original = store.begin()
    cookie = original.cookie()
    now[0] += 12.5
    reused = reopen().begin(LoginFlow.from_cookie(cookie))
    assert reused == original
    assert reused.seconds == LOGIN_SECONDS - 12
    assert reused.cookie() == cookie
    assert not core.calls
    with sqlite3.connect(root / "sessions.sqlite3") as db:
        assert db.execute(
            "SELECT count(*), min(expires) FROM login_flows"
        ).fetchone() == (1, 1000000 + LOGIN_SECONDS)
    assert original.handle not in repr(reused)
    assert original.csrf not in repr(reused)


@pytest.mark.parametrize(
    "cookie",
    [
        "",
        "legacy" * 8,
        "a" * 43,
        "v2." + "a" * 43 + "." + "b" * 43,
        "v1." + "a" * 43 + "." + "b" * 44,
        "v1." + "a" * 43 + "." + "\u00e9" * 43,
    ],
)
def test_malformed_or_legacy_cookie_is_not_a_login_capability(cookie):
    assert LoginFlow.from_cookie(cookie) is None


def test_pending_flow_capacity_preserves_existing_flow_and_recovers_on_expiry(
    accounts, monkeypatch
):
    store, core, now, reopen, root = accounts
    monkeypatch.setattr(sessions_module, "MAX_PENDING_LOGINS", 2)
    first = store.begin()
    now[0] += 10
    second = reopen().begin()
    with pytest.raises(LoginCapacity) as error:
        reopen().begin()
    assert error.value.retry_after == LOGIN_SECONDS - 10
    assert reopen().begin(first) == first
    with sqlite3.connect(root / "sessions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM login_flows").fetchone()[0] == 2
    now[0] += LOGIN_SECONDS - 10
    replacement = reopen().begin()
    assert replacement != first and replacement != second
    with sqlite3.connect(root / "sessions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM login_flows").fetchone()[0] == 2
    assert not core.calls


def test_reloading_challenged_flow_rotates_only_that_capability_even_at_capacity(
    accounts, monkeypatch
):
    store, core, _, reopen, root = accounts
    monkeypatch.setattr(sessions_module, "MAX_PENDING_LOGINS", 1)
    original = store.begin()
    store.wallet_challenge(original, ADDRESS)
    core.calls.clear()
    replacement = reopen().begin(LoginFlow.from_cookie(original.cookie()))
    assert replacement != original
    with pytest.raises(SessionError):
        store.wallet(original, "0xaabb")
    assert not core.calls
    assert reopen().begin(replacement) == replacement
    with sqlite3.connect(root / "sessions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM login_flows").fetchone()[0] == 1


def test_forged_flow_cannot_evict_a_real_pending_login(accounts, monkeypatch):
    store, core, _, reopen, _ = accounts
    monkeypatch.setattr(sessions_module, "MAX_PENDING_LOGINS", 1)
    original = store.begin()
    with pytest.raises(LoginCapacity):
        reopen().begin(LoginFlow(original.handle, "x" * 43))
    assert reopen().begin(original) == original
    assert not core.calls


def test_pending_flow_cap_is_shared_across_real_processes(accounts):
    _, _, _, _, root = accounts
    code = """
from pathlib import Path
import sys
from aipg_cinema import sessions
sessions.MAX_PENDING_LOGINS = 2
store = sessions.AccountSessions(Path(sys.argv[1]), object(), origin='https://studio.example', clock=lambda: 1000000.0)
try:
    store.begin()
except sessions.LoginCapacity:
    print('limited')
else:
    print('created')
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(6)
    ]
    try:
        results = [child.communicate(timeout=20) for child in children]
        assert all(child.returncode == 0 for child in children), results
        assert sum(output.strip() == "created" for output, _ in results) == 2
        assert sum(output.strip() == "limited" for output, _ in results) == 4
        with sqlite3.connect(root / "sessions.sqlite3") as db:
            assert db.execute("SELECT count(*) FROM login_flows").fetchone()[0] == 2
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)


def test_each_login_uses_a_fresh_server_subject_and_no_browser_account_id(accounts):
    store, core, _, reopen, _ = accounts
    first = sign_in(store)
    core.grant = TokenGrant(OTHER, "other-secret", 900)
    second = sign_in(store)
    subjects = [call[2] for call in core.calls if call[0] == "google"]
    assert len(set(subjects)) == 2
    assert all(s.startswith("studio:") and len(s) == 39 for s in subjects)
    assert reopen().resolve(first.handle).ownership.account_id == ACCOUNT
    assert reopen().resolve(second.handle).ownership.account_id == OTHER
    with pytest.raises(SessionError):
        store.resolve(first.handle, csrf=second.csrf)


def test_google_flow_is_single_use_even_when_core_rejects_proof(accounts, monkeypatch):
    store, core, _, _, _ = accounts
    flow = store.begin()

    def reject(*args):
        raise CoreAccountError(401)

    monkeypatch.setattr(core, "google", reject)
    with pytest.raises(CoreAccountError):
        store.google(flow, "bad-proof")
    with pytest.raises(SessionError):
        store.google(flow, "different-proof")


def test_wrong_csrf_and_expired_flow_never_send_a_proof(accounts):
    store, core, now, _, _ = accounts
    flow, other = store.begin(), store.begin()
    with pytest.raises(SessionError):
        store.google(LoginFlow(flow.handle, other.csrf), "proof")
    assert not core.calls
    now[0] += LOGIN_SECONDS
    with pytest.raises(SessionError):
        store.google(flow, "proof")
    assert not core.calls


def test_two_processes_cannot_replay_one_login_flow(accounts):
    store, core, _, reopen, _ = accounts
    flow = store.begin()
    barrier = Barrier(2)

    def login(service):
        barrier.wait()
        try:
            return service.google(flow, "proof")
        except SessionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(login, (store, reopen())))
    assert sum(result is not None for result in results) == 1
    assert sum(call[0] == "google" for call in core.calls) == 1


def test_wallet_proof_is_bound_to_the_server_saved_message_and_address(accounts):
    store, core, _, reopen, _ = accounts
    flow = store.begin()
    challenge = store.wallet_challenge(flow, ADDRESS)
    challenge["message"] = "browser-replaced-message"
    session = reopen().wallet(flow, "0xaabb")
    assert session.ownership.account_id == ACCOUNT
    wallet = next(call for call in core.calls if call[0] == "wallet")
    assert wallet[1:4] == (ADDRESS, "The exact Core challenge", "0xaabb")
    assert wallet[4] == next(call[2] for call in core.calls if call[0] == "challenge")
    assert (
        next(call[3] for call in core.calls if call[0] == "challenge")
        == "https://studio.example"
    )
    with pytest.raises(SessionError):
        store.wallet(flow, "0xaabb")


def test_wallet_requires_a_challenge_and_disallows_changing_login_method(accounts):
    store, core, _, _, _ = accounts
    flow = store.begin()
    with pytest.raises(SessionError):
        store.wallet(flow, "0xaabb")
    assert not core.calls
    store.wallet_challenge(flow, ADDRESS)
    with pytest.raises(SessionError):
        store.wallet_challenge(flow, "0x" + "b" * 40)
    with pytest.raises(SessionError):
        store.google(flow, "different-proof")
    assert [call[0] for call in core.calls] == ["challenge"]


def test_wallet_challenge_expiry_and_failure_require_a_new_flow(accounts, monkeypatch):
    store, core, now, _, _ = accounts
    flow = store.begin()
    store.wallet_challenge(flow, ADDRESS)
    now[0] += 300
    with pytest.raises(SessionError):
        store.wallet(flow, "0xaabb")
    assert all(call[0] != "wallet" for call in core.calls)

    def unavailable(*args):
        raise CoreAccountError(503)

    flow = store.begin()
    monkeypatch.setattr(core, "wallet_challenge", unavailable)
    with pytest.raises(CoreAccountError):
        store.wallet_challenge(flow, ADDRESS)
    with pytest.raises(SessionError):
        store.google(flow, "proof")


def test_expired_delegation_refreshes_after_restart_without_google_or_wallet(accounts):
    store, core, now, reopen, _ = accounts
    original = sign_in(store)
    subject = next(call[2] for call in core.calls if call[0] == "google")
    core.calls.clear()
    now[0] += 901
    core.grant = replace(core.grant, access_token="refreshed-secret")
    current = reopen().resolve(original.handle, csrf=original.csrf)
    assert core.calls == [("refresh", subject), ("ownership", ACCOUNT)]
    assert current.handle == original.handle
    assert current.expires_at == original.expires_at
    assert current.grant.access_token == "refreshed-secret"
    core.calls.clear()
    assert reopen().resolve(original.handle).grant == current.grant
    assert not core.calls


def test_refresh_must_not_switch_accounts_without_authoritative_merge_alias(accounts):
    store, core, now, reopen, _ = accounts
    original = sign_in(store)
    now[0] += 901
    core.grant = TokenGrant(OTHER, "other-secret", 900)
    with pytest.raises(CoreAccountError):
        store.resolve(original.handle)
    # Only Core's ownership aliases, not client input, can authorize a merge.
    core.aliases = (ACCOUNT,)
    merged = reopen().resolve(original.handle)
    assert merged.ownership.all_accounts == (OTHER, ACCOUNT)
    assert merged.grant.account_id == OTHER


def test_unavailable_refresh_fails_closed_and_can_recover_same_session(
    accounts, monkeypatch
):
    store, core, now, reopen, _ = accounts
    original = sign_in(store)
    now[0] += 901
    refresh = core.refresh

    def unavailable(*args):
        raise CoreAccountError(503)

    monkeypatch.setattr(core, "refresh", unavailable)
    with pytest.raises(CoreAccountError):
        store.resolve(original.handle)
    monkeypatch.setattr(core, "refresh", refresh)
    assert reopen().resolve(original.handle).handle == original.handle


def test_logout_revokes_durably_and_rejects_wrong_csrf(accounts):
    store, _, _, reopen, _ = accounts
    original = sign_in(store)
    other = sign_in(store)
    with pytest.raises(SessionError):
        store.logout(original.handle, other.csrf)
    assert store.resolve(original.handle)
    store.logout(original.handle, original.csrf)
    with pytest.raises(SessionError):
        reopen().resolve(original.handle)
    assert reopen().resolve(other.handle)


def test_logout_during_refresh_cannot_resurrect_session(accounts, monkeypatch):
    store, core, now, reopen, _ = accounts
    original = sign_in(store)
    now[0] += 901
    started, proceed = Event(), Event()

    def pause(subject):
        started.set()
        assert proceed.wait(5)
        return core.grant

    monkeypatch.setattr(core, "refresh", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(store.resolve, original.handle)
        assert started.wait(5)
        reopen().logout(original.handle, original.csrf)
        proceed.set()
        with pytest.raises(SessionError):
            pending.result(timeout=5)
    with pytest.raises(SessionError):
        reopen().resolve(original.handle)


def test_concurrent_refreshes_return_the_same_persisted_winner(accounts, monkeypatch):
    store, core, now, reopen, _ = accounts
    original = sign_in(store)
    now[0] += 901
    barrier = Barrier(2)

    def refresh(subject):
        barrier.wait(timeout=5)
        return replace(core.grant, access_token=f"refresh-{get_ident()}")

    monkeypatch.setattr(core, "refresh", refresh)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda service: service.resolve(original.handle), (store, reopen())
            )
        )
    assert results[0].grant == results[1].grant
    assert reopen().resolve(original.handle).grant == results[0].grant


def test_idle_and_absolute_expiry_cannot_be_extended_by_token_refresh(accounts):
    store, _, now, _, _ = accounts
    original = sign_in(store)
    now[0] += IDLE_SECONDS
    with pytest.raises(SessionError):
        store.resolve(original.handle)
    original = sign_in(store)
    created = now[0]
    for _ in range(SESSION_SECONDS // 600 - 1):
        now[0] += 600
        assert store.resolve(original.handle).expires_at == created + SESSION_SECONDS
    now[0] = created + SESSION_SECONDS
    with pytest.raises(SessionError):
        store.resolve(original.handle)


def test_network_latency_does_not_extend_token_or_login_expiry(accounts, monkeypatch):
    store, core, now, reopen, _ = accounts
    started = now[0]

    def delayed(proof, subject):
        now[0] += 20
        return core.grant

    monkeypatch.setattr(core, "google", delayed)
    original = sign_in(store)
    assert original.token_expires_at == started + 900
    assert reopen().resolve(original.handle).token_expires_at == started + 900

    def expired(proof, subject):
        now[0] += LOGIN_SECONDS
        return core.grant

    monkeypatch.setattr(core, "google", expired)
    with pytest.raises(SessionError):
        sign_in(store)


def test_expired_refresh_response_is_never_saved_or_used(accounts, monkeypatch):
    store, core, now, _, _ = accounts
    original = sign_in(store)
    now[0] += 901

    def expired(subject):
        now[0] += core.grant.expires_in
        return core.grant

    monkeypatch.setattr(core, "refresh", expired)
    with pytest.raises(CoreAccountError):
        store.resolve(original.handle)


@pytest.mark.parametrize(
    "value", [None, "", "../sessions.sqlite3", "a" * 42, "a" * 44, "A" * 42 + "\n"]
)
def test_invalid_session_handles_never_reach_core(accounts, value):
    store, core, _, _, _ = accounts
    with pytest.raises(SessionError):
        store.resolve(value)
    assert not core.calls


def test_expired_rows_are_pruned_and_database_is_not_an_account_ledger(accounts):
    store, _, now, _, root = accounts
    sign_in(store)
    store.begin()
    now[0] += SESSION_SECONDS
    store.begin()
    with sqlite3.connect(root / "sessions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM login_flows").fetchone()[0] == 1
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        assert sorted(name[0] for name in tables) == [
            "account_workspaces",
            "login_flows",
            "sessions",
            "workspaces",
        ]


def test_private_storage_rejects_shared_permissions_symlinks_and_hardlinks(
    accounts, tmp_path
):
    _, core, _, reopen, root = accounts
    path = root / "sessions.sqlite3"
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        reopen()
    path.chmod(0o600)
    os.link(path, root / "linked.sqlite3")
    with pytest.raises(ValueError, match="private"):
        reopen()
    (root / "linked.sqlite3").unlink()
    root.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        reopen()
    root.chmod(0o700)
    alias = tmp_path / "auth-alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="private"):
        AccountSessions(alias, core, origin="https://studio.example")
    path.rename(root / "old.sqlite3")
    path.symlink_to(root / "old.sqlite3")
    with pytest.raises(OSError):
        reopen()


def test_future_database_version_is_not_silently_recreated(accounts):
    _, _, _, reopen, root = accounts
    with sqlite3.connect(root / "sessions.sqlite3") as db:
        db.execute("PRAGMA user_version=99")
    before = (root / "sessions.sqlite3").read_bytes()
    with pytest.raises(ValueError, match="version"):
        reopen()
    assert (root / "sessions.sqlite3").read_bytes() == before


def test_workspace_is_stable_across_new_logins_and_a_canonical_account_merge(accounts):
    store, core, _, reopen, _ = accounts
    original = sign_in(store)
    assert sign_in(reopen()).workspace_id == original.workspace_id
    core.grant = TokenGrant(OTHER, "merged-token", 900)
    core.aliases = (ACCOUNT,)
    merged = sign_in(reopen())
    assert merged.workspace_id == original.workspace_id
    assert merged.ownership.account_id == OTHER


def test_two_populated_account_namespaces_are_preserved_on_merge_conflict(accounts):
    store, core, _, reopen, root = accounts
    first = sign_in(store)
    core.grant = TokenGrant(OTHER, "other-token", 900)
    second = sign_in(store)
    assert first.workspace_id != second.workspace_id
    core.aliases = (ACCOUNT,)
    with pytest.raises(WorkspaceConflict):
        sign_in(reopen())
    with sqlite3.connect(root / "sessions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 2
        assert dict(
            db.execute("SELECT account, workspace FROM account_workspaces")
        ) == {ACCOUNT: first.workspace_id, OTHER: second.workspace_id}
