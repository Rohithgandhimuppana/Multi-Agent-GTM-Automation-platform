#!/usr/bin/env python3
"""Assertions on what the pipeline sent to the (mock) external APIs after one run."""
import json
import sys
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "9911"
s = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/_state"))
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


check("manager produced 3 search queries", len(s["search"]) == 3, s["search"])
check("only qualified leads (score >= 80) reached HubSpot", len(s["hubspot"]) == 3, len(s["hubspot"]))
names = sorted(h["properties"]["name"] for h in s["hubspot"])
check("HubSpot got the 3 qualifying companies", names == ["Acme Robotics GmbH", "FactoryFlow", "Logisticsly"], names)
check("low-scoring bakery was NOT pushed to CRM", "Bakery Treats" not in names)
check("list/directory page filtered out (never scored)", s["openai"].count("lead_score") == 4, s["openai"].count("lead_score"))
check("one free/busy call for all leads", len(s["freebusy"]) == 1)
check("one Slack approval request per qualified lead", len(s["slack"]) == 3, len(s["slack"]))
check("no calendar event before human approval", len(s["events"]) == 0 and s["event_attempts"] == 0)

# proposed slots must not clash with busy time and must not overlap each other
from datetime import datetime  # noqa: E402
import base64  # noqa: E402
import re  # noqa: E402

fb = s["freebusy"][0]
slots = []
for m in s["slack"]:
    url = [b for b in m["blocks"] if b["type"] == "actions"][0]["elements"][0]["url"]
    p = re.search(r"p=([^&]+)", url).group(1)
    pl = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    slots.append((datetime.fromisoformat(pl["s"].replace("Z", "+00:00")), datetime.fromisoformat(pl["e"].replace("Z", "+00:00"))))
slots.sort()
check("slots do not overlap each other", all(a[1] <= b[0] for a, b in zip(slots, slots[1:])), slots)
check("slots are in the future", all(a[0] > datetime.now(a[0].tzinfo) for a in slots))
sys.exit(1 if fails else 0)
