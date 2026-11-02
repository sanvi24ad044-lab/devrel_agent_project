import os
import json
import requests
from fastapi import FastAPI, Form
from slack_sdk import WebClient
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
slack_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID")

def publish_to_linkedin(content: str) -> str:
    url = "https://api.linkedin.com/v2/ugcPosts"
    headers = {
        "Authorization": f"Bearer {os.getenv('LINKEDIN_ACCESS_TOKEN')}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    payload = {
        "author": os.getenv("LINKEDIN_PERSON_URN"),
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    res = requests.post(url, headers=headers, json=payload)
    return "Published" if res.status_code == 201 else f"Failed: {res.text}"

def send_approval_to_slack(draft_text: str):
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🚨 *LinkedIn Post Approval Requested*\n\n```{draft_text}```"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve & Post"},
                    "style": "primary",
                    "value": draft_text,
                    "action_id": "approve_post"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "value": "rejected",
                    "action_id": "reject_post"
                }
            ]
        }
    ]
    slack_client.chat_postMessage(channel=SLACK_CHANNEL, blocks=blocks, text="Approval Requested")

@app.post("/slack/interactive")
async def slack_interactive(payload: str = Form(...)):
    data = json.loads(payload)
    action = data["actions"][0]
    action_id = action["action_id"]
    response_url = data["response_url"]

    if action_id == "approve_post":
        draft_content = action["value"]
        status = publish_to_linkedin(draft_content)
        reply = {"text": f"✅ *Approved & Published to LinkedIn!*\n\n*Status:* {status}", "replace_original": True}
    else:
        reply = {"text": "❌ *Post request rejected.*", "replace_original": True}

    requests.post(response_url, json=reply)
    return {"status": "ok"}
