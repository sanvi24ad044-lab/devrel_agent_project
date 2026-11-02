# DevRel GitHub & LinkedIn Agent

The agent summarizes open GitHub issues, drafts a LinkedIn update with CrewAI, and sends an approval card to Slack. LinkedIn publishing happens only after someone approves the Slack card.

## Setup

1. Install dependencies:
   ```powershell
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
   If you are not using a virtual environment, use `python -m pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` and configure these values:
   - `OPENAI_API_KEY`
   - `GITHUB_TOKEN`
   - `SLACK_BOT_TOKEN`
   - `SLACK_CHANNEL_ID`
   - `SLACK_SIGNING_SECRET` (from your Slack app's Basic Information page)
   - `LINKEDIN_ACCESS_TOKEN`
   - `LINKEDIN_PERSON_URN`
3. In your Slack app, enable Interactivity and set its request URL to `https://<your-public-host>/slack/interactive`. For local development, expose port 8000 with a trusted HTTPS tunnel and use that URL. Slack request signatures are verified before any approval is processed.
4. Start the dashboard and API:
   ```powershell
   .\venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
   ```
5. Open [http://127.0.0.1:8000](http://127.0.0.1:8000), enter a GitHub repository such as `octocat/Hello-World`, and select **Run agent**. The page shows the current run status and result. The agent sends the generated draft to Slack for review; it does not publish to LinkedIn unless approved there.

The dashboard's health endpoint at `/api/health` reports whether each integration setting is present without exposing its value. Missing LinkedIn settings prevent publishing; missing Slack signing secret prevents processing interactive approvals.