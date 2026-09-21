#!/usr/bin/env python3
"""Exercises the human-approval webhook the way a person clicking Slack buttons would.

Needs: the mock server, and n8n running with the test workflow published.
    python3 approval_flow_test.py [mock-port] [n8n-port]
"""
import base64
import hashlib
import hmac
import json
import re
import sys
import urllib.error
import urllib.request

MOCK = sys.argv[1] if len(sys.argv) > 1 else "9911"
N8N = sys.argv[2] if len(sys.argv) > 2 else "5678"
SECRET = b"test-secret"
fails = []


def get(url):
    try:
        r = urllib.request.urlopen(url)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def state():
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{MOCK}/_state"))


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if not cond else ""))
    if not cond:
        fails.append(name)


def links(msg):
    el = [b for b in msg["blocks"] if b["type"] == "actions"][0]["elements"]
    return el[0]["url"], el[1]["url"]


def payload_of(url):
    p = re.search(r"p=([^&]+)", url).group(1)
    return p, json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


def b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode().rstrip("=")


msgs = state()["slack"]
assert len(msgs) >= 3, "run the pipeline first (need 3 Slack approval messages)"
(approve_a, _), (_, reject_b), (approve_c, _) = links(msgs[0]), links(msgs[1]), links(msgs[2])

# 1. approve -> exactly one calendar event, Slack confirmation, success page
code, html = get(approve_a)
check("approve link books the meeting", code == 200 and "Meeting booked" in html, (code, html[:120]))
s = state()
check("one Google Calendar event created", len(s["events"]) == 1, len(s["events"]))
ev = list(s["events"].values())[0]
_, pa = payload_of(approve_a)
check("event has the approved start/end", ev["start"]["dateTime"] == pa["s"] and ev["end"]["dateTime"] == pa["e"])
check("event carries agenda and HubSpot ID", "Agenda:" in ev["description"] and "HubSpot company ID" in ev["description"])
check("Slack confirmation sent", any("Meeting booked" in m.get("text", "") for m in s["slack"][3:]))

# 2. same link again must never double-book
code, html = get(approve_a)
s = state()
check("replaying the link does not create a second event", len(s["events"]) == 1 and "already booked" in html, (len(s["events"]), html[:120]))

# 3. reject -> nothing booked
before = len(state()["events"])
code, html = get(reject_b)
check("reject link books nothing", code == 200 and "Rejected" in html and len(state()["events"]) == before)

# 4. forged / tampered links
code, html = get(approve_c.replace("sig=", "sig=0"))
check("wrong signature rejected (403)", code == 403, code)
p, pl = payload_of(approve_c)
pl["s"] = "2030-01-01T10:00:00.000Z"
code, html = get(approve_c.replace(p, b64(pl)))
check("tampered payload rejected (403)", code == 403, code)
code, html = get(f"http://127.0.0.1:{N8N}/webhook/gtm-approval")
check("missing parameters rejected (400)", code == 400, code)
code, html = get(approve_c.replace("decision=approve", "decision=maybe"))
check("unknown decision rejected (400)", code == 400, code)

# 5. correctly signed but expired
p, pl = payload_of(approve_c)
pl["s"] = "2020-01-01T08:00:00.000Z"
p2 = b64(pl)
sig = hmac.new(SECRET, p2.encode(), hashlib.sha256).hexdigest()
code, html = get(f"http://127.0.0.1:{N8N}/webhook/gtm-approval?p={p2}&sig={sig}&decision=approve")
check("expired slot rejected (410)", code == 410, code)

# 6. approve the third lead -> second event
code, html = get(approve_c)
check("second approval books a second meeting", code == 200 and len(state()["events"]) == 2, (code, len(state()["events"])))

sys.exit(1 if fails else 0)
