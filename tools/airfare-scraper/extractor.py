"""LLM extraction: fare listing text in, validated JSON out.

Provider-agnostic by construction. Both target models speak the OpenAI
protocol on NVIDIA NIM, so there is one client and the model name is data:
LLM_MODEL from the environment, overridable per call. Every result carries
the model that produced it so accuracy can be compared from the database.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator

import config
from ratelimit import RateLimiter

SYSTEM_PROMPT = (
    "You read scraped flight-search listings and return structured fare data. "
    "You reply with a single JSON object and nothing else."
)

USER_TEMPLATE = """Extract every flight in this {origin}->{destination} listing.

Return JSON exactly like:
{{"flights":[{{"carrier":"IndiGo","flight_number":"6E-955","departure_time":"20:20",\
"base_fare":null,"taxes":null,"udf":null,"convenience_fee":null,"total_fare":6529}}]}}

Rules:
- total_fare: the headline price for one adult, as a number, no currency symbol
  or commas. Ignore struck-through prices and "off with COUPON" discounts.
- base_fare, taxes, udf, convenience_fee: only if the listing actually shows
  that breakup. If it does not, use null. Never estimate or split a total.
- departure_time: 24-hour "HH:MM" of the departure (the first time in the row).
- One entry per flight. Skip rows that are adverts, filters or price alerts.

LISTING:
{listing}"""

RETRY_SUFFIX = (
    "\n\nYour previous reply could not be parsed. Return ONLY valid JSON, "
    "no markdown fences, no commentary, no trailing text."
)


# ------------------------------------------------------------------ schema --
class Flight(BaseModel):
    # typing.Optional (not `X | None`) so the model also builds on Python 3.9,
    # where pydantic cannot evaluate PEP 604 unions in postponed annotations.
    carrier: str
    flight_number: Optional[str] = None
    departure_time: str
    base_fare: Optional[float] = None
    taxes: Optional[float] = None
    udf: Optional[float] = None
    convenience_fee: Optional[float] = None
    total_fare: float

    @field_validator("carrier", "departure_time", mode="before")
    @classmethod
    def _clean_str(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator(
        "base_fare", "taxes", "udf", "convenience_fee", "total_fare", mode="before"
    )
    @classmethod
    def _clean_number(cls, v):
        """Accept '₹6,529', '6529.00', 6529 — reject anything else as None."""
        if v is None or isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            digits = re.sub(r"[^\d.]", "", v)
            return float(digits) if digits.replace(".", "", 1).isdigit() else None
        return None

    @field_validator("total_fare")
    @classmethod
    def _sane_total(cls, v):
        if not (300 <= v <= 500_000):
            raise ValueError(f"total_fare {v} outside plausible INR range")
        return v


class FlightList(BaseModel):
    flights: List[Flight] = Field(default_factory=list)


@dataclass
class ExtractionResult:
    flights: list[Flight]
    model_used: str
    latency_ms: int
    attempts: int
    prompt_chars: int
    chunks: int = 1
    error: str | None = None
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None


# --------------------------------------------------------------- extractor --
class Extractor:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        limiter: RateLimiter | None = None,
    ):
        self.model = model or config.LLM_MODEL
        key = api_key or config.NVIDIA_API_KEY
        if not key:
            raise SystemExit(
                "NVIDIA_API_KEY is not set — copy .env.example to .env and fill it in"
            )
        self.client = OpenAI(
            api_key=key,
            base_url=base_url or config.NVIDIA_BASE_URL,
            timeout=config.LLM_TIMEOUT_S,
            # The SDK retries twice by default, which quietly turns a 90s
            # timeout into a 270s one. We do our own retry with a stricter
            # prompt, so let the configured timeout mean what it says.
            max_retries=0,
        )
        self.limiter = limiter or RateLimiter(config.NIM_REQUESTS_PER_MINUTE)
        self._dead: set = set()          # models that answered 410/404 this run

    def _live_model(self, failed: str) -> str:
        """Swap to the next configured model when one is retired mid-run."""
        self._dead.add(failed)
        for candidate in config.FALLBACK_MODELS:
            if candidate not in self._dead:
                return candidate
        return failed                    # nothing left; let the caller fail honestly

    # -- public ------------------------------------------------------------
    def extract(
        self,
        rows: Iterable[str] | str,
        origin: str = "",
        destination: str = "",
        model: str | None = None,
    ) -> ExtractionResult:
        """Extract flights, splitting long listings so replies never truncate."""
        model = model or self.model
        if model in self._dead:
            model = self._live_model(model)
        row_list = _as_rows(rows)
        chunks = _chunk(row_list, config.MAX_PROMPT_CHARS)

        flights: list[Flight] = []
        attempts = 0
        errors: list[str] = []
        started = time.monotonic()
        prompt_chars = 0
        last_raw = ""

        for chunk in chunks:
            listing = "\n".join(chunk)
            prompt_chars += len(listing)
            parsed, used, raw, tries, err = self._one_chunk(
                listing, origin, destination, model
            )
            attempts += tries
            last_raw = raw or last_raw
            if err:
                errors.append(err)
            else:
                flights.extend(parsed)

        latency = int((time.monotonic() - started) * 1000)
        error = None
        if errors and not flights:
            error = errors[0]
        elif errors:
            error = f"{len(errors)}/{len(chunks)} chunks failed: {errors[0]}"

        return ExtractionResult(
            flights=_dedupe(flights),
            model_used=model,
            latency_ms=latency,
            attempts=attempts,
            prompt_chars=prompt_chars,
            chunks=len(chunks),
            error=error,
            raw=last_raw,
        )

    # -- internals ---------------------------------------------------------
    def _one_chunk(self, listing, origin, destination, model):
        prompt = USER_TEMPLATE.format(
            origin=origin or "?", destination=destination or "?", listing=listing
        )
        last_error = ""
        raw = ""
        for attempt in (1, 2):  # one retry, with a stricter instruction
            try:
                raw = self._call(prompt if attempt == 1 else prompt + RETRY_SUFFIX, model)
            except Exception as exc:  # transport / rate / server error
                last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
                text = str(exc)
                if "410" in text or "end of life" in text.lower() or "404" in text:
                    replacement = self._live_model(model)
                    if replacement != model:
                        last_error += f" — {model} is gone; falling back to {replacement}"
                        model = replacement
                        continue         # retry this same chunk on the new model
                    last_error += " — no working model left in FALLBACK_MODELS"
                    break
                continue
            try:
                payload = _loads_json(raw)
                validated = FlightList.model_validate(payload)
            except (ValueError, ValidationError) as exc:
                last_error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
                continue
            return validated.flights, model, raw, attempt, None
        return [], model, raw, 2, last_error or "unknown extraction failure"

    def models(self) -> list:
        """Model ids this API key can reach, newest catalogue first."""
        return sorted(m.id for m in self.client.models.list().data)

    def _call(self, prompt: str, model: str) -> str:
        self.limiter.acquire()
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.MAX_COMPLETION_TOKENS,
        )
        return response.choices[0].message.content or ""


# ------------------------------------------------------------------ helpers --
def _as_rows(rows: Iterable[str] | str) -> list[str]:
    if isinstance(rows, str):
        return [r for r in rows.splitlines() if r.strip()]
    return [r for r in rows if r and r.strip()]


def _chunk(rows: list[str], max_chars: int) -> list[list[str]]:
    """Group rows so no single prompt gets long enough to truncate a reply."""
    if not rows:
        return [[]]
    out: list[list[str]] = [[]]
    size = 0
    for row in rows:
        if out[-1] and size + len(row) > max_chars:
            out.append([])
            size = 0
        out[-1].append(row)
        size += len(row) + 1
    return out


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def _loads_json(raw: str) -> dict:
    """Tolerate fences and stray prose; reject anything that isn't an object."""
    text = _FENCE.sub("", (raw or "").strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("JSON object never closed (reply truncated?)")


def _dedupe(flights: list[Flight]) -> list[Flight]:
    seen, out = set(), []
    for f in flights:
        key = (f.carrier.lower(), f.flight_number, f.departure_time, f.total_fare)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


# --------------------------------------------------------------------- cli --
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run one extraction over saved listing text.")
    ap.add_argument("--file", help="fare-listing text (fetcher.py --out)")
    ap.add_argument("--list-models", action="store_true",
                    help="print the catalogue (note: this endpoint needs no auth)")
    ap.add_argument("--check", action="store_true",
                    help="send one tiny completion — the only real test of the key")
    ap.add_argument("--model", default=None, help=f"overrides LLM_MODEL {config.KNOWN_MODELS}")
    ap.add_argument("--route", default="DEL-BOM")
    args = ap.parse_args(argv)

    if args.list_models:
        print("note: /v1/models answers without a key, so this does not test yours;\n"
              "      use --check for that.\n", file=sys.stderr)
        for model_id in Extractor(model=args.model).models():
            print(model_id)
        return 0

    if args.check:
        ex = Extractor(model=args.model)
        model = args.model or config.LLM_MODEL
        print(f"model   : {model}")
        print(f"endpoint: {config.NVIDIA_BASE_URL}")
        started = time.monotonic()
        try:
            reply = ex._call("Reply with the single word: ok", model)
            print(f"result  : OK in {time.monotonic()-started:.1f}s — {reply.strip()[:40]!r}")
            return 0
        except Exception as exc:
            elapsed = time.monotonic() - started
            detail = str(exc)[:200]
            print(f"result  : FAILED after {elapsed:.1f}s\n          {type(exc).__name__}: {detail}")
            if "401" in detail or "Authentication" in detail:
                print("\n  401 means the key is wrong, malformed or revoked. Re-copy it from\n"
                      "  build.nvidia.com — the token only, not the surrounding code sample.")
            elif "Timeout" in type(exc).__name__ or elapsed > 30:
                print("\n  No response at all. The key authenticates but this model is not\n"
                      "  serving your account. Try another id from --list-models, or point\n"
                      "  NVIDIA_BASE_URL at any other OpenAI-compatible provider.")
            return 1
    if not args.file:
        print("--file is required (or use --list-models)", file=sys.stderr)
        return 2

    origin, _, destination = args.route.partition("-")
    with open(args.file, encoding="utf-8") as fh:
        text = fh.read()

    result = Extractor(model=args.model).extract(text, origin, destination)
    print(
        f"model={result.model_used} flights={len(result.flights)} "
        f"attempts={result.attempts} chunks={result.chunks} "
        f"prompt_chars={result.prompt_chars} latency={result.latency_ms}ms",
        file=sys.stderr,
    )
    if result.error:
        print(f"error: {result.error}", file=sys.stderr)
    print(json.dumps([f.model_dump() for f in result.flights], indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
