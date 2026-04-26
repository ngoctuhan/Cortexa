"""
TC-EXP01 — Experience API: List endpoint returns empty list for new user

Tests:
  - GET /v1/experiences returns 200 with empty list for brand-new user
  - GET /v1/experiences returns 400 for invalid tenant_id
  - GET /v1/experiences returns 400 for invalid user_id
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_utils import APIClient, ExperienceClient, TestResult, TestHelpers
import uuid

TENANT_ID = str(uuid.uuid4())
USER_ID   = str(uuid.uuid4())


def run_tests():
    results = []

    # ── 01: Empty list for new user ──────────────────────────────────────────
    ok, data, dur = ExperienceClient.list_experiences(TENANT_ID, USER_ID)
    results.append(TestResult(
        test_id="TC-EXP01-01",
        name="GET /v1/experiences returns 200 with empty list for new user",
        passed=ok and isinstance(data.get("experiences"), list) and len(data["experiences"]) == 0,
        details=f"status_ok={ok} experiences={data.get('experiences')} dur={dur:.0f}ms",
        duration_ms=dur,
    ))

    # ── 02: Invalid tenant_id → 400 ──────────────────────────────────────────
    import requests as _req
    resp = _req.get("http://localhost:8080/v1/experiences",
                    params={"tenant_id": "not-a-uuid", "user_id": USER_ID}, timeout=5)
    results.append(TestResult(
        test_id="TC-EXP01-02",
        name="GET /v1/experiences returns 400 for invalid tenant_id",
        passed=resp.status_code == 400,
        details=f"status={resp.status_code}",
    ))

    # ── 03: Invalid user_id → 400 ────────────────────────────────────────────
    resp = _req.get("http://localhost:8080/v1/experiences",
                    params={"tenant_id": TENANT_ID, "user_id": "bad"}, timeout=5)
    results.append(TestResult(
        test_id="TC-EXP01-03",
        name="GET /v1/experiences returns 400 for invalid user_id",
        passed=resp.status_code == 400,
        details=f"status={resp.status_code}",
    ))

    return results


if __name__ == "__main__":
    results = run_tests()
    failed = [r for r in results if not r.passed]
    for r in results:
        r.print()
    sys.exit(1 if failed else 0)
