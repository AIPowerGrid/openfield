# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Approximate cost or time shown before every Generate, and actuals after.

Estimates come from this project's own measured runs and are labelled as
approximate. Comfy Cloud spend is measured from the account balance before and
after a job; overlapping Cloud jobs make that actual approximate too.
"""

import os

import httpx

# Comfy credits per US dollar (Comfy's published conversion).
CREDITS_PER_USD = 211
# Measured 2026-10-22 on this project's own Cloud and owned-GPU runs.
CLOUD_TAKE_USD = 0.087  # mean of measured 7.05¢ and 10.41¢ takes
CLOUD_LOOK_USD = 0.01
OWNED_TAKE_SECONDS = 100
# Longer video-to-video takes, measured on the owned RTX PRO 6000: 10 s takes
# ran 108-150 s; 15 s is scaled from those until it has its own runs.
OWNED_LONG_TAKE_SECONDS = {10: 130, 15: 190}
OWNED_LOOK_SECONDS = 8
# Approximate Cloud wall time (queue plus render) seen on the same runs; the
# UI shows this beside the credit estimate.
CLOUD_TAKE_WAIT_SECONDS = {5: 180, 10: 300, 15: 420}
CLOUD_LOOK_WAIT_SECONDS = 30
GRID_BRIEF_USD = 0.0005
GRID_MUSIC_USD = 0.004


def _credits(usd: float) -> int:
    return max(1, round(usd * CREDITS_PER_USD))


def take(backend: str, count: int = 1, length: int = 5) -> dict:
    if backend == "cloud":
        # Cloud bills GPU time, which grows roughly with clip length.
        credits = _credits(CLOUD_TAKE_USD * length / 5) * count
        wait = CLOUD_TAKE_WAIT_SECONDS.get(length, CLOUD_TAKE_WAIT_SECONDS[5]) * count
        return {
            "credits": credits,
            "label": f"~{credits} Cloud credits (est.)",
            "wait": _wait(wait),
        }
    seconds = OWNED_LONG_TAKE_SECONDS.get(length, OWNED_TAKE_SECONDS) * count
    return {"seconds": seconds, "label": f"~{_duration(seconds)} on your GPU (est.)"}


def look(cloud: bool, count: int = 1) -> dict:
    if cloud:
        credits = _credits(CLOUD_LOOK_USD) * count
        return {
            "credits": credits,
            "label": f"~{credits} Cloud credits (est.)",
            "wait": _wait(CLOUD_LOOK_WAIT_SECONDS * count),
        }
    seconds = OWNED_LOOK_SECONDS * count
    return {"seconds": seconds, "label": f"~{_duration(seconds)} on your GPU (est.)"}


def grid(usd: float) -> dict:
    cents = usd * 100
    return {"usd": usd, "label": f"~{cents:.2f}¢ on the Grid (est.)"}


def _duration(seconds: int) -> str:
    return f"{seconds} s" if seconds < 120 else f"{round(seconds / 60)} min"


def _wait(seconds: int) -> str:
    return f"about {_duration(seconds)}"


def table(backend: str, look_cloud: bool) -> dict:
    return {
        "take": take(backend),
        "take3": take(backend, 3),
        "take10": take(backend, length=10),
        "take15": take(backend, length=15),
        "look": look(look_cloud),
        "look3": look(look_cloud, 3),
        "brief": grid(GRID_BRIEF_USD),
        "music": grid(GRID_MUSIC_USD),
    }


def cloud_balance_cents(timeout: float = 10.0) -> float | None:
    """Comfy Cloud balance in cents, or None if it cannot be read."""
    key = os.environ.get("COMFY_API_KEY", "").strip()
    if not key:
        return None
    try:
        response = httpx.get(
            "https://cloud.comfy.org/api/billing/balance",
            headers={"X-API-Key": key},
            timeout=timeout,
        )
        response.raise_for_status()
        return spendable_cents(response.json())
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


def spendable_cents(balance: dict) -> float:
    """The cents Cloud will actually let a render spend.

    Prepaid top-ups land in ``prepaid_balance_cents`` and promotional credit
    in ``cloud_credit_balance_cents``; ``effective_balance_cents`` is the sum
    minus pending charges. A paid account whose promotional credit is spent
    still reads 0 in the credit field, so only the effective figure is safe.
    """
    if "effective_balance_cents" in balance:
        return float(balance["effective_balance_cents"])
    return float(balance.get("prepaid_balance_cents", 0)) + float(
        balance["cloud_credit_balance_cents"]
    )


def actual_label(state: dict) -> str | None:
    """Human label for a finished job's measured cost or time."""
    cents = state.get("actual_cost_cents")
    if cents is not None and cents > 0:
        credits = round(cents / 100 * CREDITS_PER_USD)
        return f"{credits} Cloud credits (measured)"
    seconds = state.get("elapsed_seconds")
    if seconds is not None:
        return f"{seconds:.0f} s (measured)"
    return None
