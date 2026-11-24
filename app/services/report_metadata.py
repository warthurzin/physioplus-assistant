"""Report descriptions are data, never credentials or executable proposals."""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal


def financial_snapshot(summary: dict) -> str:
    rows = []
    for group in ("paid_sessions", "pending_sessions"):
        for item in summary.get(group, []):
            rows.append(
                {
                    "id": str(item.get("id", "")),
                    "date": str(item.get("date", "")),
                    "start": str(item.get("start_time", "")),
                    "status": item.get("payment_status"),
                    "value": str(
                        Decimal(str(item["session_value"])).quantize(Decimal("0.01"))
                    ),
                    "patient": (item.get("patient") or {}).get("full_name"),
                }
            )
    payload = {
        "received": str(
            Decimal(str(summary["total_received"])).quantize(Decimal("0.01"))
        ),
        "pending": str(
            Decimal(str(summary["total_pending"])).quantize(Decimal("0.01"))
        ),
        "rows": sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def financial_report_metadata(summary: dict, month: int, year: int) -> dict:
    return {
        "type": "financial",
        "month": month,
        "year": year,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_hash": financial_snapshot(summary),
    }
