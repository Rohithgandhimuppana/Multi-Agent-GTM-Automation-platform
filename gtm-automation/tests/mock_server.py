#!/usr/bin/env python3
"""Mock of every external API the GTM workflow calls (OpenAI, Firecrawl, HubSpot,
Google Calendar, Slack). Lets you run the whole workflow offline, with no API keys.

    python3 mock_server.py [port]      # default 9911

GET /_state returns everything the workflow sent, so tests can assert on it.
"""
import json
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9911
LOCK = threading.Lock()
STATE = {"openai": [], "search": [], "hubspot": [], "freebusy": [], "events": {}, "event_attempts": 0, "slack": []}

PAGES = {
    "acme-robotics.de": "Acme Robotics GmbH builds warehouse automation software for logistics customers in Munich. "
                        "We are a 60 person B2B SaaS team, hiring backend engineers, and just launched our fleet API. ",
    "logisticsly.io": "Logisticsly is a Berlin based B2B platform giving mid-size manufacturers real-time shipment visibility. "
                      "Around 45 employees. Our REST API integrates with SAP. We raised a seed round last quarter. ",
    "factoryflow.com": "FactoryFlow makes MES software for industrial manufacturers in Stuttgart, 120 employees, B2B SaaS. "
                       "Contact sales@factoryflow.com. Now hiring in Germany and expanding to Austria. ",
    "bakery-treats.com": "Bakery Treats sells cakes and cookies to consumers through its online shop in Hamburg. "
                         "Family owned, 8 employees, B2C only. Order today for next day delivery across Germany. ",
    "listicle-top10.com": "Top 10 logistics software vendors in 2026 - a ranked list of companies, reviews and comparisons. "
                          "Read our guide to choosing software vendors for your business and industry today. ",
    "tiny.io": "Hi",
    "medium.com": "Blog post about logistics software " * 20,
}
SCORES = {"Acme Robotics GmbH": 93, "Logisticsly": 88, "FactoryFlow": 82, "Bakery Treats": 21}


def completion(obj):
    return {"id": "chatcmpl-mock", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(obj)}, "finish_reason": "stop"}]}


def handle_openai(body):
    schema_name = body["response_format"]["json_schema"]["name"]
    user = body["messages"][-1]["content"]
    STATE["openai"].append(schema_name)
    if schema_name == "gtm_plan":
        return completion({"queries": ["B2B logistics software Germany", "industrial SaaS manufacturers Germany",
                                       "warehouse automation platform Munich"],
                           "criteria_summary": "Engineering-led German B2B SaaS selling to industry."})
    if schema_name == "company_profile":
        url = re.search(r"Page URL: (\S+)", user).group(1)
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        names = {"acme-robotics.de": "Acme Robotics GmbH", "logisticsly.io": "Logisticsly", "factoryflow.com": "FactoryFlow",
                 "bakery-treats.com": "Bakery Treats", "listicle-top10.com": "Top 10 Vendors"}
        is_co = host != "listicle-top10.com"
        email = "sales@factoryflow.com" if host == "factoryflow.com" else None
        return completion({
            "is_company_website": is_co, "company_name": names.get(host, host), "description": PAGES.get(host, "")[:140],
            "industry": "Bakery" if "bakery" in host else "Logistics software", "location_city": "Munich",
            "location_country": "Germany", "employee_range": "50-200", "business_model": "B2C" if "bakery" in host else "B2B",
            "products": ["Platform"], "technologies": ["REST API"], "buying_signals": ["Hiring engineers"],
            "contact_email": email, "source_quotes": ["We are hiring"]})
    if schema_name == "lead_score":
        m = re.search(r'"company_name": "([^"]+)"', user)
        name = m.group(1)
        return completion({"score": SCORES.get(name, 40), "fit_reasons": ["German B2B SaaS", "Right size"],
                           "concerns": ["No pricing page"], "recommended_next_step": "Book a discovery call"})
    if schema_name == "meeting_plan":
        name = re.search(r"Company: (.+)", user).group(1)
        return completion({"meeting_title": f"Intro call: {name}", "agenda": ["Intros", "Challenges", "Demo", "Next steps"],
                           "opening_line": f"Congrats on the recent momentum at {name}."})
    return {"error": {"message": "unknown schema " + schema_name}}


def handle_search(body):
    STATE["search"].append(body["query"])
    doms = list(PAGES)
    # every query returns overlapping sets so dedupe is exercised
    order = ["B2B logistics software Germany", "industrial SaaS manufacturers Germany", "warehouse automation platform Munich"]
    q = order.index(body["query"]) + 1 if body["query"] in order else 1
    chosen = doms[(q - 1) * 2:(q - 1) * 2 + 5] + ["acme-robotics.de"]
    data = [{"url": f"https://www.{d}/", "title": d, "description": PAGES[d][:80], "markdown": PAGES[d] * 2} for d in chosen]
    return {"success": True, "data": data}


def handle_freebusy(body):
    STATE["freebusy"].append(body)
    tmin = datetime.fromisoformat(body["timeMin"].replace("Z", "+00:00"))
    # a wall of meetings: everything in the first 30 hours of the window is busy
    busy = [{"start": tmin.isoformat().replace("+00:00", "Z"),
             "end": (tmin + timedelta(hours=30)).isoformat().replace("+00:00", "Z")}]
    return {"kind": "calendar#freeBusy", "calendars": {body["items"][0]["id"]: {"busy": busy}}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, raw=False):
        data = obj.encode() if raw else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain" if raw else "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/_state":
            with LOCK:
                return self._send(200, STATE)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode() if n else "{}"
        body = json.loads(raw or "{}")
        p = self.path.split("?")[0]
        with LOCK:
            if p == "/v1/chat/completions":
                return self._send(200, handle_openai(body))
            if p == "/v1/search":
                return self._send(200, handle_search(body))
            if p == "/crm/v3/objects/companies":
                STATE["hubspot"].append(body)
                return self._send(201, {"id": str(1000 + len(STATE["hubspot"])), "properties": body.get("properties", {})})
            if p == "/calendar/v3/freeBusy":
                return self._send(200, handle_freebusy(body))
            m = re.match(r"^/calendar/v3/calendars/([^/]+)/events$", p)
            if m:
                STATE["event_attempts"] += 1
                if body["id"] in STATE["events"]:
                    return self._send(409, {"error": {"code": 409, "message": "The requested identifier already exists."}})
                STATE["events"][body["id"]] = body
                return self._send(200, {"id": body["id"], "status": "confirmed",
                                        "htmlLink": "https://calendar.google.com/event?eid=" + body["id"][:12]})
            if p == "/slack":
                STATE["slack"].append(body)
                return self._send(200, "ok", raw=True)
        self._send(404, {"error": "not found " + p})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
