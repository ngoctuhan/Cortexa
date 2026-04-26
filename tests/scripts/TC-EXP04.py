"""
TC-EXP04 — Experience Delete: soft-deactivate removes experience from list

Scenario:
  Creates an experience via correction conversation, verifies it appears
  in GET /v1/experiences, deletes it, then verifies it no longer appears.

Tests:
  - DELETE /v1/experiences/:id returns 200
  - After deletion, the experience no longer appears in list (is_active=false)
  - DELETE with invalid experience_id format returns 400
  - DELETE with invalid tenant_id returns 400
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_utils import APIClient, ExperienceClient, ExperienceHelpers, TestResult
import uuid
import requests as _req

TENANT_ID  = str(uuid.uuid4())
USER_ID    = str(uuid.uuid4())
SESSION_ID = str(uuid.uuid4())


def run_tests():
    results = []

    # ── Setup: send correction conversation, wait for experience ────────────
    _req.post("http://localhost:8080/v1/sessions", json={
        "tenant_id": TENANT_ID, "user_id": USER_ID, "title": "TC-EXP04"
    }, timeout=5)

    turns = ExperienceHelpers.build_correction_conversation(topic="code review", language="vi")
    ExperienceHelpers.send_conversation(TENANT_ID, USER_ID, SESSION_ID, turns)

    experience = ExperienceHelpers.wait_for_experience(TENANT_ID, USER_ID, timeout_ms=45000)

    if not experience:
        results.append(TestResult(
            test_id="TC-EXP04-00",
            name="Prerequisite: experience created",
            passed=False,
            details="No experience found after 45s",
        ))
        for r in results:
            r.print()
        sys.exit(1)

    exp_id = experience["id"]
    results.append(TestResult(
        test_id="TC-EXP04-00",
        name="Prerequisite: experience created",
        passed=True,
        details=f"id={exp_id}",
    ))

    # ── 01: Delete returns 200 ────────────────────────────────────────────────
    ok, data, _ = ExperienceClient.delete_experience(TENANT_ID, USER_ID, exp_id)
    results.append(TestResult(
        test_id="TC-EXP04-01",
        name="DELETE /v1/experiences/:id returns 200",
        passed=ok and data.get("status") == "experience deactivated",
        details=f"ok={ok} data={data}",
    ))

    # ── 02: Deleted experience no longer in list ──────────────────────────────
    list_ok, list_data, _ = ExperienceClient.list_experiences(TENANT_ID, USER_ID)
    exp_ids_after = [e["id"] for e in list_data.get("experiences", [])]
    results.append(TestResult(
        test_id="TC-EXP04-02",
        name="Deleted experience absent from GET /v1/experiences list",
        passed=list_ok and exp_id not in exp_ids_after,
        details=f"ids_remaining={exp_ids_after}",
    ))

    # ── 03: Invalid experience_id → 400 ──────────────────────────────────────
    resp = _req.delete(
        "http://localhost:8080/v1/experiences/not-a-uuid",
        params={"tenant_id": TENANT_ID, "user_id": USER_ID},
        timeout=5,
    )
    results.append(TestResult(
        test_id="TC-EXP04-03",
        name="DELETE with invalid experience_id format returns 400",
        passed=resp.status_code == 400,
        details=f"status={resp.status_code}",
    ))

    # ── 04: Invalid tenant_id → 400 ──────────────────────────────────────────
    resp2 = _req.delete(
        f"http://localhost:8080/v1/experiences/{exp_id}",
        params={"tenant_id": "bad-id", "user_id": USER_ID},
        timeout=5,
    )
    results.append(TestResult(
        test_id="TC-EXP04-04",
        name="DELETE with invalid tenant_id returns 400",
        passed=resp2.status_code == 400,
        details=f"status={resp2.status_code}",
    ))

    return results


if __name__ == "__main__":
    results = run_tests()
    failed = [r for r in results if not r.passed]
    for r in results:
        r.print()
    sys.exit(1 if failed else 0)
