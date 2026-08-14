#!/usr/bin/env python3
"""Classify Yandex Webmaster queries and build an actionable SEO opportunity map."""

import argparse
import csv
import datetime as dt
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "raw", "analytics")
REPORT_DIR = os.path.join(ROOT, "reports")

EXCLUDE_PATTERNS = [
    r"мастерски[ея]\s+златоуст",
    r"мастера\s+златоуст",
    r"\bзоф\b",
    r"\bzlatm\b",
    r"zlatoystmaster",
    r"русские\s+самоцветы",
    r"как\s+сделать",
    r"своими\s+руками",
    r"авито",
    r"озон",
    r"wildberries",
]

REVIEW_PATTERNS = [
    r"ювелирн.*мастер",
    r"мастерск",
    r"мастер(?:а|ов|ы)?\s+златоуст",
    r"златоустовск.*мастер",
    r"фирм.*дела.*подар",
]

CLUSTERS = [
    ("brand", [r"алмазфонд", r"almazfond", r"алмаз фонд"]),
    (
        "gift_intent",
        [
            r"подар",
            r"сувенир",
            r"руковод",
            r"директор",
            r"начальник",
            r"партнер",
            r"юбиле",
            r"корпоратив",
            r"\bvip\b",
            r"\bвип\b",
            r"элитн",
            r"эксклюзив",
        ],
    ),
    (
        "weapons",
        [r"оруж", r"нож", r"кинжал", r"сабл", r"\bмеч(?:а|и|ом|у)?\b", r"топор"],
    ),
    (
        "tableware",
        [r"икорниц", r"подстак", r"чай", r"кофе", r"рюм", r"бокал", r"блюд", r"посуда"],
    ),
    (
        "interior",
        [r"скульп", r"ваза", r"часы", r"ламп", r"ларец", r"панно", r"интерьер", r"кабинет"],
    ),
    ("eastern_religious", [r"восточ", r"православ", r"икон", r"коран", r"99 имен"]),
    ("zlatoust", [r"златоуст"]),
]

TARGET_RULES = [
    (r"руковод", "/podarki-rukovoditelyu/"),
    (r"директор", "/podarok-direktoru/"),
    (r"начальник", "/podarki-nachalniku/"),
    (r"партнер", "/podarki-partneram/"),
    (r"юбиле", "/podarki-na-yubiley/"),
    (r"корпоратив", "/korporativnye-podarki/"),
    (r"бизнес.?сувенир", "/biznes-suveniry-premium/"),
    (r"мужчин", "/podarki-muzhchine/"),
    (r"элитн", "/elitnye-podarki/"),
    (r"\bvip\b|\bвип\b|эксклюзив|дорог.*подар", "/vip-podarki/"),
    (
        r"оруж|нож|кинжал|сабл|\bмеч(?:а|и|ом|у)?\b|топор",
        "/categories/suvenirnoe-oruzhie/",
    ),
    (
        r"икорниц|чай|кофе|подстак|рюм|бокал",
        "/categories/ikorniczy-chajno-kofejnye-nabory/",
    ),
    (r"блюд", "/categories/biznes-suveniry/blyuda-suvenirnye/"),
    (r"восточ|коран|99 имен|99 имён|мечет", "/categories/vostochnaya-kollekcziya/"),
    (r"православ|икон", "/categories/pravoslavnye-izdeliya/"),
    (r"скульп", "/categories/skulptury-v-interer/"),
    (
        r"ваза|часы|ламп|ларец|панно|интерьер|кабинет",
        "/categories/eksklyuzivnyj-dekor-dlya-doma/",
    ),
    (r"златоуст.*(подар|сувенир|магазин)|магазин.*златоуст", "/categories/"),
    (r"алмазфонд|almazfond|алмаз фонд", "/"),
]


def matches(text, patterns):
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def classify_query(text):
    normalized = " ".join(text.lower().split())
    if matches(normalized, EXCLUDE_PATTERNS):
        return "competitor_or_noise", "exclude", ""
    if matches(normalized, REVIEW_PATTERNS):
        return "manual_review", "review", ""

    cluster = "manual_review"
    for name, patterns in CLUSTERS:
        if matches(normalized, patterns):
            cluster = name
            break

    target = ""
    for pattern, url in TARGET_RULES:
        if re.search(pattern, normalized, re.IGNORECASE):
            target = url
            break

    if cluster == "manual_review" and not target:
        relevance = "review"
    else:
        relevance = "relevant"
    return cluster, relevance, target


def priority(relevance, position, clicks, shows):
    if relevance == "exclude":
        return "EXCLUDE"
    if relevance == "review":
        return "REVIEW"
    if position and 8 <= position <= 20 and shows >= 2:
        return "P1"
    if position and 20 < position <= 35 and shows >= 2:
        return "P2"
    if position and position < 8 and shows >= 3 and clicks == 0:
        return "P3_CTR"
    if position and position > 35:
        return "P3_LONG"
    return "MONITOR"


def latest_source():
    files = glob.glob(os.path.join(RAW_DIR, "webmaster_queries_*.csv"))
    if not files:
        raise SystemExit("[!] No Webmaster CSV files found in raw/analytics")
    return max(files, key=os.path.getmtime)


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    source = os.path.abspath(args.source) if args.source else latest_source()
    rows = []
    with open(source, encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            query = item.get("query", "").strip()
            shows = int(number(item.get("shows")))
            clicks = int(number(item.get("clicks")))
            position = number(item.get("avg_show_position"), None)
            cluster, relevance, target = classify_query(query)
            rows.append(
                {
                    **item,
                    "cluster": cluster,
                    "relevance": relevance,
                    "priority": priority(relevance, position, clicks, shows),
                    "target_url": target,
                    "manual_mapping": "yes" if relevance != "exclude" and not target else "",
                }
            )

    order = {"P1": 0, "P2": 1, "P3_CTR": 2, "P3_LONG": 3, "MONITOR": 4, "REVIEW": 5, "EXCLUDE": 6}
    rows.sort(
        key=lambda row: (
            order.get(row["priority"], 99),
            -int(number(row.get("shows"))),
            number(row.get("avg_show_position"), 999),
        )
    )

    os.makedirs(REPORT_DIR, exist_ok=True)
    csv_path = os.path.join(REPORT_DIR, f"webmaster-query-opportunities-{args.date}.csv")
    md_path = os.path.join(REPORT_DIR, f"webmaster-query-opportunities-{args.date}.md")
    fieldnames = list(rows[0].keys()) if rows else []
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    relevant = [row for row in rows if row["relevance"] == "relevant"]
    review = [row for row in rows if row["relevance"] == "review"]
    excluded = [row for row in rows if row["relevance"] == "exclude"]
    priorities = {
        name: [row for row in rows if row["priority"] == name]
        for name in ("P1", "P2", "P3_CTR", "P3_LONG")
    }

    cluster_stats = {}
    for row in relevant:
        stats = cluster_stats.setdefault(
            row["cluster"], {"queries": 0, "shows": 0, "clicks": 0, "p1": 0, "p2": 0}
        )
        stats["queries"] += 1
        stats["shows"] += int(number(row.get("shows")))
        stats["clicks"] += int(number(row.get("clicks")))
        if row["priority"] in ("P1", "P2"):
            stats[row["priority"].lower()] += 1

    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("# Карта поискового спроса Яндекс.Вебмастера\n\n")
        handle.write(f"Дата выгрузки: {args.date}. Источник: полный экспорт за выбранный период.\n\n")
        handle.write("## Сводка\n\n")
        handle.write(f"- Всего запросов: **{len(rows)}**.\n")
        handle.write(f"- Целевых: **{len(relevant)}**.\n")
        handle.write(f"- На ручную проверку: **{len(review)}**.\n")
        handle.write(f"- Исключено как шум/чужой спрос: **{len(excluded)}**.\n")
        handle.write(f"- P1, позиции 8-20: **{len(priorities['P1'])}**.\n")
        handle.write(f"- P2, позиции 20-35: **{len(priorities['P2'])}**.\n")
        handle.write(f"- P3 CTR: **{len(priorities['P3_CTR'])}**.\n\n")
        handle.write("## Кластеры\n\n")
        handle.write("| Кластер | Запросы | Показы | Клики | P1 | P2 |\n")
        handle.write("|---|---:|---:|---:|---:|---:|\n")
        for name, stats in sorted(cluster_stats.items(), key=lambda item: -item[1]["shows"]):
            handle.write(
                f"| {name} | {stats['queries']} | {stats['shows']} | {stats['clicks']} | "
                f"{stats['p1']} | {stats['p2']} |\n"
            )
        handle.write("\n## Приоритет P1\n\n")
        handle.write("| Запрос | Показы | Клики | Позиция | Целевая страница |\n")
        handle.write("|---|---:|---:|---:|---|\n")
        for row in priorities["P1"][:40]:
            handle.write(
                f"| {row['query'].replace('|', '/')} | {row['shows']} | {row['clicks']} | "
                f"{number(row['avg_show_position']):.1f} | {row['target_url'] or 'ручная привязка'} |\n"
            )
        handle.write("\n## Правила применения\n\n")
        handle.write("- P1 дорабатываются в первую очередь: релевантность, сниппет и внутренняя перелинковка.\n")
        handle.write("- P2 получают усиление после исключения каннибализации с соседними страницами.\n")
        handle.write("- EXCLUDE не используются в текстах и не влияют на приоритет страниц.\n")
        handle.write("- REVIEW проверяются вручную перед любыми изменениями сайта.\n")

    print(f"Source: {source}")
    print(
        f"Queries: {len(rows)} | relevant: {len(relevant)} | review: {len(review)} | "
        f"excluded: {len(excluded)}"
    )
    print(f"P1: {len(priorities['P1'])} | P2: {len(priorities['P2'])}")
    print(f"CSV: {csv_path}")
    print(f"MD:  {md_path}")


if __name__ == "__main__":
    main()
