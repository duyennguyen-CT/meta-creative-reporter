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

# Time ranges pre-built into the dashboard (dropdown). key = Meta date_preset.
PRESETS = [
    ("yesterday",  "Yesterday"),
    ("last_7d",    "Last 7 days"),
    ("last_30d",   "Last 30 days"),
    ("this_month", "This month"),
    ("last_month", "Last month"),
]
DEFAULT_RANGE = "last_30d"

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


def fetch_creatives(account_id, date_preset):
    """Return a list of ad/creative rows for one account + time range, by spend."""
    url = f"{META_GRAPH_URL}/act_{account_id}/insights"
    params = {
        "level": "ad",
        "fields": FIELDS,
        "date_preset": date_preset,
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


def classify_format(creative):
    """Map a creative object to a coarse format bucket used by the dashboard."""
    if not creative:
        return "Other"
    oss = creative.get("object_story_spec") or {}
    link = oss.get("link_data") or {}
    if creative.get("video_id") or creative.get("object_type") == "VIDEO" or oss.get("video_data"):
        return "Video"
    # carousel cards live under object_story_spec.link_data.child_attachments
    if link.get("child_attachments"):
        return "Carousel"
    if creative.get("image_hash") or creative.get("object_type") == "PHOTO" or link.get("image_hash"):
        return "Image"
    # object_story_spec/asset_feed-based dynamic/catalog ads report as SHARE, no asset
    if creative.get("object_type") == "SHARE":
        return "Dynamic"
    # STATUS and other rare object types → keep the buckets clean
    return "Other"


def fetch_formats(ad_ids):
    """Return {ad_id: format} by batch-reading each ad's creative object."""
    out = {}
    ids = list(ad_ids)
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        params = {
            "ids": ",".join(batch),
            "fields": "creative{object_type,video_id,image_hash,object_story_spec}",
            "access_token": TOKEN,
        }
        data = _get(META_GRAPH_URL, params)
        for ad_id, node in (data or {}).items():
            if isinstance(node, dict):
                out[ad_id] = classify_format(node.get("creative") or {})
    return out


def period_label(preset):
    """Human date range that approximates Meta's definition of the preset."""
    t = datetime.date.today()
    y = t - datetime.timedelta(days=1)
    if preset == "yesterday":
        s = e = y
    elif preset == "last_7d":
        e, s = y, t - datetime.timedelta(days=7)
    elif preset == "last_30d":
        e, s = y, t - datetime.timedelta(days=30)
    elif preset == "this_month":
        s, e = t.replace(day=1), t
    elif preset == "last_month":
        e = t.replace(day=1) - datetime.timedelta(days=1)
        s = e.replace(day=1)
    else:
        s = e = t
    return f"{s:%-d %b} – {e:%-d %b %Y}"


def build_from_api():
    ranges = {}
    ad_ids = set()
    for preset, label in PRESETS:
        accounts = []
        for acc_label, acc_id in ACCOUNTS.items():
            print(f"Pulling [{preset}] {acc_label} ({acc_id}) ...")
            creatives = fetch_creatives(acc_id, preset)
            print(f"  -> {len(creatives)} creatives")
            for c in creatives:
                if c["id"]:
                    ad_ids.add(c["id"])
            accounts.append({
                "id": acc_id,
                "label": acc_label,
                "group": GROUPS.get(acc_label, ""),
                "creatives": creatives,
            })
        ranges[preset] = {
            "label": label,
            "period_label": period_label(preset),
            "accounts": accounts,
        }

    # Creative format is an attribute of the ad, not of a time range — fetch once.
    print(f"Resolving creative formats for {len(ad_ids)} ads ...")
    fmt_map = fetch_formats(ad_ids)
    for rng in ranges.values():
        for acc in rng["accounts"]:
            for c in acc["creatives"]:
                c["format"] = fmt_map.get(c["id"], "Other")

    return {
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": "SGD",
        "default_range": DEFAULT_RANGE,
        "ranges": ranges,
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
    dflt = report["ranges"].get(DEFAULT_RANGE) or next(iter(report["ranges"].values()))
    total = sum(c["spend"] for a in dflt["accounts"] for c in a["creatives"])
    print(f"Wrote {OUT_PATH} — {len(report['ranges'])} ranges, "
          f"{DEFAULT_RANGE} total spend SGD {total:,.2f}")


if __name__ == "__main__":
    main()
