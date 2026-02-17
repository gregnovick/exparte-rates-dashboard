"""
build_dashboard.py

Fetches the current CSV download URL from the CMS Medicaid dataset API,
downloads the CSV, computes ex parte rates from "Updated" (U) rows only,
and injects the result into dashboard_template.html, writing the final
output to docs/index.html.

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

METADATA_URL = (
    "https://data.medicaid.gov/api/1/metastore/schemas/dataset/items"
    "/5abea2e0-3f8e-4b49-a50d-d63d5fd9103c?show-reference-ids=false"
)


def get_csv_url() -> str:
    """Fetch the dataset metadata and extract the current CSV download URL."""
    print("Fetching dataset metadata from Medicaid API ...")
    response = requests.get(METADATA_URL, timeout=30)
    response.raise_for_status()
    metadata = response.json()

    try:
        csv_url = metadata["distribution"][0]["data"]["downloadURL"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(
            f"Could not find downloadURL in API response. "
            f"Response structure may have changed. Error: {e}\n"
            f"Response snippet: {json.dumps(metadata, indent=2)[:500]}"
        )

    print(f"  Found CSV URL: {csv_url}")
    return csv_url


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
    # Paths are relative to repo root (where the Action runs from)
    template_path = "scripts/dashboard_template.html"
    output_path = "docs/index.html"

    csv_url = get_csv_url()
    raw_csv = download_csv(csv_url)
    data = parse_csv(raw_csv)
    build_html(data, template_path, output_path)
    print("Build complete.")


if __name__ == "__main__":
    main()
