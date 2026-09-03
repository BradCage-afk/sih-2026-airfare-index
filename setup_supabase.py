#!/usr/bin/env python3
"""Point the scraper and the dashboard at a Supabase project.

Checks the credentials actually work and the schema is in place before it
writes anything, so a typo fails here instead of halfway through a demo.

    python setup_supabase.py

Keys are read from a hidden prompt, never from the command line — a key in
your shell history or in a chat log is a key you have to rotate.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(ROOT, "dashboard", "index.html")
ENV = os.path.join(ROOT, "airfare-scraper", ".env")
TABLES = ["fares", "fares_daily", "scrape_runs"]

OK, BAD, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m!\033[0m"


def key_role(key: str) -> str:
    """What kind of key is this? Decoded locally — nothing is sent anywhere.

    Legacy Supabase keys are JWTs whose payload carries `role`; the anon and
    service_role keys look identical otherwise, and mixing them up is the one
    mistake here that actually matters. Newer keys say it in the prefix.
    """
    if key.startswith("sb_publishable_"):
        return "anon"
    if key.startswith("sb_secret_"):
        return "service_role"
    parts = key.split(".")
    if len(parts) == 3:                      # looks like a JWT
        try:
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            return str(claims.get("role", "unknown"))
        except Exception:
            return "unknown"
    return "unknown"


def probe(url: str, key: str, table: str, timeout: float = 20.0):
    """Returns (ok, detail). Uses the REST API exactly as the dashboard does."""
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}?select=*&limit=1",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            rows = json.loads(resp.read() or b"[]")
            return True, f"{len(rows)} row(s) readable"
    except urllib.error.HTTPError as exc:
        body = (exc.read() or b"").decode("utf-8", "replace")[:200]
        try:
            body = json.loads(body).get("message", body)
        except Exception:
            pass
        return False, f"HTTP {exc.code} — {body}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def patch_dashboard(url: str, anon: str) -> None:
    with open(DASHBOARD, encoding="utf-8") as fh:
        html = fh.read()
    # replace the whole line so the placeholder comment goes with it
    html, n1 = re.subn(r'\n  url: "[^"]*",[^\n]*', f'\n  url: "{url}",', html, count=1)
    html, n2 = re.subn(r'\n  key: "[^"]*",[^\n]*', f'\n  key: "{anon}",', html, count=1)
    if not (n1 and n2):
        raise SystemExit(f"{BAD} could not find the SUPABASE block in {DASHBOARD}")
    with open(DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(html)


def write_env(url: str, service: str) -> None:
    existing = {}
    if os.path.exists(ENV):
        for line in open(ENV, encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    elif os.path.exists(ENV + ".example"):
        for line in open(ENV + ".example", encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    existing["SUPABASE_URL"] = url
    existing["SUPABASE_KEY"] = service
    existing.setdefault("LLM_MODEL", "deepseek-ai/deepseek-v4-pro-0813")
    existing.setdefault("NVIDIA_API_KEY", "")

    with open(ENV, "w", encoding="utf-8") as fh:
        fh.write("# written by setup_supabase.py — never commit this file\n")
        for k, v in existing.items():
            fh.write(f"{k}={v}\n")
    os.chmod(ENV, 0o600)


def real_nvidia_key() -> bool:
    """Is the key in .env an actual key, or the example placeholder?"""
    if not os.path.exists(ENV):
        return False
    for line in open(ENV, encoding="utf-8"):
        if line.startswith("NVIDIA_API_KEY="):
            value = line.partition("=")[2].strip()
            return bool(value) and "xxxx" not in value.lower()
    return False


def set_env_key(name: str, label: str, where: str) -> int:
    """Write one key into .env without disturbing anything else."""
    if not os.path.exists(ENV):
        raise SystemExit(f"{BAD} {ENV} does not exist — run the full setup first")
    print(f"  From {where}\n")
    key = getpass.getpass(f"  {label}: ").strip()
    if not key:
        raise SystemExit(f"{BAD} nothing entered")
    if any(ch.isspace() for ch in key):
        raise SystemExit(f"{BAD} that contains whitespace — paste the token only")
    lines, out, seen = open(ENV, encoding="utf-8").read().splitlines(), [], False
    for line in lines:
        if line.startswith(f"{name}="):
            out.append(f"{name}={key}"); seen = True
        else:
            out.append(line)
    if not seen:
        out.append(f"{name}={key}")
    with open(ENV, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    os.chmod(ENV, 0o600)
    print(f"  {OK} {name} written to {ENV}")
    return 0


def set_nvidia_key() -> int:
    """Update just NVIDIA_API_KEY in .env, without touching anything else."""
    if not os.path.exists(ENV):
        raise SystemExit(f"{BAD} {ENV} does not exist — run the full setup first")
    print("  Paste the key itself — not the Python snippet the NVIDIA site shows you.")
    print("  It is one line starting with nvapi-\n")
    key = getpass.getpass("  NVIDIA_API_KEY: ").strip()
    if not key:
        raise SystemExit(f"{BAD} nothing entered")
    if "xxxx" in key.lower():
        raise SystemExit(f"{BAD} that is the placeholder from .env.example, not a key")
    if any(ch.isspace() for ch in key) or not key.startswith("nvapi-"):
        raise SystemExit(
            f"\n{BAD} That is not an API key — it is {key[:32]!r}…\n"
            "   NVIDIA's page shows a code sample around the key. Copy only the\n"
            "   token: one line, starts with nvapi-, no spaces.\n")
    if len(key) < 40:
        raise SystemExit(f"{BAD} that key looks truncated ({len(key)} chars; expect ~70)")
    lines = open(ENV, encoding="utf-8").read().splitlines()
    out, seen = [], False
    for line in lines:
        if line.startswith("NVIDIA_API_KEY="):
            out.append(f"NVIDIA_API_KEY={key}"); seen = True
        else:
            out.append(line)
    if not seen:
        out.append(f"NVIDIA_API_KEY={key}")
    with open(ENV, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    os.chmod(ENV, 0o600)
    print(f"  {OK} NVIDIA_API_KEY written to {ENV}")
    print("\nCheck it reaches a live model:")
    print("  cd airfare-scraper && python3 extractor.py --list-models\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="https://<project>.supabase.co")
    ap.add_argument("--check-only", action="store_true",
                    help="verify credentials and schema, change nothing")
    ap.add_argument("--nvidia", action="store_true",
                    help="only set NVIDIA_API_KEY in .env, leave Supabase alone")
    ap.add_argument("--travelpayouts", action="store_true",
                    help="only set TRAVELPAYOUTS_TOKEN in .env")
    args = ap.parse_args()

    if args.nvidia:
        return set_nvidia_key()
    if args.travelpayouts:
        return set_env_key("TRAVELPAYOUTS_TOKEN", "Travelpayouts API token",
                           "travelpayouts.com -> Profile -> API token")

    print("\nSupabase → Settings → API is where all three of these live.\n")
    url = (args.url or input("  Project URL  : ")).strip().rstrip("/")
    if not re.match(r"^https?://[^/]+", url):
        raise SystemExit(f"{BAD} that does not look like a URL")

    anon = getpass.getpass("  anon key     : ").strip()
    if not anon:
        raise SystemExit(f"{BAD} the anon key is required — the dashboard reads with it")
    service = getpass.getpass("  service_role : (blank to skip the scraper) ").strip()

    anon_role = key_role(anon)
    if anon_role == "service_role":
        raise SystemExit(
            f"\n{BAD} That is the SERVICE_ROLE key, not the anon key.\n"
            "   It bypasses row-level security, and the dashboard ships its key to\n"
            "   every visitor — this would hand the public write access to your\n"
            "   database. Go back and copy the anon / publishable one.\n")
    if anon_role not in ("anon", "unknown"):
        print(f"{WARN} the anon key decodes to role {anon_role!r}, which is unexpected")

    if service:
        service_role = key_role(service)
        if service_role == "anon":
            raise SystemExit(
                f"\n{BAD} That is the ANON key in the service_role slot.\n"
                "   The scraper writes, and RLS only grants anon SELECT, so every\n"
                "   insert would fail. Copy the service_role / secret key instead.\n")

    print(f"\nChecking {url} …")
    failures = 0
    for table in TABLES:
        ok, detail = probe(url, anon, table)
        print(f"  {OK if ok else BAD} {table:<12} {detail}")
        failures += not ok

    if failures:
        print(f"\n{WARN} {failures} of {len(TABLES)} not readable.")
        print("   If they are missing: open the Supabase SQL editor and run")
        print("   airfare-scraper/schema.sql, then run this again.")
        print("   If it says permission denied: the RLS policies at the bottom")
        print("   of schema.sql are what grant the anon role read access.")
        if not args.check_only:
            return 1

    if service:
        ok, detail = probe(url, service, "fares")
        print(f"  {OK if ok else BAD} {'service_role':<12} {detail}")
        if not ok and not args.check_only:
            print(f"\n{BAD} the service_role key could not read `fares` — check you copied the right one")
            return 1

    if args.check_only:
        print("\nchecked only, nothing written.\n")
        return 0

    patch_dashboard(url, anon)
    print(f"\n  {OK} dashboard/index.html now points at your project")
    if service:
        write_env(url, service)
        print(f"  {OK} airfare-scraper/.env written (chmod 600)")
        if not real_nvidia_key():
            print(f"  {WARN} NVIDIA_API_KEY is still the placeholder — set it with:")
            print(f"      python3 setup_supabase.py --nvidia")
    else:
        print(f"  {WARN} no service_role key given, so the scraper is not configured")

    print("\nNext:")
    print("  cd dashboard && npx vercel deploy --prod       # push the live dashboard")
    print("  cd airfare-scraper && python main.py --tier hot  # put real fares in it\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
