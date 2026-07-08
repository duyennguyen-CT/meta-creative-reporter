"""
Meta Ads — Creative Performance Reporter.

Pulls ad/creative-level performance for a list of ad accounts and writes
docs/data/latest.json, which docs/index.html renders as a dashboard.

Run modes:
  - With env var META_ACCESS_TOKEN set -> pulls live data from the Graph API.
  - Without it                        -> keeps the existing seed JSON untouched,
                                         so the dashboard still works offline.

Local:   python build_report.py
CI:       runs inside .github/workflows/weekly.yml on a schedule.
"""

import os
import json
import time
import datetime
import pathlib

# --- CONFIG ---------------------------------------------------------------

META_GRAPH_URL = "https://graph.facebook.com/v21.0"

# label -> ad account id (numeric, without the "act_" prefix)
ACCOUNTS = {
    "Chotot_growth_sgd":  "217167486615130",
    "Chotot_gds_elt_sgd": "655717678725444",
    "Chotot_job_sgd":     "1009648153146994",
    "Chotot_pty_sgd":     "189567943020118",
    "Chotot_veh_sgd":     "211751247179666",
}

# Which group each account belongs to (used only for labelling in the UI).
GROUPS = {
    "Chotot_growth_sgd":  "GROWTH",
    "Chotot_gds_elt_sgd": "GROWTH",
    "Chotot_job_sgd":     "GROWTH",
    "Chotot_pty_sgd":     "VERTICAL",
    "Chotot_veh_sgd":     "VERTICAL",
}

DATE_PRESET = "last_30d"
FIELDS = "ad_id,ad_name,spend,impressions,reach,clicks,ctr,cpc,cpm,frequency,actions"
TOP_N = 25  # creatives per account, sorted by spend

# action_type values counted as an app install (varies by campaign setup)
INSTALL_ACTIONS = ("mobile_app_install", "omni_app_install", "app_install")

TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
OUT_PATH = pathlib.Path(__file__).parent / "docs" / "data" / "latest.json"

# --- META API -------------------------------------------------------------


def _get(url, params, retries=3):
    import requests  # imported lazily so offline/seed mode needs no install
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            data = r.json()
            if "error" in data:
                # 4/17/32/613 = rate limits -> back off and retry
                if data["error"].get("code") in (4, 17, 32, 613) and attempt < retries - 1:
                    time.sleep(2 ** attempt * 5)
                    continue
                print(f"Meta API error: {data['error']}")
                return {}
            return data
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5)
            else:
                print(f"Request failed: {e}")
    return {}


def fetch_creatives(account_id):
    """Return a list of ad/creative rows for one account, sorted by spend."""
    url = f"{META_GRAPH_URL}/act_{account_id}/insights"
    params = {
        "level": "ad",
        "fields": FIELDS,
        "date_preset": DATE_PRESET,
        "filtering": json.dumps([{"field": "spend", "operator": "GREATER_THAN", "value": "0"}]),
        "sort": "spend_descending",
        "limit": TOP_N,
        "access_token": TOKEN,
    }
    data = _get(url, params)
    rows = []
    for row in data.get("data", []):
        reach = int(float(row.get("reach", 0) or 0))
        impr = int(float(row.get("impressions", 0) or 0))
        spend = round(float(row.get("spend", 0) or 0), 2)
        freq = float(row.get("frequency") or (impr / reach if reach else 0))
        installs = sum(
            int(float(a.get("value", 0) or 0))
            for a in (row.get("actions") or [])
            if a.get("action_type") in INSTALL_ACTIONS
        )
        rows.append({
            "id":          row.get("ad_id", ""),
            "name":        row.get("ad_name", ""),
            "spend":       spend,
            "impressions": impr,
            "reach":       reach,
            "clicks":      int(float(row.get("clicks", 0) or 0)),
            "ctr":         round(float(row.get("ctr", 0) or 0), 2),
            "cpc":         round(float(row.get("cpc", 0) or 0), 2),
            "cpm":         round(float(row.get("cpm", 0) or 0), 2),
            "frequency":   round(freq, 2),
            "installs":    installs,
            "cpi":         round(spend / installs, 2) if installs else 0,
        })
    return rows


def build_from_api():
    accounts = []
    for label, acc_id in ACCOUNTS.items():
        print(f"Pulling {label} ({acc_id}) ...")
        creatives = fetch_creatives(acc_id)
        print(f"  -> {len(creatives)} creatives")
        accounts.append({
            "id": acc_id,
            "label": label,
            "group": GROUPS.get(label, ""),
            "creatives": creatives,
        })

    today = datetime.date.today()
    start = today - datetime.timedelta(days=30)
    return {
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period_label": f"{start:%-d %b} – {today:%-d %b %Y} (last 30 days)",
        "date_start": start.isoformat(),
        "date_stop": today.isoformat(),
        "currency": "SGD",
        "accounts": accounts,
    }


def main():
    if not TOKEN:
        print("META_ACCESS_TOKEN not set — keeping existing seed data at")
        print(f"  {OUT_PATH}")
        print("Set the token to pull live data:  export META_ACCESS_TOKEN=...")
        return

    report = build_from_api()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    total = sum(c["spend"] for a in report["accounts"] for c in a["creatives"])
    print(f"Wrote {OUT_PATH} — total spend SGD {total:,.2f}")


if __name__ == "__main__":
    main()
