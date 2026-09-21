#!/usr/bin/env python3
"""Make an offline copy of the workflow that talks to the local mock server.

    python3 make_test_workflow.py <workflow.json> <out.json> <mock-port>

Only the Config values (base URLs, Slack webhook, secret) change and credentials are
stripped. Every node, prompt and code snippet stays identical to the shipped workflow.
"""
import json
import sys

src, dst, port = sys.argv[1], sys.argv[2], sys.argv[3]
w = json.load(open(src))
base = f"http://127.0.0.1:{port}"
override = {
    "openaiBaseUrl": base, "firecrawlBaseUrl": base, "hubspotBaseUrl": base, "googleBaseUrl": base,
    "slackWebhookUrl": base + "/slack", "approvalSecret": "test-secret",
}
for n in w["nodes"]:
    if n["type"] == "n8n-nodes-base.set":
        for a in n["parameters"]["assignments"]["assignments"]:
            if a["name"] in override:
                a["value"] = override[a["name"]]
    if n["type"] == "n8n-nodes-base.httpRequest":
        for k in ("authentication", "nodeCredentialType", "genericAuthType"):
            n["parameters"].pop(k, None)
        n.pop("credentials", None)
        n.pop("retryOnFail", None)
w["id"] = "gtmtest0000000001"
json.dump(w, open(dst, "w"), indent=1)
print("wrote", dst)
