"""
TC-EXP02 — Experience Auto-Detection: ExperienceWorker learns from correction conversation

Scenario:
  User sends a conversation where they correct the AI and give explicit instructions
  for a future task type ("lần sau ... nhớ là ...").
  After the batch triggers, ExperienceWorker should detect the learning signal
  and create an experience record for the user.

Tests:
  - After a correction conversation, at least one experience is created
  - The created experience has a non-empty description and steps
  - The experience appears in GET /v1/experiences for the user
  - A different user's experiences list remains empty (isolation)

Note: ExperienceWorker fires async after Redis Stream batch. This test polls
      up to 45 s to account for LLM extraction latency.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_utils import APIClient, ExperienceClient, ExperienceHelpers, TestResult, TestHelpers
import uuid

TENANT_ID       = str(uuid.uuid4())
USER_ID         = str(uuid.uuid4())
SESSION_ID      = str(uuid.uuid4())
OTHER_USER_ID   = str(uuid.uuid4())


def run_tests():
    results = []

    # ── Setup: create session and send correction conversation ───────────────
    session_resp = APIClient.append_message.__func__ if False else None  # just for IDE
    # Create session first
    import requests as _req
    sess = _req.post("http://localhost:8080/v1/sessions", json={
        "tenant_id": TENANT_ID,
        "user_id": USER_ID,
        "title": "TC-EXP02 test session",
    }, timeout=5)
    session_ok = sess.status_code == 201

    # Send a realistic Vietnamese correction conversation
    turns = ExperienceHelpers.build_correction_conversation(topic="SQL", language="vi")
    sent_ok = ExperienceHelpers.send_conversation(TENANT_ID, USER_ID, SESSION_ID, turns)

    results.append(TestResult(
        test_id="TC-EXP02-01",
        name="Session created and correction conversation sent successfully",
        passed=session_ok and sent_ok,
        details=f"session_status={sess.status_code} sent={sent_ok}",
    ))

    if not sent_ok:
        # Cannot continue if messages didn't send
        for r in results:
            r.print()
        sys.exit(1)

    # ── 02: Wait for ExperienceWorker to detect and create experience ─────────
    experience = ExperienceHelpers.wait_for_experience(
        TENANT_ID, USER_ID, timeout_ms=180000, poll_interval_ms=500,
    )
    results.append(TestResult(
        test_id="TC-EXP02-02",
        name="ExperienceWorker creates experience after correction conversation",
        passed=experience is not None,
        details=f"experience={'found' if experience else 'NOT FOUND (timeout 180s)'}",
    ))

    # ── 03: Experience has required fields ───────────────────────────────────
    if experience:
        has_desc = bool(experience.get("description", "").strip())
        has_steps = isinstance(experience.get("steps"), list) and len(experience["steps"]) > 0
        has_confidence = 0 < experience.get("confidence", 0) <= 1.0
        results.append(TestResult(
            test_id="TC-EXP02-03",
            name="Experience has description, steps, and valid confidence",
            passed=has_desc and has_steps and has_confidence,
            details=f"description={experience.get('description', '')[:80]!r} steps={len(experience.get('steps', []))} confidence={experience.get('confidence')}",
        ))
    else:
        results.append(TestResult(
            test_id="TC-EXP02-03",
            name="Experience has description, steps, and valid confidence",
            passed=False,
            details="skipped — no experience found in TC-EXP02-02",
        ))

    # ── 04: Other user has no experiences (isolation) ─────────────────────────
    ok, data, _ = ExperienceClient.list_experiences(TENANT_ID, OTHER_USER_ID)
    other_empty = ok and len(data.get("experiences", [])) == 0
    results.append(TestResult(
        test_id="TC-EXP02-04",
        name="Another user's experiences list is empty (user-scope isolation)",
        passed=other_empty,
        details=f"other_experiences={data.get('experiences')}",
    ))

    return results


if __name__ == "__main__":
    results = run_tests()
    failed = [r for r in results if not r.passed]
    for r in results:
        r.print()
    sys.exit(1 if failed else 0)
