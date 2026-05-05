#!/usr/bin/env python3
"""
ctx.py - Cortexa context CLI

Usage:
    python3 tests/scripts/ctx.py --tenant-id <UUID> --user-id <UUID>
    python3 tests/scripts/ctx.py ... -q "query" [--format plain|rich]

Interactive commands:
    <query>              Query /v1/context
    :say <text>          Send user message (triggers cognitive extraction)
    :assistant <text>    Send assistant message
    :wait [N]            Sleep N sec for cognitive extraction (default 8)
    :types <t,...>       Filter: entity_facts|semantic_messages|persona|events
    :types all           Reset filter
    :format plain|rich   Switch output format
    :pretty              Toggle raw JSON
    :session             Show IDs
    :newsession          New session_id
    :help                This help
    exit / quit          Exit
"""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
for _ep in ["cortexa/.env", "../cortexa/.env", ".env"]:
    if Path(_ep).exists():
        for _ln in Path(_ep).read_text().splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                k, _, v = _ln.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        break

BASE_URL = os.environ.get("CORTEXA_BASE_URL", "http://localhost:8080/v1")

import urllib.request
import urllib.error

# ── Terminal colours ──────────────────────────────────────────────────────────
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _c(t, col):
    return f"{col}{t}{RESET}"


# ── Type aliases ──────────────────────────────────────────────────────────────
TYPE_ALIASES = {
    "entity": "entity_facts",
    "facts": "entity_facts",
    "semantic": "semantic_messages",
    "messages": "semantic_messages",
    "persona": "persona",
    "events": "events",
    "exp": "experiences",
    "experiences": "experiences",
}

# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────────────────────────

def _post(path: str, payload: dict, timeout: int = 15) -> tuple:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), (time.time() - t0) * 1000
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}, (time.time() - t0) * 1000
    except Exception as e:
        return {"error": str(e)}, (time.time() - t0) * 1000


def call_context(tenant_id, user_id, session_id, query, memory_types=None):
    p = {
        "tenant_id": tenant_id, "user_id": user_id,
        "session_id": session_id, "query": query,
    }
    if memory_types:
        p["memory_types"] = memory_types
    return _post("/context", p)


def send_message(tenant_id, user_id, session_id, role, content):
    return _post("/messages", {
        "tenant_id": tenant_id, "user_id": user_id,
        "session_id": session_id, "role": role, "content": content,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Payload flattener
# ─────────────────────────────────────────────────────────────────────────────

def _payload_text(payload) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return payload.strip()
    if isinstance(payload, list):
        return "; ".join(str(x) for x in payload)
    if isinstance(payload, dict):
        ev   = (payload.get("event_name") or payload.get("title")
                or payload.get("content") or payload.get("summary"))
        date = payload.get("date") or payload.get("period") or ""
        if ev:
            return f"{ev}" + (f" ({date})" if date else "")
        return "; ".join(f"{k}: {v}" for k, v in payload.items() if v)
    return str(payload).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Plain-text renderer  (LLM-ready, no ANSI, no scores)
# ─────────────────────────────────────────────────────────────────────────────

def render_plain(ctx: dict, latency_ms: float):
    if "error" in ctx:
        print(f"[ERROR] {ctx['error']}")
        return

    lines = []

    # Identity (self-facts): always first — mirrors formatBundle in rest.go
    self_facts = ctx.get("self_facts") or []
    if self_facts:
        lines.append("## Identity")
        for f in self_facts:
            attr = f.get("attribute", "?")
            val  = f.get("value", "?")
            lines.append(f"- {attr}: {val}")

    facts = ctx.get("entity_facts") or []
    if facts:
        lines.append("\n## Entity Facts")
        for f in facts:
            name = f.get("entity_name", "?")
            attr = f.get("attribute", "?")
            val  = f.get("value", "?")
            lines.append(f"- {name}.{attr}: {val}")

    events = ctx.get("upcoming_events") or []
    if events:
        lines.append("\n## Life Events")
        for e in events:
            text = _payload_text(e.get("payload"))
            if text:
                lines.append(f"- {text}")

    persona = ctx.get("persona_context")
    if persona:
        p    = persona.get("payload") if isinstance(persona, dict) else None
        text = _payload_text(p)
        if text:
            lines.append("\n## Persona Traits")
            for trait in (text.split(";") if ";" in text else [text]):
                t = trait.strip()
                if t:
                    lines.append(f"- {t}")

    for exp in (ctx.get("experiences") or []):
        lines.append("\n## Learned Behaviors")
        lines.append(f"- {exp.get('description', '')}")
        break

    sem = ctx.get("semantic_messages") or []
    if sem:
        lines.append("\n## Relevant Past Messages")
        for m in sem[:5]:
            content = m.get("content", "")[:200]
            if content:
                lines.append(f"- {content}")

    recent = ctx.get("recent_messages") or []
    if recent:
        lines.append("\n## Recent Conversation")
        for m in recent[-6:]:
            role    = m.get("role", "?")
            content = m.get("content", "")[:200]
            lines.append(f"{role.upper()}: {content}")

    if lines:
        print("\n".join(lines))
        print(f"\n[latency: {latency_ms:.0f}ms  tokens: {ctx.get('total_tokens', 0)}]")
    else:
        print("(no context found)")
        print(f"[latency: {latency_ms:.0f}ms]")


# ─────────────────────────────────────────────────────────────────────────────
# Rich renderer  (coloured)
# ─────────────────────────────────────────────────────────────────────────────

def render_rich(ctx: dict, latency_ms: float):
    if "error" in ctx:
        print(f"\n{_c('ERROR', RED)}: {ctx['error']}")
        return

    print(f"\n{_c('-' * 60, DIM)}")
    print(f"  latency: {_c(f'{latency_ms:.0f}ms', GREEN)}  tokens: {ctx.get('total_tokens', '?')}")

    # Identity (self-facts): always first — mirrors formatBundle in rest.go
    self_facts = ctx.get("self_facts") or []
    if self_facts:
        print(f"\n{_c(chr(9656) + ' identity (self_facts)', BOLD + CYAN)} ({len(self_facts)})")
        for f in self_facts:
            conf = f.get("confidence")
            conf_str = f"  {_c(f'conf={conf:.2f}', DIM)}" if conf is not None else ""
            print(f"  {_c(f.get('attribute', '?'), YELLOW)} = "
                  f"{_c(str(f.get('value', '?'))[:80], GREEN)}"
                  f"{conf_str}")

    facts = ctx.get("entity_facts") or []
    if facts:
        print(f"\n{_c(chr(9656) + ' entity_facts', BOLD + CYAN)} ({len(facts)})")
        for f in facts:
            conf = f.get("confidence")
            conf_str = f"  {_c(f'conf={conf:.2f}', DIM)}" if conf is not None else ""
            print(f"  {_c(f.get('entity_name', '?'), YELLOW)}"
                  f".{f.get('attribute', '?')} = "
                  f"{_c(str(f.get('value', '?'))[:80], GREEN)}"
                  f"{conf_str}")

    sem = ctx.get("semantic_messages") or []
    if sem:
        print(f"\n{_c(chr(9656) + ' semantic_messages', BOLD + CYAN)} ({len(sem)})")
        for m in sem[:5]:
            score = m.get("cosine_sim") or m.get("score")
            score_str = f"  {_c(f'score={score:.3f}', DIM)}" if score is not None else ""
            print(f"  {str(m.get('content', ''))[:160]}{score_str}")

    persona = ctx.get("persona_context")
    if persona:
        imp = persona.get("importance") if isinstance(persona, dict) else None
        imp_str = f"  {_c(f'imp={imp:.2f}', DIM)}" if imp is not None else ""
        p    = persona.get("payload") if isinstance(persona, dict) else None
        text = _payload_text(p)
        print(f"\n{_c(chr(9656) + ' persona_context', BOLD + CYAN)} (1)")
        print(f"  {_c('persona', YELLOW)}{imp_str}")
        print(f"       {text[:200]}")

    events = ctx.get("upcoming_events") or []
    if events:
        print(f"\n{_c(chr(9656) + ' upcoming_events', BOLD + CYAN)} ({len(events)})")
        for e in events:
            p       = e.get("payload") or {}
            name    = p.get("event_name") or p.get("title") or _payload_text(p)
            date    = p.get("date") or p.get("period") or ""
            imp     = e.get("importance")
            imp_str = f"  {_c(f'imp={imp:.2f}', DIM)}" if imp is not None else ""
            date_str = f"  {_c(date, DIM)}" if date else ""
            print(f"  {_c(chr(8226), YELLOW)} {name}{date_str}{imp_str}")

    recent = ctx.get("recent_messages") or []
    if recent:
        print(f"\n{_c(chr(9656) + ' recent_messages', DIM)} ({len(recent)})")
        for m in recent[-4:]:
            role    = m.get("role", "?")
            content = m.get("content", "")[:120]
            print(f"  {_c(role, YELLOW)}: {content}")

    nothing = not self_facts and not facts and not sem and not persona and not events and not recent
    if nothing:
        print(f"  {_c('(no results)', DIM)}")


def render(ctx, latency_ms, fmt="rich", pretty=False):
    if pretty:
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
        return
    if fmt == "plain":
        render_plain(ctx, latency_ms)
    else:
        render_rich(ctx, latency_ms)


# ─────────────────────────────────────────────────────────────────────────────
# Interactive loop
# ─────────────────────────────────────────────────────────────────────────────

HELP_TEXT = """
Commands:
  <query>              Query /v1/context and show results
  :say <text>          Send user message (triggers cognitive extraction)
  :assistant <text>    Send assistant message
  :wait [N]            Sleep N sec for cognitive extraction (default 8)
  :types <t,...>       Filter: entity_facts | semantic_messages | persona | events
  :types all           Reset filter
  :format plain|rich   Switch output format
  :pretty              Toggle raw JSON dump
  :session             Show tenant/user/session IDs
  :newsession          Generate new session_id
  :help                This help
  exit / quit          Exit
"""


def interactive_loop(tenant_id: str, user_id: str, session_id: str, fmt: str = "rich"):
    memory_types = None
    pretty = False

    print(f"\n{_c('Cortexa Context CLI', BOLD)}")
    print(f"  tenant  : {_c(tenant_id, YELLOW)}")
    print(f"  user    : {_c(user_id, YELLOW)}")
    print(f"  session : {_c(session_id, YELLOW)}")
    print(f"  format  : {_c(fmt, DIM)}")
    print(f"  endpoint: {_c(BASE_URL, DIM)}")
    print(f"\n':help' for commands. ':say <msg>' to send a message.\n")

    while True:
        try:
            types_hint = f"[{','.join(memory_types)}] " if memory_types else ""
            prompt = f"{_c('ctx', BOLD + CYAN)}{_c(types_hint, DIM)} > "
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            print("Bye!")
            break
        if line == ":help":
            print(HELP_TEXT)
            continue
        if line == ":pretty":
            pretty = not pretty
            print(f"  pretty JSON = {pretty}")
            continue
        if line == ":session":
            print(f"  tenant  = {tenant_id}")
            print(f"  user    = {user_id}")
            print(f"  session = {session_id}")
            continue
        if line == ":newsession":
            session_id = str(uuid.uuid4())
            print(f"  new session_id = {session_id}")
            continue
        if line.startswith(":format"):
            parts = line.split()
            fmt = parts[1] if len(parts) > 1 else "rich"
            print(f"  format = {fmt}")
            continue
        if line.startswith(":types"):
            arg = line[6:].strip()
            if not arg or arg == "all":
                memory_types = None
                print("  memory_types = all")
            else:
                memory_types = [
                    TYPE_ALIASES.get(p.strip(), p.strip())
                    for p in arg.replace(",", " ").split()
                ]
                print(f"  memory_types = {memory_types}")
            continue
        if line.startswith(":wait"):
            parts = line.split()
            n = int(parts[1]) if len(parts) > 1 else 8
            print(f"  waiting {n}s...", end="", flush=True)
            for _ in range(n):
                time.sleep(1)
                print(".", end="", flush=True)
            print(" done")
            continue
        if line.startswith(":say "):
            content = line[5:].strip()
            resp, lat = send_message(tenant_id, user_id, session_id, "user", content)
            if "error" in resp:
                print(f"  {_c('ERROR', RED)}: {resp['error']}")
            else:
                print(f"  {_c('sent (user)', GREEN)} {lat:.0f}ms")
            continue
        if line.startswith(":assistant "):
            content = line[11:].strip()
            resp, lat = send_message(tenant_id, user_id, session_id, "assistant", content)
            if "error" in resp:
                print(f"  {_c('ERROR', RED)}: {resp['error']}")
            else:
                print(f"  {_c('sent (assistant)', GREEN)} {lat:.0f}ms")
            continue

        # Default: query context
        ctx, latency = call_context(tenant_id, user_id, session_id, line, memory_types)
        render(ctx, latency, fmt, pretty)
        print()


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Cortexa context CLI")
    ap.add_argument("--tenant-id", default=os.environ.get("CORTEXA_TENANT"))
    ap.add_argument("--user-id",   default=os.environ.get("CORTEXA_USER"))
    ap.add_argument("--session-id", default=str(uuid.uuid4()))
    ap.add_argument("-q", "--query", default=None)
    ap.add_argument("--types", default=None,
                    help="Comma-separated memory types, e.g. entity_facts,events")
    ap.add_argument("--format", default="rich", choices=["plain", "rich"],
                    dest="output_format",
                    help="Output: plain (LLM-ready) or rich (coloured)")
    ap.add_argument("--pretty", action="store_true", help="Raw JSON output")
    args = ap.parse_args()

    if not args.tenant_id or not args.user_id:
        ap.error("--tenant-id and --user-id are required")

    mt = None
    if args.types:
        mt = [TYPE_ALIASES.get(t.strip(), t.strip()) for t in args.types.split(",")]

    if args.query:
        ctx, lat = call_context(
            args.tenant_id, args.user_id, args.session_id, args.query, mt
        )
        render(ctx, lat, args.output_format, args.pretty)
        print()
    else:
        interactive_loop(
            args.tenant_id, args.user_id, args.session_id, args.output_format
        )


if __name__ == "__main__":
    main()
