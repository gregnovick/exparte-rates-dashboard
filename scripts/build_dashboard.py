"""
build_dashboard.py

Downloads the CMS Medicaid renewal CSV, computes ex parte rates from
"Updated" (U) rows only, and injects the result into dashboard_template.html,
writing the final output to docs/index.html.

Environment variables:
  CSV_URL  - URL to download the raw CSV from (set as a GitHub repo variable)

Usage:
  python scripts/build_dashboard.py
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict
from io import StringIO

import requests


def download_csv(url: str) -> str:
    print(f"Downloading CSV from {url} ...")
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    print(f"  Downloaded {len(response.content):,} bytes")
    return response.text


def parse_csv(raw: str) -> dict:
    """
    Parse the raw CMS CSV and return a dict with:
      - states: sorted list of state abbreviations
      - rows:   list of dicts keyed by state abbrev + 'month' + 'date'

    Rules:
      - Only rows where "Original or Updated" == "U" are used
      - Ex parte rate = "Beneficiaries Whose Coverage Was Renewed on an Ex Parte Basis"
                        / "Beneficiaries with a Renewal Due" * 100
      - Rows missing either value are recorded as null
    """
    rows_by_month: dict[str, dict[str, float | None]] = defaultdict(dict)
    month_dates: dict[str, str] = {}
    states_seen: set[str] = set()
    months_seen: set[str] = set()

    reader = csv.DictReader(StringIO(raw))
    for row in reader:
        if row["Original or Updated"].strip() != "U":
            continue

        state = row["State Abbreviation"].strip()
        month = row["Reporting Period"].strip()
        renewal_due = row["Beneficiaries with a Renewal Due"].strip()
        ex_parte = row[
            "Beneficiaries Whose Coverage Was Renewed on an Ex Parte Basis"
        ].strip()

        states_seen.add(state)
        months_seen.add(month)

        # Build a human-readable date label e.g. "3/1/2023"
        year = month[:4]
        mon = str(int(month[4:]))
        month_dates[month] = f"{mon}/1/{year}"

        if renewal_due and ex_parte:
            try:
                rate = round(float(ex_parte) / float(renewal_due) * 100, 2)
                rows_by_month[month][state] = rate
            except (ValueError, ZeroDivisionError):
                rows_by_month[month][state] = None
        else:
            rows_by_month[month][state] = None

    states = sorted(states_seen)
    months = sorted(months_seen)

    all_rows = []
    for m in months:
        entry: dict = {"month": m, "date": month_dates[m]}
        for s in states:
            entry[s] = rows_by_month[m].get(s)
        all_rows.append(entry)

    print(
        f"  Parsed {len(months)} months × {len(states)} states "
        f"({months[0]}–{months[-1]})"
    )
    return {"states": states, "rows": all_rows}


def build_html(data: dict, template_path: str, output_path: str) -> None:
    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    payload = json.dumps(data)

    output = re.sub(
        r"// INJECT_DATA_START\n.*?// INJECT_DATA_END",
        f"// INJECT_DATA_START\nconst INJECTED = {payload};\n// INJECT_DATA_END",
        template,
        flags=re.DOTALL,
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"  Written to {output_path} ({len(output):,} chars)")


def main() -> None:
    csv_url = os.environ.get("CSV_URL")
    if not csv_url:
        print("ERROR: CSV_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    # Paths are relative to repo root (where the Action runs from)
    template_path = "scripts/dashboard_template.html"
    output_path = "docs/index.html"

    raw_csv = download_csv(csv_url)
    data = parse_csv(raw_csv)
    build_html(data, template_path, output_path)
    print("Build complete.")


if __name__ == "__main__":
    main()
