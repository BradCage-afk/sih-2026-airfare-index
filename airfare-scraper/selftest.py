"""Offline end-to-end check: every stage except NIM's own availability.

Runs the real extractor against a local stand-in for the OpenAI-compatible
endpoint, over the real fare listing in fixtures/, and checks the behaviours
that matter when a model misbehaves: markdown fences, a truncated reply, a
non-JSON reply, and a 5xx. Then writes through db.py in dry-run mode.

    python selftest.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tests.mock_nim import serve  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "del-bom-cleartrip.txt")
PORT = 8848
PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"


def check(label, condition, detail=""):
    print(f"  {PASS if condition else FAIL}  {label}{('  — ' + detail) if detail else ''}")
    return bool(condition)


def run() -> int:
    os.environ.setdefault("NVIDIA_API_KEY", "mock-key")
    os.environ["NVIDIA_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"

    import config
    config.NVIDIA_BASE_URL = os.environ["NVIDIA_BASE_URL"]
    config.NVIDIA_API_KEY = "mock-key"
    config.LLM_TIMEOUT_S = 15

    from db import FareStore, records_from_flights
    from extractor import Extractor

    with open(FIXTURE, encoding="utf-8") as fh:
        rows = [r for r in fh.read().splitlines() if r.strip()]
    print(f"\nlisting: {os.path.relpath(FIXTURE)} ({len(rows)} rows)\n")

    ok = True
    results = {}
    for mode in ["clean", "fenced", "truncated", "server_error", "garbage"]:
        server, _ = serve(PORT, mode)
        try:
            extractor = Extractor(model="mock/test-model")
            result = extractor.extract(rows, "DEL", "BOM")
            results[mode] = result
        finally:
            server.shutdown()
            server.server_close()

        print(f"mode={mode}")
        if mode in ("clean", "fenced"):
            ok &= check(f"{mode}: flights parsed", len(result.flights) > 0,
                        f"{len(result.flights)} flights, {result.chunks} chunk(s)")
            ok &= check(f"{mode}: no error", result.ok, result.error or "")
        elif mode == "truncated":
            ok &= check("truncated: recovered on the stricter retry",
                        len(result.flights) > 0 and result.attempts >= 2,
                        f"{len(result.flights)} flights after {result.attempts} attempts")
        elif mode == "server_error":
            ok &= check("5xx: retried and recovered", len(result.flights) > 0,
                        f"{len(result.flights)} flights after {result.attempts} attempts")
        elif mode == "garbage":
            ok &= check("garbage: reported as an error, no rows invented",
                        not result.flights and result.error is not None,
                        (result.error or "")[:60])
        print()

    clean = results["clean"]
    ok &= check("every fare is a plausible INR total",
                all(300 <= f.total_fare <= 500_000 for f in clean.flights))
    ok &= check("components stay null when the page does not show them",
                all(f.base_fare is None for f in clean.flights))
    ok &= check("duplicate rows collapsed",
                len(clean.flights) <= len(rows),
                f"{len(rows)} rows -> {len(clean.flights)} flights")
    ok &= check("model recorded on the result", clean.model_used == "mock/test-model")

    with tempfile.NamedTemporaryFile("r+", suffix=".jsonl", delete=False) as tmp:
        path = tmp.name
    store = FareStore(dry_run=True, dry_run_path=path)
    records = records_from_flights(clean.flights, origin="DEL", destination="BOM",
                                   source="cleartrip", advance_days=7,
                                   model_used=clean.model_used)
    written = store.write(records)
    with open(path, encoding="utf-8") as fh:
        first = json.loads(fh.readline())
    os.unlink(path)

    expected = {"origin", "destination", "carrier", "departure_time", "source",
                "advance_window_days", "base_fare", "taxes", "udf",
                "convenience_fee", "total_fare", "model_used", "scraped_at"}
    ok &= check("db.write returned a count", written == len(records), f"{written} rows")
    ok &= check("row matches the fares schema", set(first) == expected,
                ", ".join(sorted(set(first) ^ expected)) or "exact match")

    print("\n" + ("all checks passed" if ok else "SOME CHECKS FAILED") + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
