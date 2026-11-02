import os

from crewai import Agent, Crew, Task
from crewai.tools import tool
from github import Github, GithubException
from langchain_openai import ChatOpenAI

from server import send_approval_to_slack


def _required_environment(*names: str) -> None:
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


@tool("Fetch GitHub Issues")
def fetch_github_issues(repo_name: str) -> str:
    """Fetch up to five open issues from a GitHub repository."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured.")

    try:
        repository = Github(token).get_repo(repo_name)
        issues = []
        for issue in repository.get_issues(state="open"):
            if issue.pull_request is None:
                issues.append(f"- Issue #{issue.number}: {issue.title}")
                if len(issues) == 5:
                    break
    except GithubException as exc:
        return f"Unable to fetch issues for {repo_name}: {exc.data}"

    if not issues:
        return f"No open issues found for {repo_name}."
    return f"Open issues for {repo_name}:\n" + "\n".join(issues)


@tool("Send Draft for Approval")
def trigger_slack_approval(draft_text: str) -> str:
    """Send a drafted LinkedIn post to Slack for approval."""
    send_approval_to_slack(draft_text)
    return "Draft sent to Slack for approval."


def run_agent(repo_name: str) -> str:
    """Analyze a repository, draft a LinkedIn post, and request Slack approval."""
    _required_environment(
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_CHANNEL_ID",
        "SLACK_SIGNING_SECRET",
        "LINKEDIN_ACCESS_TOKEN",
        "LINKEDIN_PERSON_URN",
    )

    llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
    github_researcher = Agent(
        role="GitHub Technical Analyst",
        goal="Extract accurate technical updates from open GitHub issues.",
        backstory="You analyze repository issues and summarize only verifiable details.",
        tools=[fetch_github_issues],
        llm=llm,
    )
    copywriter = Agent(
        role="Tech Copywriter",
        goal="Draft a factual LinkedIn update and send it to Slack for approval.",
        backstory="You turn technical updates into clear, engaging social posts without inventing facts.",
        tools=[trigger_slack_approval],
        llm=llm,
    )

    research_task = Task(
        description=(
            "Analyze the open issues for the GitHub repository {repo_name}. "
            "Use the GitHub tool and report only information returned by it."
        ),
        expected_output="A concise, factual summary of the repository's open issues.",
        agent=github_researcher,
    )
    approval_task = Task(
        description=(
            "Using only the research summary, draft a concise LinkedIn post. "
            "Do not invent repository updates or claim issues are fixed. "
            "You must send the draft to Slack with the approval tool."
        ),
        expected_output="Confirmation that the draft was sent to Slack for approval.",
        agent=copywriter,
        context=[research_task],
    )

    result = Crew(
        agents=[github_researcher, copywriter],
        tasks=[research_task, approval_task],
    ).kickoff(inputs={"repo_name": repo_name})
    return str(result)


if __name__ == "__main__":
    print(run_agent("octocat/Hello-World"))
