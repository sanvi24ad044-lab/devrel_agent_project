import hashlib
import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from slack_sdk import WebClient

load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI(title="DevRel GitHub & LinkedIn Agent")
run_lock = threading.Lock()
run_state = {
    "status": "idle",
    "repo_name": None,
    "started_at": None,
    "finished_at": None,
    "message": "Ready to run.",
    "result": None,
}

REQUIRED_RUN_SETTINGS = (
    "OPENAI_API_KEY",
    "GITHUB_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_CHANNEL_ID",
    "SLACK_SIGNING_SECRET",
    "LINKEDIN_ACCESS_TOKEN",
    "LINKEDIN_PERSON_URN",
)

DASHBOARD = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DevRel Agent</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, Segoe UI, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: #101827; color: #e8eef8; }
    main { width: min(680px, calc(100% - 40px)); padding: 32px; border: 1px solid #29364a;
      border-radius: 16px; background: #172235; box-shadow: 0 24px 80px #080d16; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    p { color: #aab8cd; line-height: 1.55; }
    label { display: block; margin: 24px 0 8px; font-weight: 600; }
    input { box-sizing: border-box; width: 100%; padding: 12px 14px; border: 1px solid #43536b;
      border-radius: 8px; background: #101827; color: inherit; font: inherit; }
    button { margin-top: 14px; padding: 11px 16px; border: 0; border-radius: 8px;
      background: #3678f6; color: white; font: inherit; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }
    .panel { margin-top: 24px; padding: 16px; border-radius: 10px; background: #101827; }
    .status { font-weight: 700; text-transform: capitalize; }
    pre { max-height: 260px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere;
      color: #c6d4e8; font: 13px/1.5 Consolas, monospace; }
    .muted { font-size: 13px; }
    .error { color: #ff9a9a; }
  </style>
</head>
<body>
  <main>
    <h1>DevRel Agent</h1>
    <p>Analyze a GitHub repository, draft a LinkedIn update, and send it to Slack for your approval.</p>
    <form id="run-form">
      <label for="repo">GitHub repository</label>
      <input id="repo" name="repo_name" value="octocat/Hello-World"
        pattern="[\w.\-]+/[\w.\-]+" required>
      <button id="run-button" type="submit">Run agent</button>
    </form>
    <section class="panel" aria-live="polite">
      <div>Status: <span id="status" class="status">loading</span></div>
      <p id="message" class="muted">Checking configuration…</p>
      <pre id="result"></pre>
    </section>
  </main>
  <script>
    const form = document.querySelector("#run-form");
    const button = document.querySelector("#run-button");
    const status = document.querySelector("#status");
    const message = document.querySelector("#message");
    const result = document.querySelector("#result");

    async function refreshStatus() {
      try {
        const [runResponse, healthResponse] = await Promise.all([
          fetch("/api/agent/status"), fetch("/api/health")
        ]);
        if (!runResponse.ok || !healthResponse.ok) throw new Error("Unable to load agent status.");
        const run = await runResponse.json();
        const health = await healthResponse.json();
        status.textContent = run.status;
        const missing = Object.entries(health.configuration)
          .filter(([, configured]) => !configured).map(([name]) => name);
        message.textContent = missing.length
          ? `Missing configuration: ${missing.join(", ")}`
          : run.message;
        message.classList.toggle("error", missing.length > 0 || run.status === "failed");
        result.textContent = run.result || "";
        button.disabled = !Object.values(health.configuration).every(Boolean)
          || run.status === "queued" || run.status === "running";
      } catch (error) {
        status.textContent = "unavailable";
        message.textContent = error.message;
        message.classList.add("error");
        button.disabled = true;
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      button.disabled = true;
      message.textContent = "Starting agent…";
      message.classList.remove("error");
      try {
        const response = await fetch("/api/agent/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_name: form.elements.repo_name.value })
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Unable to start the agent.");
        await refreshStatus();
      } catch (error) {
        message.textContent = error.message;
        message.classList.add("error");
        button.disabled = false;
      }
    });

    refreshStatus();
    window.setInterval(refreshStatus, 2000);
  </script>
</body>
</html>"""


class AgentRunRequest(BaseModel):
    repo_name: str = Field(
        min_length=3,
        max_length=200,
        pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
    )


def _required_environment(*names: str) -> dict[str, str]:
    values = {name: os.getenv(name) for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    return {name: value for name, value in values.items() if value is not None}


def publish_to_linkedin(content: str) -> str:
    settings = _required_environment("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN")
    response = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {settings['LINKEDIN_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json={
            "author": settings["LINKEDIN_PERSON_URN"],
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        },
        timeout=15,
    )
    response.raise_for_status()
    return "Published"


def send_approval_to_slack(draft_text: str) -> None:
    settings = _required_environment("SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID")
    if not draft_text or len(draft_text) > 2000:
        raise ValueError("The Slack approval draft must contain 1 to 2000 characters.")

    client = WebClient(token=settings["SLACK_BOT_TOKEN"])
    client.chat_postMessage(
        channel=settings["SLACK_CHANNEL_ID"],
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🚨 *LinkedIn Post Approval Requested*\n\n```{draft_text}```",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve & Post"},
                        "style": "primary",
                        "value": draft_text,
                        "action_id": "approve_post",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "value": "rejected",
                        "action_id": "reject_post",
                    },
                ],
            },
        ],
        text="Approval Requested",
    )


def _valid_slack_signature(
    body: bytes, timestamp: str | None, signature: str | None, secret: str | None
) -> bool:
    if not timestamp or not signature or not secret:
        return False
    try:
        request_time = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - request_time) > 300:
        return False

    base_string = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), base_string, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"v0={digest}", signature)


def _update_run_state(**updates: str | None) -> None:
    with run_lock:
        run_state.update(updates)


def _execute_agent(repo_name: str) -> None:
    _update_run_state(
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        message=f"Analyzing {repo_name}; the draft will be sent to Slack for approval.",
        result=None,
    )
    try:
        from main import run_agent

        result = run_agent(repo_name)
    except Exception as exc:
        logger.exception("Agent run failed for %s", repo_name)
        _update_run_state(
            status="failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            message=str(exc),
            result=None,
        )
        return

    _update_run_state(
        status="completed",
        finished_at=datetime.now(timezone.utc).isoformat(),
        message="Agent finished and sent its draft to Slack for approval.",
        result=result,
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return DASHBOARD


@app.get("/api/health")
async def health() -> dict[str, object]:
    names = (*REQUIRED_RUN_SETTINGS, "SLACK_SIGNING_SECRET",
             "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN")
    return {
        "status": "ok",
        "configuration": {name: bool(os.getenv(name)) for name in names},
    }


@app.get("/api/agent/status")
async def agent_status() -> dict[str, object]:
    with run_lock:
        return dict(run_state)


@app.post("/api/agent/run", status_code=202)
async def start_agent(
    request: AgentRunRequest, background_tasks: BackgroundTasks
) -> dict[str, str]:
    missing = [name for name in REQUIRED_RUN_SETTINGS if not os.getenv(name)]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Missing required environment variables: {', '.join(missing)}",
        )

    with run_lock:
        if run_state["status"] in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="An agent run is already in progress.")
        run_state.update(
            status="queued",
            repo_name=request.repo_name,
            started_at=None,
            finished_at=None,
            message=f"Queued analysis for {request.repo_name}.",
            result=None,
        )
    background_tasks.add_task(_execute_agent, request.repo_name)
    return {"status": "queued", "repo_name": request.repo_name}


@app.post("/slack/interactive")
async def slack_interactive(request: Request) -> dict[str, str]:
    secret = os.getenv("SLACK_SIGNING_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="SLACK_SIGNING_SECRET is not configured.")

    body = await request.body()
    if not _valid_slack_signature(
        body,
        request.headers.get("X-Slack-Request-Timestamp"),
        request.headers.get("X-Slack-Signature"),
        secret,
    ):
        raise HTTPException(status_code=401, detail="Invalid Slack request signature.")

    try:
        payload_value = parse_qs(body.decode("utf-8")).get("payload", [None])[0]
        if payload_value is None:
            raise ValueError("Missing payload field.")
        data = json.loads(payload_value)
        action = data["actions"][0]
        action_id = action["action_id"]
        response_url = data["response_url"]
    except (UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Slack interaction payload.") from exc

    if action_id == "approve_post":
        try:
            status = publish_to_linkedin(action["value"])
        except (RuntimeError, requests.RequestException, ValueError) as exc:
            reply = {
                "text": f"⚠️ *Unable to publish to LinkedIn.*\n\n{exc}",
                "replace_original": True,
            }
        else:
            reply = {
                "text": f"✅ *Approved & Published to LinkedIn!*\n\n*Status:* {status}",
                "replace_original": True,
            }
    elif action_id == "reject_post":
        reply = {"text": "❌ *Post request rejected.*", "replace_original": True}
    else:
        raise HTTPException(status_code=400, detail="Unsupported Slack action.")

    response = requests.post(response_url, json=reply, timeout=10)
    response.raise_for_status()
    return {"status": "ok"}
