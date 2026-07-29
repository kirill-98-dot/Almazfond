#!/usr/bin/env python3
"""Collect all search queries for almazfond.ru from Yandex Webmaster API v4."""

import argparse
import csv
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATHS = [
    os.path.join(ROOT, "secrets", "yandex-webmaster.env"),
    os.path.join(ROOT, "raw", "keywords", ".env"),
]
OUT_DIR = os.path.join(ROOT, "raw", "analytics")

API = "https://api.webmaster.yandex.net/v4"
OUR = "almazfond.ru"
INDICATORS = ["TOTAL_SHOWS", "TOTAL_CLICKS", "AVG_SHOW_POSITION", "AVG_CLICK_POSITION"]
API_PAGE_LIMIT = 500


def load_env(path):
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def get(url, token):
    request = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all_queries(uid, host_id, token, date_from, date_to, page_size, max_rows):
    queries = []
    offset = 0
    pages = 0

    while True:
        remaining = max_rows - len(queries) if max_rows else page_size
        current_limit = min(page_size, remaining) if max_rows else page_size
        if current_limit <= 0:
            break

        params = [
            ("order_by", "TOTAL_SHOWS"),
            ("date_from", date_from),
            ("date_to", date_to),
            ("limit", str(current_limit)),
            ("offset", str(offset)),
        ]
        params += [("query_indicator", indicator) for indicator in INDICATORS]
        url = (
            f"{API}/user/{uid}/hosts/{host_id}/search-queries/popular?"
            + urllib.parse.urlencode(params)
        )
        page = get(url, token)
        batch = page.get("queries", [])
        pages += 1

        if not batch:
            break
        queries.extend(batch)
        offset += len(batch)

        if len(batch) < current_limit or (max_rows and len(queries) >= max_rows):
            break

    # A changing API result can shift offsets. Keep one row per exact query text.
    unique = {}
    for query in queries:
        text = query.get("query_text", "")
        if text and text not in unique:
            unique[text] = query
    return list(unique.values()), pages, len(queries) - len(unique)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hosts", action="store_true", help="List available hosts and exit")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--page-size", type=int, default=API_PAGE_LIMIT)
    parser.add_argument("--max-rows", type=int, default=0, help="0 means all available rows")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Legacy alias for --max-rows; retained for existing commands",
    )
    args = parser.parse_args()

    page_size = min(max(args.page_size, 1), API_PAGE_LIMIT)
    max_rows = args.limit if args.limit is not None else max(args.max_rows, 0)

    env = {}
    for env_path in reversed(ENV_PATHS):
        env.update(load_env(env_path))
    token = env.get("YANDEX_WEBMASTER_TOKEN")
    if not token:
        sys.exit("[!] YANDEX_WEBMASTER_TOKEN is missing in secrets/yandex-webmaster.env")

    try:
        user_data = get(f"{API}/user/", token)
        uid = user_data.get("user_id") or user_data.get("userId")
        if not uid:
            raise RuntimeError("Yandex Webmaster API did not return user_id")
        hosts = get(f"{API}/user/{uid}/hosts", token).get("hosts", [])
    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", "replace")[:300]
        sys.exit(f"[!] HTTP {error.code}: {message}")

    print(f"user_id: {uid} | hosts: {len(hosts)}")
    for host in hosts:
        print(
            f"  - {host.get('host_id')}  {host.get('ascii_host_url')}  "
            f"verified={host.get('verified')}"
        )
    if args.hosts:
        return

    host = next(
        (item for item in hosts if OUR in (item.get("ascii_host_url") or "")),
        None,
    )
    if not host:
        sys.exit(f"[!] Verified host {OUR} was not found in Yandex Webmaster")
    host_id = host["host_id"]

    today = dt.date.today()
    date_from = (today - dt.timedelta(days=args.days)).isoformat()
    date_to = today.isoformat()

    try:
        queries, pages, duplicate_count = fetch_all_queries(
            uid, host_id, token, date_from, date_to, page_size, max_rows
        )
    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", "replace")[:300]
        sys.exit(f"[!] HTTP {error.code} while collecting queries: {message}")

    rows = []
    for query in queries:
        indicators = query.get("indicators", {})
        shows = indicators.get("TOTAL_SHOWS") or 0
        clicks = indicators.get("TOTAL_CLICKS") or 0
        rows.append(
            {
                "query": query.get("query_text", ""),
                "shows": shows,
                "clicks": clicks,
                "ctr_%": round(100 * clicks / shows, 2) if shows else 0,
                "avg_show_position": indicators.get("AVG_SHOW_POSITION"),
                "avg_click_position": indicators.get("AVG_CLICK_POSITION"),
            }
        )
    rows.sort(key=lambda row: row["shows"] or 0, reverse=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = today.isoformat()
    csv_path = os.path.join(OUT_DIR, f"webmaster_queries_{stamp}.csv")
    json_path = os.path.join(OUT_DIR, f"webmaster_queries_{stamp}.json")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "query",
                "shows",
                "clicks",
                "ctr_%",
                "avg_show_position",
                "avg_click_position",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "collection": {
                    "host": OUR,
                    "date_from": date_from,
                    "date_to": date_to,
                    "pages": pages,
                    "page_size": page_size,
                    "max_rows": max_rows,
                    "duplicates_removed": duplicate_count,
                },
                "queries": queries,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    quick = [
        row
        for row in rows
        if row["avg_show_position"] and 11 <= row["avg_show_position"] <= 30
    ]
    print(f"\nQueries: {len(rows)} | period: {date_from}..{date_to} | pages: {pages}")
    print(f"Duplicates removed: {duplicate_count}")
    print(f"Quick-win candidates at positions 11-30: {len(quick)}")
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
