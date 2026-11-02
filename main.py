import os
from github import Github
from crewai import Agent, Task, Crew
from crewai.tools import tool
from langchain_openai import ChatOpenAI
from server import send_approval_to_slack
from dotenv import load_dotenv

load_dotenv()

gh = Github(os.getenv("GITHUB_TOKEN"))

@tool("Fetch GitHub Issues")
def fetch_github_issues(repo_name: str) -> str:
    """Fetch open issues from a specific GitHub repository."""
    try:
        repo = gh.get_repo(repo_name)
        issues = repo.get_issues(state='open')
        result = [f"- Issue #{i.number}: {i.title}" for i in issues[:5]]
        return f"Open Issues for {repo_name}:\n" + "\n".join(result) if result else "No open issues found."
    except Exception as e:
        return f"Error: {str(e)}"

@tool("Send Draft for Approval")
def trigger_slack_approval(draft_text: str) -> str:
    """Sends the drafted post to Slack for approval."""
    send_approval_to_slack(draft_text)
    return "Sent draft to Slack."

llm = ChatOpenAI(model="gpt-4o", temperature=0.3)

github_researcher = Agent(
    role="GitHub Technical Analyst",
    goal="Extract technical updates from GitHub repositories.",
    backstory="You analyze repository activity and extract key bug updates or features.",
    tools=[fetch_github_issues],
    llm=llm
)

copywriter = Agent(
    role="Tech Copywriter",
    goal="Draft engaging LinkedIn updates and dispatch them to Slack for sign-off.",
    backstory="You turn technical updates into readable, high-performing tech social posts.",
    tools=[trigger_slack_approval],
    llm=llm
)

task1 = Task(
    description="Analyze open issues and activity for repository: {repo_name}.",
    expected_output="Summary of issues and features.",
    agent=github_researcher
)

task2 = Task(
    description="Draft a LinkedIn post based on the summary and send it to Slack for approval.",
    expected_output="Confirmation of dispatch to Slack.",
    agent=copywriter
)

crew = Crew(agents=[github_researcher, copywriter], tasks=[task1, task2])

if __name__ == "__main__":
    crew.kickoff(inputs={"repo_name": "octocat/Hello-World"})
