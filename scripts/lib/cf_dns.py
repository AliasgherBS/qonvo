"""JSON handling for scripts/dns-email.sh.

This lives in its own file rather than inline `python3 -c` because the audit
below needs both quote styles, and shell quoting mangles them: a `\\"` inside a
single-quoted shell string reaches Python literally and is a syntax error.
"""

from __future__ import annotations

import json
import sys
from collections import Counter

GREEN, RED, BOLD, OFF = "\033[32m", "\033[31m", "\033[1m", "\033[0m"


def _payload() -> dict:
    """Cloudflare's envelope, or exit non-zero having printed its errors."""
    data = json.load(sys.stdin)
    if not data.get("success"):
        for err in data.get("errors", []):
            print(f"  cloudflare {err.get('code')}: {err.get('message')}", file=sys.stderr)
        if not data.get("errors"):
            print("  cloudflare: request failed with no error detail", file=sys.stderr)
        sys.exit(1)
    return data


def cmd_zone_id() -> None:
    result = _payload().get("result") or []
    if not result:
        print(f"zone not found -- is the token scoped to it?", file=sys.stderr)
        sys.exit(1)
    print(result[0]["id"])


def cmd_result() -> None:
    print(json.dumps(_payload().get("result")))


def cmd_match_id(raw: str, rtype: str, content: str) -> None:
    """The id of the record this write should replace, or nothing.

    MX is a set -- one name legitimately holds several, so a match must agree
    on the host too. The TXT records here are single-valued per name, so an
    existing one is updated rather than joined by a second.
    """
    for record in json.loads(raw) or []:
        if rtype == "MX":
            if record.get("content") == content:
                print(record["id"])
                return
        else:
            print(record["id"])
            return


def cmd_body(rtype: str, name: str, content: str, priority: str) -> None:
    body: dict[str, object] = {"type": rtype, "name": name, "content": content, "ttl": 1}
    if priority:
        body["priority"] = int(priority)
    print(json.dumps(body))


def cmd_audit() -> None:
    records = _payload().get("result") or []
    mail = [r for r in records if r["type"] in ("MX", "TXT")]

    print(f"\n{BOLD}Mail records{OFF}")
    if not mail:
        print("  (none yet)")
    for record in sorted(mail, key=lambda r: (r["type"], r["name"])):
        prio = f" prio={record['priority']}" if record.get("priority") is not None else ""
        content = record["content"]
        shown = content[:70] + ("..." if len(content) > 70 else "")
        print(f"  {record['type']:<4} {record['name']:<32}{prio} {shown}")

    site = [r for r in records if r["type"] in ("A", "AAAA", "CNAME")]
    print(f"\n{BOLD}Site records (this script never writes these){OFF}")
    for record in sorted(site, key=lambda r: r["name"]):
        print(f"  {record['type']:<6} {record['name']:<32} -> {record['content'][:50]}")

    problems = []

    spf = [r for r in mail if r["type"] == "TXT" and r["content"].startswith("v=spf1")]
    for name, count in Counter(r["name"] for r in spf).items():
        if count > 1:
            problems.append(f"{count} SPF records on {name}. Illegal, and it fails closed. Merge into one.")

    mx = [r for r in mail if r["type"] == "MX"]
    providers = {".".join(r["content"].rsplit(".", 2)[-2:]) for r in mx if "." in r["content"]}
    if len(providers) > 1:
        problems.append(f"MX points at more than one provider ({sorted(providers)}). Mail will be lost.")
    for record in mx:
        if record.get("proxied"):
            problems.append(f"MX {record['name']} is proxied. Mail records must be grey cloud.")

    print()
    if problems:
        print(f"{RED}Problems{OFF}")
        for problem in problems:
            print(f"  ✗ {problem}")
    else:
        print(f"{GREEN}No contradictions in what exists so far.{OFF}")


def cmd_routing() -> None:
    data = json.load(sys.stdin)
    if not data.get("success"):
        print("  (cannot read: the token has no Email Routing scope. Check by hand.)")
        return
    enabled = (data.get("result") or {}).get("enabled")
    print(f"  enabled: {enabled}")
    if enabled:
        print(f"  {RED}✗ Turn this off before pointing MX at Zoho.{OFF}")
        print("    MX points at exactly one provider. Two holders silently lose mail.")


COMMANDS = {
    "zone-id": cmd_zone_id,
    "result": cmd_result,
    "match-id": cmd_match_id,
    "body": cmd_body,
    "audit": cmd_audit,
    "routing": cmd_routing,
}

if __name__ == "__main__":
    name, *rest = sys.argv[1:]
    COMMANDS[name](*rest)
