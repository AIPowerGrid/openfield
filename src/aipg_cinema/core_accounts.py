"""Credential-safe account calls to the configured public Grid authority.

This is account plumbing, not an inference executor or a separate credit ledger.
"""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID

import httpx

CORE_URL = "https://api.aipowergrid.io/v1"
MAX_RESPONSE = 65536


class CoreAccountError(Exception):
    def __init__(self, status: int = 503):
        self.status = status
        super().__init__(
            "Grid account service rejected the request."
            if status < 500
            else "Grid account service is unavailable."
        )


def account_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
        if str(parsed) != value or parsed.int == 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid canonical Grid account ID.") from None
    return value


def secret(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 32768
        or not value.isascii()
        or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Invalid credential.")
    return value


def subject(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"studio:[0-9a-f]{32}", value):
        raise ValueError("Invalid server-owned application subject.")
    return value


@dataclass(frozen=True)
class TokenGrant:
    account_id: str
    access_token: str = field(repr=False)
    expires_in: int

    @classmethod
    def parse(cls, data: dict):
        try:
            account = account_uuid(data["account_id"])
            token = secret(data["access_token"])
            expiry = data["expires_in"]
            if (
                data.get("token_type") != "Bearer"
                or type(expiry) is not int
                or not 1 <= expiry <= 3600
            ):
                raise ValueError
            return cls(account, token, expiry)
        except (KeyError, TypeError, ValueError):
            raise CoreAccountError(502) from None


@dataclass(frozen=True)
class Ownership:
    account_id: str
    aliases: tuple[str, ...]

    @property
    def all_accounts(self):
        return (self.account_id, *self.aliases)


@dataclass(frozen=True)
class VideoQuote:
    account_id: str
    model: str
    frames: int
    fps: int
    cost_micro: int
    balance_sufficient: bool


class CoreAccounts:
    def __init__(
        self, service_key: str, *, transport: httpx.BaseTransport | None = None
    ):
        self._key = secret(service_key)
        self._http = httpx.Client(
            transport=transport, timeout=10, follow_redirects=False, trust_env=False
        )

    def close(self):
        self._http.close()

    def _call(self, method, path, *, token=None, body=None):
        headers = {"apikey": self._key, "User-Agent": "AIPG-Studio-Accounts"}
        if token is not None:
            headers["X-Grid-User-Token"] = secret(token)
        try:
            with self._http.stream(
                method, CORE_URL + path, headers=headers, json=body
            ) as response:
                if response.status_code != 200:
                    status = response.status_code
                    raise CoreAccountError(
                        status if status in (400, 401, 403, 409, 422, 429) else 503
                    )
                payload = bytearray()
                for chunk in response.iter_bytes(8192):
                    payload.extend(chunk)
                    if len(payload) > MAX_RESPONSE:
                        raise CoreAccountError(502)
                try:
                    data = json.loads(payload)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    raise CoreAccountError(502) from None
                if not isinstance(data, dict):
                    raise CoreAccountError(502)
                return data
        except httpx.HTTPError:
            # Upstream bodies/exceptions may contain proofs or other private data.
            raise CoreAccountError() from None

    def google(self, id_token: str, app_subject: str) -> TokenGrant:
        return TokenGrant.parse(
            self._call(
                "POST",
                "/auth/google/exchange",
                body={
                    "id_token": secret(id_token),
                    "app_subject": subject(app_subject),
                },
            )
        )

    def wallet_challenge(self, address: str, app_subject: str, origin: str) -> dict:
        parsed = urlsplit(origin)
        if (
            not isinstance(address, str)
            or not re.fullmatch(r"0x[0-9a-fA-F]{40}", address)
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not origin.isascii()
            or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in origin)
        ):
            raise ValueError("Use an HTTPS sign-in origin and an EVM wallet address.")
        # Validate the port now, rather than passing a malformed authority upstream.
        _ = parsed.port
        data = self._call(
            "POST",
            "/auth/wallet/challenge",
            body={
                "address": address,
                "domain": parsed.netloc,
                "uri": origin,
                "chain_id": 8453,
                "app_subject": subject(app_subject),
            },
        )
        if (
            not isinstance(data.get("message"), str)
            or not 1 <= len(data["message"]) <= 8192
            or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("nonce")))
            or data.get("chain_id") != 8453
            or type(data.get("chain_id")) is not int
            or type(data.get("expires_in")) is not int
            or not 1 <= data["expires_in"] <= 900
        ):
            raise CoreAccountError(502)
        return {
            key: data[key] for key in ("message", "nonce", "chain_id", "expires_in")
        }

    def wallet(
        self, address: str, message: str, signature: str, app_subject: str
    ) -> TokenGrant:
        if (
            not isinstance(address, str)
            or not re.fullmatch(r"0x[0-9a-fA-F]{40}", address)
            or not isinstance(message, str)
            or not 1 <= len(message) <= 8192
            or not isinstance(signature, str)
            or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2}){1,8192}", signature)
        ):
            raise ValueError("Invalid wallet proof.")
        return TokenGrant.parse(
            self._call(
                "POST",
                "/auth/wallet/exchange",
                body={
                    "address": address,
                    "message": message,
                    "signature": signature,
                    "app_subject": subject(app_subject),
                },
            )
        )

    def refresh(self, app_subject: str) -> TokenGrant:
        # Caller must supply only a previously proof-bound, server-owned subject.
        return TokenGrant.parse(
            self._call(
                "POST", "/auth/service/exchange", body={"subject": subject(app_subject)}
            )
        )

    def ownership(self, grant: TokenGrant) -> Ownership:
        data = self._call("GET", "/account/ownership", token=grant.access_token)
        try:
            account = account_uuid(data["account_id"])
            aliases = data["account_aliases"]
            if (
                account != grant.account_id
                or not isinstance(aliases, list)
                or len(aliases) > 127
            ):
                raise ValueError
            aliases = tuple(account_uuid(value) for value in aliases)
            if len({account, *aliases}) != len(aliases) + 1:
                raise ValueError
            return Ownership(account, aliases)
        except (KeyError, TypeError, ValueError):
            raise CoreAccountError(502) from None

    def video_quote(self, grant: TokenGrant, model: str, frames: int) -> VideoQuote:
        if (
            not isinstance(model, str)
            or not 1 <= len(model) <= 255
            or type(frames) is not int
            or not 9 <= frames <= 625
            or frames % 8 != 1
        ):
            raise ValueError("Choose a supported model and LTX frame count.")
        data = self._call(
            "POST",
            "/account/credits/quote",
            token=grant.access_token,
            body={
                "model": model,
                "modality": "video",
                "n": 1,
                "frames": frames,
            },
        )
        estimate = data.get("estimate")
        if (
            not isinstance(estimate, dict)
            or data.get("account_id") != grant.account_id
            or estimate.get("model") != model
            or estimate.get("modality") != "video"
            or estimate.get("frames") != frames
            or type(estimate.get("frames")) is not int
            or estimate.get("fps") != 24
            or type(estimate.get("fps")) is not int
            or estimate.get("n") != 1
            or type(estimate.get("n")) is not int
        ):
            raise CoreAccountError(502)
        cost = estimate.get("cost_micro")
        if (
            data.get("charging_enabled") is not True
            or estimate.get("priced") is not True
            or type(cost) is not int
            or not 0 < cost <= 2**63 - 1
        ):
            raise CoreAccountError(503)
        if type(estimate.get("balance_sufficient")) is not bool:
            raise CoreAccountError(502)
        return VideoQuote(
            grant.account_id, model, frames, 24, cost, estimate["balance_sufficient"]
        )
