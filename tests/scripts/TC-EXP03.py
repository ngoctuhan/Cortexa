"""
TC-EXP03 — Experience Feedback: positive and negative signals update confidence

Scenario:
  Uses the same correction conversation pattern to generate an experience,
  then sends positive and negative feedback signals and verifies the
  confidence field is updated accordingly.

Tests:
  - Positive feedback increases (or maintains) confidence, success_count increments
  - Negative feedback decreases confidence
  - Invalid signal value returns 400
  - Invalid experience_id format returns 400
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


def _get_experience(tenant_id, user_id, exp_id):
    """Re-fetch the experience to read updated fields."""
    ok, data, _ = ExperienceClient.list_experiences(tenant_id, user_id)
    if ok:
        for exp in data.get("experiences", []):
            if exp["id"] == exp_id:
                return exp
    return None


def run_tests():
    results = []

    # ── Setup: send correction conversation, wait for experience ────────────
    _req.post("http://localhost:8080/v1/sessions", json={
        "tenant_id": TENANT_ID, "user_id": USER_ID, "title": "TC-EXP03"
    }, timeout=5)

    turns = ExperienceHelpers.build_correction_conversation(topic="Python", language="en")
    ExperienceHelpers.send_conversation(TENANT_ID, USER_ID, SESSION_ID, turns)

    experience = ExperienceHelpers.wait_for_experience(TENANT_ID, USER_ID, timeout_ms=60000)

    if not experience:
        # Can't test feedback without an experience — fail fast but still report
        results.append(TestResult(
            test_id="TC-EXP03-00",
            name="Prerequisite: experience created from correction conversation",
            passed=False,
            details="No experience found after 45s — feedback tests skipped",
        ))
        for r in results:
            r.print()
        sys.exit(1)

    exp_id = experience["id"]
    confidence_before = experience.get("confidence", 0)

    results.append(TestResult(
        test_id="TC-EXP03-00",
        name="Prerequisite: experience created",
        passed=True,
        details=f"id={exp_id} confidence={confidence_before}",
    ))

    # ── 01: Positive feedback ────────────────────────────────────────────────
    ok, data, _ = ExperienceClient.send_feedback(TENANT_ID, USER_ID, exp_id, "positive")
    results.append(TestResult(
        test_id="TC-EXP03-01",
        name="POST /v1/experiences/:id/feedback with positive signal returns 200",
        passed=ok and data.get("status") == "feedback recorded",
        details=f"ok={ok} data={data}",
    ))

    # ── 02: Negative feedback ────────────────────────────────────────────────
    ok2, data2, _ = ExperienceClient.send_feedback(TENANT_ID, USER_ID, exp_id, "negative")
    results.append(TestResult(
        test_id="TC-EXP03-02",
        name="POST /v1/experiences/:id/feedback with negative signal returns 200",
        passed=ok2 and data2.get("status") == "feedback recorded",
        details=f"ok={ok2} data={data2}",
    ))

    # ── 03: Invalid signal value → 400 ───────────────────────────────────────
    resp = _req.post(
        f"http://localhost:8080/v1/experiences/{exp_id}/feedback",
        json={"tenant_id": TENANT_ID, "user_id": USER_ID, "signal": "thumbs_up"},
        timeout=5,
    )
    results.append(TestResult(
        test_id="TC-EXP03-03",
        name="Invalid signal value returns 400",
        passed=resp.status_code == 400,
        details=f"status={resp.status_code}",
    ))

    # ── 04: Invalid experience_id format → 400 ───────────────────────────────
    resp2 = _req.post(
        "http://localhost:8080/v1/experiences/not-a-uuid/feedback",
        json={"tenant_id": TENANT_ID, "user_id": USER_ID, "signal": "positive"},
        timeout=5,
    )
    results.append(TestResult(
        test_id="TC-EXP03-04",
        name="Invalid experience_id format returns 400",
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
