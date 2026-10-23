import base64
import json
from contextlib import contextmanager
from dataclasses import replace

import httpx
import pytest
from pydantic import ValidationError

from aipg_cinema import core_video
from aipg_cinema.core_accounts import TokenGrant, VideoQuote
from aipg_cinema.core_video import (
    CoreVideoClient,
    VideoIntent,
    VideoOutcomeUnknown,
    VideoProtocolError,
    VideoReceipt,
    VideoRejected,
)

ACCOUNT = "a0e2f13f-c2f7-4eca-ab22-416f03d0d235"
OTHER = "abbc19a0-a57d-4639-8ea8-139090efc089"
KEY = "11111111-1111-4111-8111-111111111111"
JOB = "22222222-2222-4222-8222-222222222222"
MODEL = "LTX-2.5 Distilled BF16"
GRANT = TokenGrant(ACCOUNT, "delegated-user-secret", 900)
QUOTE = VideoQuote(ACCOUNT, MODEL, 33, 24, 40000, True)


def intent(**updates):
    return VideoIntent.parse(
        {
            "prompt": "A synthetic red ball rolls on a table",
            "model": MODEL,
            "n": 1,
            "size": "256x256",
            "frames": 33,
            "fps": 24,
            "seed": 42,
            "steps": 8,
            "cfg_scale": 1,
            "audio": True,
            "max_cost_micro_usd": 40000,
            **updates,
        }
    )


def receipt(plan=None, *, completed=False, **updates):
    plan = plan or intent()
    return {
        "schema": "aipg.video-job.v1",
        "job_id": JOB,
        "request_hash": plan.request_hash(),
        "model": plan.model,
        "state": "completed" if completed else "queued",
        "reserved_micro": 40000,
        "max_cost_micro": plan.max_cost_micro_usd,
        "actual_micro": 40000 if completed else None,
        "result": {
            "model": plan.model,
            "worker": "synthetic-worker",
            "gen_time": 1.5,
            "recipe_root": "0x" + "a" * 64,
            "media": [
                {
                    "url": "https://media.example/result.mp4",
                    "key": "result.mp4",
                    "sha256": "b" * 64,
                    "seed": plan.seed,
                }
            ],
        }
        if completed
        else None,
        **updates,
    }


@contextmanager
def client(handler):
    calls = []

    def invoke(request):
        calls.append(request)
        return handler(request)

    service = CoreVideoClient(
        "server-service-secret", transport=httpx.MockTransport(invoke)
    )
    try:
        yield service, calls
    finally:
        service.close()


@pytest.mark.parametrize(
    "variant,steps,cfg,expected",
    [
        (
            "Distilled",
            8,
            1,
            "ff5564001dd3f129a4edc10db7d434d8805dc62b5ef71efae37654283f2d9bb4",
        ),
        (
            "Dev",
            40,
            3,
            "196b13865d0062b00c158e8d112c4eee379e02320592df9acf9032105a2fa94b",
        ),
    ],
)
def test_core_wire_commitment_matches_independent_protocol_vectors(
    variant, steps, cfg, expected
):
    # Public protocol vector only: no recipe admission or real job is implied.
    plan = intent(model=f"LTX-2.5 {variant} BF16", steps=steps, cfg_scale=cfg)
    assert plan.request_hash() == expected
    assert VideoIntent.parse(json.loads(plan.body())).request_hash() == expected


def test_omitted_size_zero_seed_unicode_and_source_spelling_keep_their_meaning():
    values = json.loads(intent().body())
    values.pop("size")
    omitted = VideoIntent.parse(values)
    explicit = VideoIntent.parse({**values, "size": "768x512"})
    assert "size" not in json.loads(omitted.body())
    assert omitted.request_hash() != explicit.request_hash()
    assert intent(seed=0).request_hash() != intent(seed=None).request_hash()
    source = base64.b64encode(b"synthetic-source-bytes").decode()
    plain = intent(reference_audio=source, prompt="Unicode: caf\u00e9 \U0001f600")
    data_uri = intent(
        reference_audio="data:audio/wav;base64," + source, prompt=plain.prompt
    )
    assert plain.request_hash() == data_uri.request_hash()
    assert (
        intent(
            reference_audio=base64.b64encode(b"different").decode(), prompt=plain.prompt
        ).request_hash()
        != plain.request_hash()
    )
    assert "synthetic-source-bytes" not in repr(plain)
    assert plain.prompt not in repr(plain)


def test_pin_lists_are_deeply_immutable_and_bound_to_the_exact_ending():
    pins = [
        {"image": base64.b64encode(b"opening").decode(), "frame": 0},
        {"image": base64.b64encode(b"ending").decode(), "frame": 32, "strength": 0.7},
    ]
    plan = intent(keyframes=pins)
    digest = plan.request_hash()
    pins[1]["strength"] = 0.1
    assert plan.request_hash() == digest
    with pytest.raises(ValidationError):
        plan.keyframes[1].strength = 0.1
    assert isinstance(plan.keyframes, tuple)
    assert intent(keyframes=pins).request_hash() != digest


@pytest.mark.parametrize(
    "updates",
    [
        {"frames": 32},
        {"frames": True},
        {"fps": 24.0},
        {"n": True},
        {"seconds": 2.0},
        {"max_cost_micro_usd": 0},
        {"max_cost_micro_usd": True},
        {"seed": 2**53},
        {"cfg_scale": float("nan")},
        {"audio": 1},
        {"reference_audio": "https://private.example/audio.wav"},
        {"reference_video": "data:audio/wav;base64,YQ=="},
        {"reference_image": "data:image/jpeg;base64,YQ=="},
        {"image": "cHJp\ndmF0ZQ=="},
        {"reference_audio": ""},
        {"keyframes": [{"image": "YQ==", "frame": 1}]},
        {"keyframes": [{"image": "YQ==", "frame": 0}, {"image": "YQ==", "frame": 0}]},
        {"image": "YQ==", "keyframes": [{"image": "YQ==", "frame": 0}]},
        {"render_profile": "pretend-two-pass"},
    ],
)
def test_invalid_or_ambiguous_requests_fail_with_private_values_hidden(updates):
    with pytest.raises(VideoProtocolError) as caught:
        intent(**updates)
    assert "private.example" not in str(caught.value)
    assert "cHJp" not in str(caught.value)


def test_total_request_size_is_checked_before_any_post(monkeypatch):
    monkeypatch.setattr(core_video, "MAX_BODY", 10)
    with pytest.raises(VideoProtocolError):
        intent()


def test_success_posts_once_with_server_credentials_and_exact_ceiling():
    plan = intent()
    with client(lambda r: httpx.Response(202, json=receipt(plan))) as (service, calls):
        accepted = service.submit(GRANT, plan, QUOTE, KEY)
    assert accepted.job_id == JOB
    assert accepted.reserved_micro == accepted.max_cost_micro == 40000
    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == "https://api.aipowergrid.io/v1/videos/jobs"
    assert request.headers["apikey"] == "server-service-secret"
    assert request.headers["x-grid-user-token"] == GRANT.access_token
    assert request.headers["idempotency-key"] == KEY
    assert request.content == plan.body()
    assert "server-service-secret" not in repr(accepted)


def test_a_lower_live_hold_is_allowed_but_never_a_higher_cost():
    with client(lambda r: httpx.Response(202, json=receipt(reserved_micro=39999))) as (
        service,
        _,
    ):
        accepted = service.submit(GRANT, intent(), QUOTE, KEY)
    assert accepted.reserved_micro < accepted.max_cost_micro


@pytest.mark.parametrize(
    "quote",
    [
        replace(QUOTE, account_id=OTHER),
        replace(QUOTE, model="different-model"),
        replace(QUOTE, frames=41),
        replace(QUOTE, frames=33.0),
        replace(QUOTE, fps=30),
        replace(QUOTE, cost_micro=40001),
        replace(QUOTE, balance_sufficient=False),
        replace(QUOTE, balance_sufficient=1),
    ],
)
def test_wrong_or_insufficient_quotes_never_post(quote):
    with (
        client(lambda r: pytest.fail("Must not post")) as (service, calls),
        pytest.raises(VideoProtocolError),
    ):
        service.submit(GRANT, intent(), quote, KEY)
    assert not calls


@pytest.mark.parametrize("status", [400, 401, 402, 403, 409, 413, 422, 429])
def test_core_rejections_are_sanitized_and_never_retried(status):
    with (
        client(
            lambda r: httpx.Response(status, json={"detail": "private-source-or-token"})
        ) as (service, calls),
        pytest.raises(VideoRejected) as caught,
    ):
        service.submit(GRANT, intent(), QUOTE, KEY)
    assert len(calls) == 1
    assert caught.value.status == status
    assert "private-source" not in str(caught.value)


@pytest.mark.parametrize("status", [200, 301, 302, 307, 308, 404, 408, 500, 502, 503])
def test_unconfirmed_posts_do_not_redirect_retry_or_assume_failure(status):
    # HTTP 200 with a nonterminal receipt is also a protocol mismatch.
    with (
        client(lambda r: httpx.Response(status, json=receipt())) as (service, calls),
        pytest.raises(VideoOutcomeUnknown),
    ):
        service.submit(GRANT, intent(), QUOTE, KEY)
    assert len(calls) == 1


def test_lost_post_reply_recovers_by_get_with_same_key_and_without_source_body():
    plan = intent()

    def handler(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("private-upstream-proof")
        return httpx.Response(200, json=receipt(plan, completed=True))

    with client(handler) as (service, calls):
        with pytest.raises(VideoOutcomeUnknown):
            service.submit(GRANT, plan, QUOTE, KEY)
        recovered = service.recover(GRANT, intent=plan, key=KEY)
    assert recovered.state == "completed"
    assert [r.method for r in calls] == ["POST", "GET"]
    assert calls[1].headers["idempotency-key"] == KEY
    assert not calls[1].content
    assert "private-upstream" not in repr(recovered)


@pytest.mark.parametrize(
    "changes",
    [
        {"request_hash": "f" * 64},
        {"model": "different-model"},
        {"max_cost_micro": 40001},
        {"reserved_micro": 40001},
        {"reserved_micro": True},
        {"actual_micro": 0},
        {"state": "unknown-state"},
        {"schema": "wrong-schema"},
        {"job_id": "../other-job"},
        {"request_hash": "a" * 64 + "\n"},
        {"private_extra": "do-not-forward"},
    ],
)
def test_submission_receipt_must_match_the_exact_intent_and_hold(changes):
    with (
        client(lambda r: httpx.Response(202, json=receipt(**changes))) as (service, _),
        pytest.raises(VideoOutcomeUnknown),
    ):
        service.submit(GRANT, intent(), QUOTE, KEY)


def test_completed_receipts_bind_seed_model_recipe_and_output_identity():
    plan = intent()
    good = receipt(plan, completed=True)
    with client(lambda r: httpx.Response(200, json=good)) as (service, _):
        result = service.submit(GRANT, plan, QUOTE, KEY)
        assert result.actual_micro == 40000
        assert result.terminal
    for field, value in (
        ("seed", 43),
        ("sha256", "bad"),
        ("url", "http://private.example/result"),
    ):
        data = receipt(plan, completed=True)
        data["result"]["media"][0][field] = value
        with (
            client(lambda r, data=data: httpx.Response(200, json=data)) as (service, _),
            pytest.raises(VideoOutcomeUnknown),
        ):
            service.submit(GRANT, plan, QUOTE, KEY)


def test_missing_receipt_never_reposts_or_erases_a_previously_known_job():
    with client(lambda r: httpx.Response(404)) as (service, calls):
        assert service.recover(GRANT, intent=intent(), key=KEY) is None
        with pytest.raises(VideoProtocolError):
            service.recover(
                GRANT,
                intent=intent(),
                job_id=JOB,
                previous=VideoReceipt.parse(receipt()),
            )
    assert [r.method for r in calls] == ["GET", "GET"]


def test_terminal_or_economic_receipts_cannot_change_during_recovery():
    old = VideoReceipt.parse(receipt(completed=True))
    changed = receipt(completed=True)
    changed["result"]["media"][0]["sha256"] = "c" * 64
    with (
        client(lambda r: httpx.Response(200, json=changed)) as (service, _),
        pytest.raises(VideoProtocolError),
    ):
        service.recover(GRANT, intent=intent(), job_id=JOB, previous=old)
    with (
        client(lambda r: httpx.Response(200, json=receipt())) as (service, _),
        pytest.raises(VideoProtocolError),
    ):
        service.recover(GRANT, intent=intent(), job_id=JOB, previous=old)


def test_closed_without_result_is_not_automatically_described_as_refunded():
    closed = VideoReceipt.parse(
        receipt(state="closed_without_result", actual_micro=None)
    )
    assert closed.terminal
    assert closed.actual_micro is None
    with pytest.raises(VideoProtocolError):
        VideoReceipt.parse(
            receipt(
                state="closed_without_result", result=receipt(completed=True)["result"]
            )
        )


@pytest.mark.parametrize("raw", [b"{bad", b"[]", b"\xff", b"x" * 65537])
def test_unreadable_or_oversize_receipts_remain_unknown(raw):
    with (
        client(lambda r: httpx.Response(202, content=raw)) as (service, _),
        pytest.raises(VideoOutcomeUnknown),
    ):
        service.submit(GRANT, intent(), QUOTE, KEY)


def test_recovery_requires_one_canonical_selector_without_network():
    with client(lambda r: pytest.fail("No recovery request permitted")) as (
        service,
        calls,
    ):
        for selectors in (
            {},
            {"job_id": JOB, "key": KEY},
            {"job_id": "../private"},
            {"key": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"},
        ):
            with pytest.raises(VideoProtocolError):
                service.recover(GRANT, intent=intent(), **selectors)
    assert not calls
