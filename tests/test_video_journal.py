import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import httpx
import pytest
from test_core_video import ACCOUNT, GRANT, OTHER, QUOTE, intent, receipt

from aipg_cinema.core_accounts import TokenGrant
from aipg_cinema.core_video import (
    CoreVideoClient,
    VideoOutcomeUnknown,
    VideoProtocolError,
    VideoRejected,
)
from aipg_cinema.video_journal import JournalConflict, VideoJournal


def service(handler, calls):
    def request(value):
        calls.append(value)
        return handler(value)

    return CoreVideoClient(
        "server-service-secret", transport=httpx.MockTransport(request)
    )


def test_prepare_persists_the_exact_private_body_and_stable_server_request_key(
    tmp_path,
):
    root = tmp_path / "credit-video"
    journal = VideoJournal(root)
    original = intent()
    record = journal.prepare("a" * 32, ACCOUNT, original, QUOTE)
    assert UUID(record.request_key).version == 4
    assert record.request_key.replace("-", "") != record.local_id
    assert record.state == "prepared"
    assert (
        VideoJournal(root).prepare(record.local_id, ACCOUNT, original, QUOTE) == record
    )
    assert VideoJournal(root).load(record.local_id) == record
    assert (root / record.local_id / "body.json").read_bytes() == original.body()
    for path in (root, root / record.local_id):
        assert path.stat().st_mode & 0o777 == 0o700
    for name in ("record.json", "body.json"):
        path = root / record.local_id / name
        assert path.stat().st_mode & 0o777 == 0o600
        assert b"server-service-secret" not in path.read_bytes()
        assert b"delegated-user-secret" not in path.read_bytes()


def test_changed_settings_reusing_an_id_cannot_overwrite_the_approved_body(tmp_path):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    with pytest.raises(JournalConflict):
        journal.prepare(record.local_id, ACCOUNT, intent(seed=43), QUOTE)
    assert journal.load(record.local_id) == record


def test_equivalent_wire_spelling_reuses_the_frozen_original_body(tmp_path):
    journal = VideoJournal(tmp_path)
    first = intent(reference_audio="c3ludGhldGlj")
    record = journal.prepare("a" * 32, ACCOUNT, first, QUOTE)
    second = intent(reference_audio="data:audio/wav;base64,c3ludGhldGlj")
    assert second.request_hash() == first.request_hash()
    assert second.body() != first.body()
    assert journal.prepare(record.local_id, ACCOUNT, second, QUOTE) == record
    assert (tmp_path / record.local_id / "body.json").read_bytes() == first.body()


def test_dispatch_is_claimed_durably_before_post_and_duplicate_dispatch_only_recovers(
    tmp_path,
):
    root = tmp_path / "credit-video"
    journal = VideoJournal(root)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    calls = []

    def handler(request):
        if request.method == "POST":
            assert VideoJournal(root).load(record.local_id).state == "attempted"
            assert request.headers["idempotency-key"] == record.request_key
            return httpx.Response(202, json=receipt())
        assert not request.content
        return httpx.Response(200, json=receipt(completed=True))

    client = service(handler, calls)
    try:
        accepted = journal.dispatch(record.local_id, GRANT, client)
        assert accepted.state == "accepted" and accepted.active
        completed = VideoJournal(root).dispatch(record.local_id, GRANT, client)
        assert completed.receipt.state == "completed" and not completed.active
        assert VideoJournal(root).dispatch(record.local_id, GRANT, client) == completed
    finally:
        client.close()
    assert [request.method for request in calls] == ["POST", "GET"]


def test_two_instances_dispatch_the_same_intent_with_at_most_one_post(tmp_path):
    root = tmp_path / "credit-video"
    first, second = VideoJournal(root), VideoJournal(root)
    record = first.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    posted, release = Event(), Event()
    calls = []

    def handler(request):
        if request.method == "POST":
            posted.set()
            assert release.wait(5)
            return httpx.Response(202, json=receipt())
        return httpx.Response(404)

    client = service(handler, calls)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = pool.submit(first.dispatch, record.local_id, GRANT, client)
            assert posted.wait(5)
            recovered = second.dispatch(record.local_id, GRANT, client)
            assert recovered.state == "attempted" and recovered.active
            release.set()
            assert active.result(timeout=5).state == "accepted"
    finally:
        release.set()
        client.close()
    assert [request.method for request in calls] == ["POST", "GET"]


def test_unknown_reply_survives_restart_and_never_becomes_a_replacement_job(tmp_path):
    root = tmp_path / "credit-video"
    journal = VideoJournal(root)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    calls = []

    def unknown(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("private-source-bytes")
        return httpx.Response(404)

    client = service(unknown, calls)
    try:
        with pytest.raises(VideoOutcomeUnknown):
            journal.dispatch(record.local_id, GRANT, client)
        reopened = VideoJournal(root)
        assert reopened.dispatch(record.local_id, GRANT, client).state == "attempted"
        with pytest.raises(JournalConflict):
            reopened.prepare("b" * 32, ACCOUNT, intent(seed=43), QUOTE)
    finally:
        client.close()
    assert [request.method for request in calls] == ["POST", "GET"]


def test_actual_process_exit_after_claim_keeps_a_get_only_recovery(tmp_path):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    program = """
import os, sys
from pathlib import Path
import httpx
from aipg_cinema.core_accounts import TokenGrant
from aipg_cinema.core_video import CoreVideoClient
from aipg_cinema.video_journal import VideoJournal
def interrupted(request):
    assert request.method == 'POST'
    os._exit(77)
client = CoreVideoClient('synthetic-key', transport=httpx.MockTransport(interrupted))
VideoJournal(Path(sys.argv[1])).dispatch(sys.argv[2], TokenGrant(sys.argv[3], 'synthetic-token', 900), client)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path), record.local_id, ACCOUNT],
        check=False,
        timeout=10,
        capture_output=True,
    )
    assert result.returncode == 77
    assert VideoJournal(tmp_path).load(record.local_id).state == "attempted"
    calls = []
    client = service(
        lambda request: httpx.Response(200, json=receipt(completed=True)), calls
    )
    try:
        completed = VideoJournal(tmp_path).dispatch(record.local_id, GRANT, client)
        assert completed.receipt.state == "completed"
    finally:
        client.close()
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].headers["idempotency-key"] == record.request_key


def test_definitive_rejection_is_recorded_and_does_not_get_resubmitted(tmp_path):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    calls = []
    client = service(
        lambda request: httpx.Response(402, json={"detail": "private error"}), calls
    )
    try:
        with pytest.raises(VideoRejected):
            journal.dispatch(record.local_id, GRANT, client)
        rejected = journal.dispatch(record.local_id, GRANT, client)
        assert rejected.state == "rejected" and rejected.rejected_status == 402
        assert not rejected.active
        assert journal.prepare("b" * 32, ACCOUNT, intent(), QUOTE).state == "prepared"
    finally:
        client.close()
    assert len(calls) == 1


def test_a_different_account_cannot_dispatch_recover_or_cancel_saved_work(tmp_path):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    other = TokenGrant(OTHER, "other-secret", 900)
    calls = []
    client = service(
        lambda request: pytest.fail("No cross-account network request"), calls
    )
    try:
        for operation in (journal.dispatch, journal.recover):
            with pytest.raises(JournalConflict):
                operation(record.local_id, other, client)
        with pytest.raises(JournalConflict):
            journal.cancel_prepared(record.local_id, other)
    finally:
        client.close()
    assert not calls


def test_only_a_never_attempted_job_can_be_cancelled_without_calling_core(tmp_path):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    assert journal.cancel_prepared(record.local_id, GRANT).state == "cancelled"
    next_record = journal.prepare("b" * 32, ACCOUNT, intent(), QUOTE)
    calls = []
    client = service(lambda request: httpx.Response(202, json=receipt()), calls)
    try:
        journal.dispatch(next_record.local_id, GRANT, client)
        with pytest.raises(JournalConflict):
            journal.cancel_prepared(next_record.local_id, GRANT)
    finally:
        client.close()


def test_corrupted_or_shared_source_files_cannot_reach_the_network(tmp_path):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    body = tmp_path / record.local_id / "body.json"
    original = body.read_bytes()
    body.write_bytes(original.replace(b"synthetic", b"different"))
    calls = []
    client = service(
        lambda request: pytest.fail("No corrupted body may be posted"), calls
    )
    try:
        with pytest.raises(VideoProtocolError):
            journal.dispatch(record.local_id, GRANT, client)
        body.write_bytes(original)
        body.chmod(0o644)
        with pytest.raises(VideoProtocolError):
            journal.dispatch(record.local_id, GRANT, client)
        body.chmod(0o600)
        os.link(body, tmp_path / "another-link")
        with pytest.raises(VideoProtocolError):
            journal.dispatch(record.local_id, GRANT, client)
    finally:
        client.close()
    assert not calls


def test_malformed_and_oversize_journal_records_fail_closed(tmp_path):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    path = tmp_path / record.local_id / "record.json"
    original = path.read_bytes()
    for value in (b"[]", b"x" * 65537, original.replace(b'"prepared"', b'"accepted"')):
        path.write_bytes(value)
        with pytest.raises(VideoProtocolError):
            journal.load(record.local_id)


def test_late_poll_cannot_replace_a_completed_output_with_queued_state(tmp_path):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    completed = journal._accept(record.local_id, core_receipt(completed=True))
    assert journal._accept(record.local_id, core_receipt()) == completed
    changed = receipt(completed=True)
    changed["result"]["media"][0]["sha256"] = "c" * 64
    with pytest.raises(VideoProtocolError):
        journal._accept(record.local_id, core_receipt(data=changed))
    assert journal.load(record.local_id) == completed


@pytest.mark.parametrize("field", ["version", "state", "receipt", "rejected_status"])
def test_missing_lifecycle_fields_never_revert_an_attempt_to_prepared(tmp_path, field):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    path = tmp_path / record.local_id / "record.json"
    data = json.loads(path.read_bytes())
    data["state"] = "attempted"
    data.pop(field)
    path.write_text(json.dumps(data))
    calls = []
    client = service(
        lambda request: pytest.fail("Corrupted lifecycle must not reach Core"), calls
    )
    try:
        with pytest.raises(VideoProtocolError):
            journal.dispatch(record.local_id, GRANT, client)
    finally:
        client.close()
    assert not calls


def core_receipt(*, data=None, completed=False):
    from aipg_cinema.core_video import VideoReceipt

    return VideoReceipt.parse(
        data if data is not None else receipt(completed=completed)
    )


def test_active_limit_is_not_a_credit_balance_or_an_automatic_refund(tmp_path):
    journal = VideoJournal(tmp_path)
    record = journal.prepare("a" * 32, ACCOUNT, intent(), QUOTE)
    closed = core_receipt(
        data=receipt(state="closed_without_result", actual_micro=None)
    )
    finished = journal._accept(record.local_id, closed)
    assert not finished.active
    assert finished.receipt.actual_micro is None
    data = json.loads((tmp_path / record.local_id / "record.json").read_bytes())
    assert "balance" not in data and "refund" not in data
