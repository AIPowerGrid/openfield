"""Core's durable video wire protocol, not an SDK workflow translator.

The caller must journal the intent and request key before submit. This module
does not select a recipe, authorize an SDK bypass or keep a second credit ledger.
"""

import base64
import binascii
import hashlib
import json
import math
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .core_accounts import (
    CORE_URL,
    MAX_RESPONSE,
    CoreAccounts,
    TokenGrant,
    VideoQuote,
    secret,
)

MAX_BODY = 64 * 1024 * 1024 + 65536
DIGEST = r"[0-9a-f]{64}"


class VideoProtocolError(Exception):
    def __init__(self):
        super().__init__("Invalid Grid video request or receipt.")


class VideoOutcomeUnknown(Exception):
    def __init__(self):
        super().__init__(
            "Video submission could not be confirmed. Recover the saved request; do not submit a replacement."
        )


class VideoRejected(Exception):
    def __init__(self, status: int):
        self.status = status
        super().__init__(
            "Insufficient credits or cost ceiling exceeded."
            if status == 402
            else "Grid rejected this video request."
        )


def _uuid(value: str, *, request=False) -> str:
    try:
        parsed = UUID(value)
        if str(parsed) != value or not parsed.int or (request and parsed.version != 4):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise VideoProtocolError() from None
    return value


def _decode(value: str, role: str) -> bytes:
    limit = (32 if role == "reference_video" else 12) * 1024 * 1024
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4 * ((limit + 2) // 3) + 64
    ):
        raise VideoProtocolError()
    if value.startswith("data:"):
        prefix, separator, value = value.partition(",")
        allowed = {
            "reference_video": ("video/mp4",),
            "reference_audio": ("audio/wav",),
            "reference_image": ("image/png",),
        }.get(role, ("image/png", "image/jpeg", "image/webp"))
        if not separator or prefix not in {f"data:{mime};base64" for mime in allowed}:
            raise VideoProtocolError()
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise VideoProtocolError() from None
    if not raw or len(raw) > limit:
        raise VideoProtocolError()
    return raw


class WireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class VideoPin(WireModel):
    image: str = Field(min_length=1, max_length=17_000_000, repr=False)
    frame: int = Field(ge=0, le=624)
    strength: float = Field(default=1.0, ge=0, le=1)


class VideoIntent(WireModel):
    """Explicit execution units; model/recipe compatibility is a separate gate."""

    prompt: str = Field(min_length=1, max_length=8000, repr=False)
    model: str = Field(min_length=1, max_length=255)
    n: Literal[1] = 1
    size: str = Field(default="768x512", min_length=1, max_length=32)
    seconds: float | None = Field(default=None, gt=0, le=625 / 24)
    frames: int = Field(ge=9, le=625)
    fps: Literal[24] = 24
    image: str | None = Field(default=None, max_length=17_000_000, repr=False)
    reference_audio: str | None = Field(default=None, max_length=16_777_280, repr=False)
    reference_video: str | None = Field(default=None, max_length=44_739_308, repr=False)
    reference_image: str | None = Field(default=None, max_length=16_777_280, repr=False)
    keyframes: tuple[VideoPin, ...] = Field(default=(), max_length=16, repr=False)
    loras: None = None
    response_format: Literal["url"] = "url"
    worker: str | None = Field(default=None, min_length=1, max_length=255)
    style: str | None = Field(default=None, min_length=1, max_length=128)
    progress_token: None = None
    negative_prompt: str = Field(default="", max_length=8000, repr=False)
    seed: int | None = Field(default=None, ge=0, le=2**53 - 1)
    steps: int | None = Field(default=None, ge=4, le=40)
    cfg_scale: float | None = Field(default=None, ge=1, le=5)
    sampler: Literal["euler_ancestral_cfg_pp"] = "euler_ancestral_cfg_pp"
    audio: bool = True
    guide_strength: float | None = Field(default=None, gt=0, le=1)
    reference_strength: float | None = Field(default=None, gt=0, le=1)
    reference_attention_strength: float | None = Field(default=None, gt=0, le=1)
    motion_attention_strength: float | None = Field(default=None, gt=0, le=1)
    max_cost_micro_usd: int = Field(gt=0, le=2**63 - 1)

    @field_validator("keyframes", mode="before")
    @classmethod
    def immutable_pins(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("n", "fps", mode="before")
    @classmethod
    def integer_units(cls, value):
        if type(value) is not int:
            raise ValueError("Video units must be integers.")
        return value

    @model_validator(mode="after")
    def unambiguous(self):
        positions = [pin.frame for pin in self.keyframes]
        if (
            self.frames % 8 != 1
            or (
                self.seconds is not None
                and not math.isclose(self.seconds, self.frames / self.fps, abs_tol=1e-9)
            )
            or (self.image is not None and self.keyframes)
            or (
                positions
                and (
                    positions[0] != 0
                    or positions != sorted(set(positions))
                    or positions[-1] >= self.frames
                )
            )
        ):
            raise ValueError(
                "Video timing and references must describe one explicit clip."
            )
        return self

    @classmethod
    def parse(cls, value: dict):
        try:
            result = cls.model_validate(value)
            result.request_hash()
            result.body()
            return result
        except (ValueError, TypeError, ValidationError, VideoProtocolError):
            raise VideoProtocolError() from None

    def body(self) -> bytes:
        # Keep omission semantics: an omitted size is not an explicit default size.
        data = self.model_dump(mode="json", exclude_unset=True)
        body = json.dumps(
            data, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode("ascii")
        if len(body) > MAX_BODY:
            raise VideoProtocolError()
        return body

    def request_hash(self) -> str:
        data = self.model_dump(mode="json")
        if "size" not in self.model_fields_set:
            data.pop("size")
        images = (
            [self.image]
            if self.image is not None
            else [pin.image for pin in self.keyframes]
        )
        if sum(len(value) for value in images) > 32 * 1024 * 1024:
            raise VideoProtocolError()
        decoded = [_decode(value, "image") for value in images]
        if sum(map(len, decoded)) > 24 * 1024 * 1024:
            raise VideoProtocolError()
        digests = [{"sha256": hashlib.sha256(raw).hexdigest()} for raw in decoded]
        if self.image is not None:
            data["image"] = digests[0]
        for pin, digest in zip(data["keyframes"], digests):
            pin["image"] = digest
        for role in ("reference_audio", "reference_video", "reference_image"):
            value = getattr(self, role)
            if value is None:
                data.pop(role)
            else:
                data[role] = {
                    "sha256": hashlib.sha256(_decode(value, role)).hexdigest()
                }
        for control in (
            "guide_strength",
            "reference_strength",
            "reference_attention_strength",
            "motion_attention_strength",
        ):
            if getattr(self, control) is None:
                data.pop(control)
        encoded = json.dumps(
            {"schema": "aipg.video-intent.v1", "request": data},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()


class VideoMedia(WireModel):
    url: str = Field(min_length=1, max_length=4096, repr=False)
    key: str = Field(min_length=1, max_length=2048, repr=False)
    sha256: str = Field(min_length=64, max_length=64, pattern="^" + DIGEST + "$")
    seed: int = Field(ge=0, le=2**53 - 1)

    @field_validator("url")
    @classmethod
    def https_result(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(c.isspace() for c in value)
        ):
            raise ValueError("A receipt needs an HTTPS media URL.")
        _ = parsed.port
        return value


class VideoResult(WireModel):
    model: str = Field(min_length=1, max_length=255)
    worker: str = Field(max_length=255)
    gen_time: float = Field(ge=0)
    recipe_root: str = Field(min_length=66, max_length=66, pattern="^0x" + DIGEST + "$")
    media: tuple[VideoMedia, ...] = Field(min_length=1, max_length=1, repr=False)

    @field_validator("media", mode="before")
    @classmethod
    def immutable_media(cls, value):
        return tuple(value) if isinstance(value, list) else value


class VideoReceipt(WireModel):
    schema_version: Literal["aipg.video-job.v1"] = Field(alias="schema")
    job_id: str
    request_hash: str = Field(min_length=64, max_length=64, pattern="^" + DIGEST + "$")
    model: str = Field(min_length=1, max_length=255)
    state: Literal[
        "pending_dispatch",
        "queued",
        "execution_uncertain",
        "completed",
        "closed_without_result",
    ]
    reserved_micro: int = Field(gt=0, le=2**63 - 1)
    max_cost_micro: int = Field(gt=0, le=2**63 - 1)
    actual_micro: int | None
    result: VideoResult | None

    @field_validator("job_id")
    @classmethod
    def canonical_id(cls, value):
        return _uuid(value)

    @model_validator(mode="after")
    def consistent(self):
        invalid = self.max_cost_micro < self.reserved_micro or (
            self.actual_micro is not None
            and not 0 <= self.actual_micro <= self.max_cost_micro
        )
        if self.state == "completed":
            invalid |= (
                self.actual_micro != self.reserved_micro
                or self.result is None
                or self.result.model != self.model
            )
        elif self.state == "closed_without_result":
            invalid |= self.result is not None
        else:
            invalid |= self.actual_micro is not None or self.result is not None
        if invalid:
            raise ValueError("Receipt state and economic commitments disagree.")
        return self

    @property
    def terminal(self):
        return self.state in ("completed", "closed_without_result")

    @classmethod
    def parse(cls, data: dict):
        try:
            return cls.model_validate(data)
        except (ValueError, TypeError, ValidationError, VideoProtocolError):
            raise VideoProtocolError() from None

    def bind(
        self,
        *,
        intent_hash: str,
        model: str,
        ceiling: int,
        job_id: str | None = None,
        seed: int | None = None,
    ):
        if (
            self.request_hash != intent_hash
            or self.model != model
            or self.max_cost_micro != ceiling
            or (job_id is not None and self.job_id != job_id)
            or (
                seed is not None
                and self.result is not None
                and self.result.media[0].seed != seed
            )
        ):
            raise VideoProtocolError()
        return self

    def follows(self, previous):
        if (
            self.job_id,
            self.request_hash,
            self.model,
            self.reserved_micro,
            self.max_cost_micro,
        ) != (
            previous.job_id,
            previous.request_hash,
            previous.model,
            previous.reserved_micro,
            previous.max_cost_micro,
        ) or (previous.terminal and self != previous):
            raise VideoProtocolError()
        return self


class CoreVideoClient(CoreAccounts):
    def _video_request(self, method, path, grant, *, key=None, body=None):
        headers = {
            "apikey": self._key,
            "X-Grid-User-Token": secret(grant.access_token),
            "User-Agent": "AIPG-Studio-Video",
        }
        if key is not None:
            headers["Idempotency-Key"] = _uuid(key, request=True)
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            with self._http.stream(
                method, CORE_URL + path, content=body, headers=headers
            ) as response:
                if response.status_code == 404 and method == "GET":
                    return None
                if response.status_code in (400, 401, 402, 403, 409, 413, 422, 429):
                    raise VideoRejected(response.status_code)
                if response.status_code not in (
                    (200, 202) if method == "POST" else (200,)
                ):
                    raise VideoProtocolError()
                payload = bytearray()
                for chunk in response.iter_bytes(8192):
                    if len(payload) + len(chunk) > MAX_RESPONSE:
                        raise VideoProtocolError()
                    payload.extend(chunk)
                receipt = VideoReceipt.parse(json.loads(payload))
                if method == "POST" and receipt.terminal != (
                    response.status_code == 200
                ):
                    raise VideoProtocolError()
                return receipt
        except (
            httpx.HTTPError,
            VideoProtocolError,
            ValueError,
            RecursionError,
            TypeError,
        ):
            if method == "POST":
                raise VideoOutcomeUnknown() from None
            raise VideoProtocolError() from None

    def submit(
        self, grant: TokenGrant, intent: VideoIntent, quote: VideoQuote, key: str
    ) -> VideoReceipt:
        _uuid(key, request=True)
        _uuid(grant.account_id)
        if (
            quote.account_id != grant.account_id
            or quote.model != intent.model
            or type(quote.frames) is not int
            or quote.frames != intent.frames
            or type(quote.fps) is not int
            or quote.fps != intent.fps
            or type(quote.cost_micro) is not int
            or quote.cost_micro != intent.max_cost_micro_usd
            or quote.balance_sufficient is not True
        ):
            raise VideoProtocolError()
        intent_hash, body = intent.request_hash(), intent.body()
        receipt = self._video_request("POST", "/videos/jobs", grant, key=key, body=body)
        try:
            receipt.bind(
                intent_hash=intent_hash,
                model=intent.model,
                ceiling=intent.max_cost_micro_usd,
                seed=intent.seed,
            )
            return receipt
        except VideoProtocolError:
            raise VideoOutcomeUnknown() from None

    def recover(
        self,
        grant: TokenGrant,
        *,
        intent: VideoIntent,
        job_id: str | None = None,
        key: str | None = None,
        previous: VideoReceipt | None = None,
    ) -> VideoReceipt | None:
        _uuid(grant.account_id)
        if (job_id is None) == (key is None):
            raise VideoProtocolError()
        path = "/videos/jobs" + ("/" + _uuid(job_id) if job_id is not None else "")
        receipt = self._video_request("GET", path, grant, key=key)
        if receipt is None and previous is not None:
            raise VideoProtocolError()
        if receipt is not None:
            receipt.bind(
                intent_hash=intent.request_hash(),
                model=intent.model,
                ceiling=intent.max_cost_micro_usd,
                job_id=job_id,
                seed=intent.seed,
            )
            if previous is not None:
                receipt.follows(previous)
        return receipt
