#!/usr/bin/env python3
"""Run schema.sql straight against Postgres, skipping the dashboard.

For when the SQL editor is being awkward. Connects through Supabase's session
pooler, which works over IPv4 — the direct db.<ref>.supabase.co host is often
IPv6-only and fails from home connections.

    python3 run_schema.py                # prompts for the database password
    python3 run_schema.py --check        # connect and list tables, change nothing

The password is the one set when the project was created (Project Settings ->
Database -> Reset database password, if it was not saved). It is read from a
hidden prompt and never stored.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys

try:
    import psycopg2
except ImportError:
    raise SystemExit("psycopg2 is missing — run: python3 -m pip install --user psycopg2-binary")

ROOT = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(ROOT, "airfare-scraper", "schema.sql")
OK, BAD, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m!\033[0m"

CHECKS = """
SELECT table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'public' AND table_name IN ('fares', 'fares_daily', 'scrape_runs')
ORDER BY table_name;
"""


def connect(dsn: str, password: str):
    """Connect using the exact string Supabase gives you.

    Guessing the pooler hostname does not work — the tenant routing prefix
    varies per project, and a wrong guess fails with "tenant/user not found"
    rather than anything useful. So we take the string from the dashboard.
    """
    filled = dsn
    for placeholder in ("[YOUR-PASSWORD]", "[PASSWORD]", "YOUR-PASSWORD"):
        filled = filled.replace(placeholder, password)
    if filled == dsn and password:
        # no placeholder in the string: splice the password in after the user
        filled = re.sub(r"://([^:/@]+)@", lambda m: f"://{m.group(1)}:{password}@", dsn, count=1)
    try:
        conn = psycopg2.connect(filled, connect_timeout=25, sslmode="require")
    except Exception as exc:
        first = str(exc).strip().splitlines()[0]
        hint = ""
        if "not found" in first:
            hint = ("\n   That host does not know this project. Copy the string from the\n"
                    "   green Connect button at the top of your Supabase project page —\n"
                    "   pick Session pooler (port 5432); Transaction pooler cannot run DDL.")
        elif "authentication failed" in first:
            hint = ("\n   Wrong database password. Reset it under\n"
                    "   Project Settings -> Database -> Reset database password.")
        raise SystemExit(f"\n{BAD} {first}{hint}\n")
    host = re.sub(r"://[^@]*@", "://", filled).split("/")[2]
    print(f"  {OK} connected to {host}")
    return conn


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dsn", help="connection string from Supabase's Connect button "
                                  "(Session pooler); the password may stay as [YOUR-PASSWORD]")
    ap.add_argument("--ref", default="ngywgselrypjcyagaast", help="project ref, for the next-step hint")
    ap.add_argument("--check", action="store_true", help="connect and report, change nothing")
    args = ap.parse_args()

    dsn = args.dsn or input(
        "\nPaste the Session pooler connection string from Supabase's Connect button:\n  ").strip()
    if not dsn.startswith("postgres"):
        raise SystemExit(f"{BAD} that does not look like a postgres:// connection string")

    password = getpass.getpass("  database password: ").strip()
    if not password:
        raise SystemExit(f"{BAD} no password given")

    conn = connect(dsn, password)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            if not args.check:
                with open(SCHEMA, encoding="utf-8") as fh:
                    cur.execute(fh.read())
                print(f"  {OK} schema.sql applied")

            cur.execute(CHECKS)
            found = cur.fetchall()
            print()
            for name in ("fares", "fares_daily", "scrape_runs"):
                row = next((r for r in found if r[0] == name), None)
                print(f"  {OK if row else BAD} {name:<12} "
                      f"{row[1].lower() if row else 'missing'}")

            cur.execute("""SELECT tablename, policyname FROM pg_policies
                           WHERE schemaname='public' ORDER BY 1,2;""")
            policies = cur.fetchall()
            print(f"  {OK if policies else BAD} rls policies "
                  f"{', '.join(p[1] for p in policies) or 'none — anon cannot read'}")
    finally:
        conn.close()

    if not args.check:
        print("\nNext:")
        print(f"  python3 setup_supabase.py --url https://{args.ref}.supabase.co\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
