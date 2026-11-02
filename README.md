# DevRel GitHub & LinkedIn Agent

An automated agent that monitors GitHub repositories, drafts LinkedIn updates using CrewAI, sends interactive approval cards to Slack, and publishes directly to LinkedIn upon approval.

## Setup Instructions

1. **Unzip the files into a single directory.**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure environment variables:**
   Update `.env` with your API keys for OpenAI, GitHub, LinkedIn, and Slack.
4. **Run the FastAPI Server (Terminal 1):**
   ```bash
   uvicorn server:app --port 8000
   ```
5. **Run the CrewAI Agent (Terminal 2):**
   ```bash
   python main.py
   ```
