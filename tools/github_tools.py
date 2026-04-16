"""
GitHub tool definitions and execution functions for the calendar-agent.

GitHub Search API rate limit: 30 requests/min for authenticated users.
All API responses are compressed before returning to Claude to keep token usage low.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from tools.github_utils import (
    age_in_days,
    compress_issue,
    compress_pr,
    compress_review_threads,
    get_github_headers,
)
from core.session import get_session, save_session

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

GITHUB_TOOLS = [
    {
        "name": "github_my_prs",
        "description": (
            "List the authenticated user's open pull requests. Returns authored PRs and PRs where "
            "review is requested. Includes CI status, review decision, days open, and labels."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Filter to a specific repository in owner/repo format (optional).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of PRs to return. Default 20.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "github_pr_detail",
        "description": (
            "Get full details of a pull request: description, review threads with comments, "
            "CI check statuses, labels, merge status. Use when user asks about specific review "
            "comments or CI failures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
            },
            "required": ["repo", "pr_number"],
        },
    },
    {
        "name": "github_pr_review_requested",
        "description": (
            "List open PRs where the authenticated user has a pending review request from teammates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of PRs to return. Default 10.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "github_my_issues",
        "description": (
            "List issues assigned to or created by any GitHub user. "
            "Defaults to the authenticated user. Pass assignee to check another person's issues "
            "(useful for checking a teammate's workload in a shared repo). "
            "Filterable by label and repo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Filter to a specific repository in owner/repo format (optional).",
                },
                "assignee": {
                    "type": "string",
                    "description": (
                        "GitHub username to check issues for. Omit to use the authenticated user. "
                        "Use github_search_user first if you only have a display name."
                    ),
                },
                "role": {
                    "type": "string",
                    "enum": ["assigned", "created", "both"],
                    "description": "Whether to return issues assigned to or created by the user. Default: assigned.",
                },
                "label": {
                    "type": "string",
                    "description": "Filter by label name (optional).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of issues to return. Default 20.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "github_search_user",
        "description": (
            "Search for a GitHub user by their display name or partial name, optionally within "
            "a specific org. Returns matching GitHub logins. Use this before github_my_issues or "
            "github_my_prs when the user gives a person's name instead of a GitHub username."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Display name or partial name to search for (e.g. 'Hritvik Mohan').",
                },
                "org": {
                    "type": "string",
                    "description": "Limit search to this GitHub org name (e.g. 'NewtonSchool'). Optional but recommended.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "github_issue_detail",
        "description": (
            "Get full details of an issue including all comments chronologically. "
            "Use when user wants to understand or discuss a specific issue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
                "issue_number": {
                    "type": "integer",
                    "description": "The issue number.",
                },
            },
            "required": ["repo", "issue_number"],
        },
    },
    {
        "name": "github_repo_list",
        "description": (
            "List repositories the user owns or contributes to. "
            "Call once per session to cache available repos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of repos to return. Default 30.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "github_repo_labels",
        "description": (
            "List all labels defined in a repository with their descriptions and colors. "
            "Use when user asks about tags, labels, or wants to filter by label but doesn't "
            "know exact names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
            },
            "required": ["repo"],
        },
    },
    {
        "name": "github_recent_activity",
        "description": (
            "Get the user's GitHub activity over the past N days: merged PRs, closed issues, "
            "reviews given. Use for generating standup notes or weekly summaries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look back. Default 1.",
                },
                "repo": {
                    "type": "string",
                    "description": "Filter to a specific repository in owner/repo format (optional).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "github_create_pr",
        "description": (
            "Create a new pull request. If head branch is not provided, call this tool without "
            "head and the response will include available branches to ask the user. "
            "Gather title conversationally if not given. Always confirm before creating: "
            "'Creating PR \\'[title]\\' from [head] → [base]. Ready to open? (yes/no)'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
                "head": {
                    "type": "string",
                    "description": "The branch containing the changes.",
                },
                "base": {
                    "type": "string",
                    "description": "The branch to merge into. Default: main.",
                },
                "title": {
                    "type": "string",
                    "description": "PR title.",
                },
                "body": {
                    "type": "string",
                    "description": "PR description (optional).",
                },
                "draft": {
                    "type": "boolean",
                    "description": "Whether to open as a draft PR. Default false.",
                },
            },
            "required": ["repo", "title"],
        },
    },
    {
        "name": "github_pr_submit_review",
        "description": (
            "Submit a review on a pull request: approve, request changes, or leave a comment review. "
            "Executes immediately — no confirmation needed. Body is required when event=REQUEST_CHANGES."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
                "event": {
                    "type": "string",
                    "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"],
                    "description": "Review action to take.",
                },
                "body": {
                    "type": "string",
                    "description": "Review body. Required when event=REQUEST_CHANGES.",
                },
            },
            "required": ["repo", "pr_number", "event"],
        },
    },
    {
        "name": "github_pr_comment",
        "description": (
            "Add a comment to a pull request's issue thread. Executes immediately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
                "body": {
                    "type": "string",
                    "description": "Comment text.",
                },
            },
            "required": ["repo", "pr_number", "body"],
        },
    },
    {
        "name": "github_pr_merge",
        "description": (
            "Merge a pull request. ALWAYS ask the user first: "
            "'Merge `{repo}#{pr_number}` via {method}? (yes/no)' — only call this tool after confirmation. "
            "Replies with the merge SHA on success."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
                "merge_method": {
                    "type": "string",
                    "enum": ["merge", "squash", "rebase"],
                    "description": "Merge strategy. Default: squash.",
                },
            },
            "required": ["repo", "pr_number"],
        },
    },
    {
        "name": "github_pr_close",
        "description": (
            "Close a pull request without merging. "
            "ALWAYS ask the user first: 'Close `{repo}#{pr_number}` without merging? (yes/no)' "
            "— only call this tool after confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
            },
            "required": ["repo", "pr_number"],
        },
    },
    {
        "name": "github_pr_request_reviewers",
        "description": (
            "Request reviews from one or more GitHub users on a pull request. "
            "Executes immediately. If the user gives display names instead of GitHub logins, "
            "call github_search_user first. Confirm after: 'Requested review from @alice and @bob.'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
                "reviewers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of GitHub logins to request reviews from.",
                },
            },
            "required": ["repo", "pr_number", "reviewers"],
        },
    },
    {
        "name": "github_pr_set_labels",
        "description": (
            "Add or remove labels on a pull request. Executes immediately. "
            "If unsure of exact label names, call github_repo_labels first. "
            "Confirm after: 'Added \\'needs-review\\', removed \\'WIP\\'.' "
            "At least one of add or remove must be provided."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
                "add": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label names to add (optional).",
                },
                "remove": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label names to remove (optional).",
                },
            },
            "required": ["repo", "pr_number"],
        },
    },
]


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

async def _get_github_username_and_token(chat_id: int) -> tuple[str, str]:
    """
    Return (token, username) for the given chat_id.

    Priority:
    1. Session context (set after first auth or from env var bootstrap)
    2. GET /user call to resolve username if token is known but username is not

    Raises RuntimeError with a user-friendly message if no token is available.
    """
    session = get_session(chat_id)
    ctx = session["ctx"]

    token = ctx.get("github_token") or ""
    username = ctx.get("github_username") or ""

    if not token:
        raise RuntimeError(
            "GitHub is not connected. Send /github to link your account with a Personal Access Token."
        )

    if not username:
        # Resolve username via API and cache it
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/user",
                headers=get_github_headers(token),
                timeout=10,
            )
            _raise_for_github_status(resp)
            data = resp.json()
            username = data.get("login", "")

        if username:
            ctx["github_username"] = username
            save_session(chat_id, session)

    return token, username


def _raise_for_github_status(resp: httpx.Response) -> None:
    """Raise a descriptive RuntimeError for common GitHub API error codes."""
    if resp.status_code == 401:
        raise RuntimeError(
            "GitHub token is invalid or expired. Send /github to reconnect."
        )
    if resp.status_code == 403:
        rate_remaining = resp.headers.get("x-ratelimit-remaining", "?")
        if rate_remaining == "0":
            raise RuntimeError(
                "GitHub API rate limit reached. Please wait a minute and try again."
            )
        raise RuntimeError(
            "GitHub access denied. Check that your token has the required scopes: repo, read:org, read:user."
        )
    if resp.status_code == 404:
        raise RuntimeError(
            "GitHub resource not found. Check the repo name or issue/PR number."
        )
    resp.raise_for_status()


def _relative_time(iso_str: str) -> str:
    """Return a human-readable relative time string like '2 days ago'."""
    if not iso_str:
        return ""
    try:
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        days = delta.days
        if days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                mins = delta.seconds // 60
                return f"{mins} minute{'s' if mins != 1 else ''} ago"
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if days == 1:
            return "1 day ago"
        if days < 30:
            return f"{days} days ago"
        months = days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    except (ValueError, TypeError):
        return iso_str


async def _resolve_repo(token: str, username: str, repo_hint: str) -> str:
    """
    If repo_hint is already in 'owner/repo' format, return it as-is.
    If it's just a repo name, search the user's repos to find the full name.
    """
    if "/" in repo_hint:
        return repo_hint
    # Search for a repo matching the name
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/user/repos",
            headers=get_github_headers(token),
            params={"affiliation": "owner,collaborator", "per_page": 100, "sort": "pushed"},
            timeout=10,
        )
        _raise_for_github_status(resp)
        repos = resp.json()
    for r in repos:
        if r.get("name", "").lower() == repo_hint.lower():
            return r.get("full_name", repo_hint)
    return repo_hint  # Return as-is if not found


async def _list_branches(token: str, repo: str) -> list[str]:
    """Return branch names for a repo. Used internally by github_create_pr."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/branches",
            headers=get_github_headers(token),
            params={"per_page": 100},
            timeout=10,
        )
        _raise_for_github_status(resp)
        data = resp.json()
    return [b.get("name", "") for b in data]


# ---------------------------------------------------------------------------
# Execution functions
# ---------------------------------------------------------------------------

async def _execute_github_my_prs(chat_id: int, repo: str = None, limit: int = 20) -> dict:
    """List authored PRs and review-requested PRs for the authenticated user."""
    token, username = await _get_github_username_and_token(chat_id)

    authored_query = f"is:pr is:open author:@me"
    review_query = f"is:pr is:open review-requested:@me"

    if repo:
        repo = await _resolve_repo(token, username, repo)
        authored_query += f" repo:{repo}"
        review_query += f" repo:{repo}"

    async with httpx.AsyncClient() as client:
        # Fetch authored PRs
        authored_resp = await client.get(
            f"{GITHUB_API_BASE}/search/issues",
            headers=get_github_headers(token),
            params={"q": authored_query, "per_page": limit},
            timeout=15,
        )
        _raise_for_github_status(authored_resp)
        authored_data = authored_resp.json()

        # Fetch review-requested PRs
        review_resp = await client.get(
            f"{GITHUB_API_BASE}/search/issues",
            headers=get_github_headers(token),
            params={"q": review_query, "per_page": limit},
            timeout=15,
        )
        _raise_for_github_status(review_resp)
        review_data = review_resp.json()

        # For each authored PR, fetch CI check runs
        authored_prs = []
        for item in authored_data.get("items", []):
            pr_raw = dict(item)
            # Extract owner/repo from repository_url for CI lookup
            repo_url = item.get("repository_url", "")
            parts = repo_url.rstrip("/").split("/")
            if len(parts) >= 2:
                pr_repo = f"{parts[-2]}/{parts[-1]}"
                # Get the PR detail to find head SHA
                pr_num = item.get("number")
                try:
                    pr_detail_resp = await client.get(
                        f"{GITHUB_API_BASE}/repos/{pr_repo}/pulls/{pr_num}",
                        headers=get_github_headers(token),
                        timeout=10,
                    )
                    if pr_detail_resp.status_code == 200:
                        pr_detail = pr_detail_resp.json()
                        sha = pr_detail.get("head", {}).get("sha", "")
                        pr_raw["draft"] = pr_detail.get("draft", False)
                        pr_raw["mergeable"] = pr_detail.get("mergeable")
                        if sha:
                            ci_resp = await client.get(
                                f"{GITHUB_API_BASE}/repos/{pr_repo}/commits/{sha}/check-runs",
                                headers=get_github_headers(token),
                                timeout=10,
                            )
                            if ci_resp.status_code == 200:
                                ci_data = ci_resp.json()
                                runs = ci_data.get("check_runs", [])
                                conclusions = [r.get("conclusion") for r in runs if r.get("conclusion")]
                                if not runs:
                                    pr_raw["_ci_status"] = "no_checks"
                                elif all(c == "success" for c in conclusions):
                                    pr_raw["_ci_status"] = "passing"
                                elif any(c in ("failure", "timed_out", "action_required") for c in conclusions):
                                    pr_raw["_ci_status"] = "failing"
                                elif any(c is None for c in [r.get("conclusion") for r in runs]):
                                    pr_raw["_ci_status"] = "pending"
                                else:
                                    pr_raw["_ci_status"] = "unknown"
                except Exception as exc:
                    logger.warning("Could not fetch CI for PR %s#%s: %s", pr_repo, pr_num, exc)

            authored_prs.append(compress_pr(pr_raw, username))

        review_prs = [compress_pr(item, username) for item in review_data.get("items", [])]

    return {
        "authored": authored_prs,
        "review_requested": review_prs,
    }


async def _execute_github_pr_detail(chat_id: int, repo: str, pr_number: int) -> dict:
    """Get full details of a specific pull request including reviews, comments, and CI."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    async with httpx.AsyncClient() as client:
        # Fetch PR details
        pr_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}",
            headers=get_github_headers(token),
            timeout=10,
        )
        _raise_for_github_status(pr_resp)
        pr_data = pr_resp.json()

        # Fetch reviews
        reviews_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/reviews",
            headers=get_github_headers(token),
            timeout=10,
        )
        reviews = reviews_resp.json() if reviews_resp.status_code == 200 else []

        # Fetch inline comments
        comments_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/comments",
            headers=get_github_headers(token),
            timeout=10,
        )
        comments = comments_resp.json() if comments_resp.status_code == 200 else []

        # Fetch CI check runs
        sha = pr_data.get("head", {}).get("sha", "")
        ci_checks = {"passed": 0, "failed": 0, "pending": 0, "failed_names": []}
        if sha:
            ci_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{repo}/commits/{sha}/check-runs",
                headers=get_github_headers(token),
                timeout=10,
            )
            if ci_resp.status_code == 200:
                ci_data = ci_resp.json()
                for run in ci_data.get("check_runs", []):
                    conclusion = run.get("conclusion")
                    name = run.get("name", "")
                    status = run.get("status", "")
                    if conclusion == "success":
                        ci_checks["passed"] += 1
                    elif conclusion in ("failure", "timed_out", "action_required"):
                        ci_checks["failed"] += 1
                        ci_checks["failed_names"].append(name)
                    elif status in ("in_progress", "queued", "waiting") or conclusion is None:
                        ci_checks["pending"] += 1

    # Determine review decision from the most recent review per reviewer
    review_decision = pr_data.get("review_decision") or ""
    if not review_decision and reviews:
        reviewer_latest: dict[str, str] = {}
        for r in reviews:
            login = (r.get("user") or {}).get("login", "")
            state = r.get("state", "")
            if login and state not in ("COMMENTED",):
                reviewer_latest[login] = state
        states = list(reviewer_latest.values())
        if any(s == "CHANGES_REQUESTED" for s in states):
            review_decision = "CHANGES_REQUESTED"
        elif all(s == "APPROVED" for s in states) and states:
            review_decision = "APPROVED"
        elif any(s == "APPROVED" for s in states):
            review_decision = "REVIEW_REQUIRED"

    review_threads = compress_review_threads(reviews, comments)

    body = pr_data.get("body") or ""
    labels = [lbl.get("name", "") for lbl in pr_data.get("labels", [])]

    return {
        "number": pr_data.get("number"),
        "title": pr_data.get("title", ""),
        "repo": repo,
        "url": pr_data.get("html_url", ""),
        "body_summary": body[:400],
        "days_open": age_in_days(pr_data.get("created_at", "")),
        "review_threads": review_threads,
        "ci_checks": ci_checks,
        "labels": labels,
        "mergeable": pr_data.get("mergeable"),
        "draft": pr_data.get("draft", False),
        "review_decision": review_decision,
    }


async def _execute_github_pr_review_requested(chat_id: int, limit: int = 10) -> dict:
    """List open PRs where the user has a pending review request."""
    token, username = await _get_github_username_and_token(chat_id)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/search/issues",
            headers=get_github_headers(token),
            params={"q": f"is:pr is:open review-requested:@me", "per_page": limit},
            timeout=15,
        )
        _raise_for_github_status(resp)
        data = resp.json()

    prs = [compress_pr(item, username) for item in data.get("items", [])]
    return {"prs": prs}


async def _execute_github_search_user(
    chat_id: int,
    name: str,
    org: str = None,
) -> dict:
    """Search for a GitHub user by display name, optionally scoped to an org."""
    token, _username = await _get_github_username_and_token(chat_id)

    results = []

    # Strategy 1: GitHub user search (finds public profiles by name)
    query = name
    if org:
        query += f" org:{org}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/search/users",
            headers=get_github_headers(token),
            params={"q": query, "per_page": 10},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("items", []):
                results.append({
                    "login": item.get("login", ""),
                    "name": item.get("name") or "",
                    "avatar_url": item.get("avatar_url", ""),
                })

        # Strategy 2: If org given, also list org members and fuzzy-match by login/name
        if org and not results:
            members_resp = await client.get(
                f"{GITHUB_API_BASE}/orgs/{org}/members",
                headers=get_github_headers(token),
                params={"per_page": 100},
                timeout=10,
            )
            if members_resp.status_code == 200:
                name_lower = name.lower()
                for member in members_resp.json():
                    login = member.get("login", "")
                    if name_lower in login.lower():
                        results.append({"login": login, "name": ""})

    if not results:
        return {"matches": [], "message": f"No GitHub users found matching '{name}'."}

    return {"matches": results}


async def _execute_github_my_issues(
    chat_id: int,
    repo: str = None,
    assignee: str = None,
    role: str = "assigned",
    label: str = None,
    limit: int = 20,
) -> dict:
    """List issues assigned to or created by a GitHub user (defaults to authenticated user)."""
    token, username = await _get_github_username_and_token(chat_id)

    # Use @me for the authenticated user (avoids username casing issues),
    # or use the provided assignee login directly.
    target_user = assignee if assignee else "@me"

    # Build search query — use spaces as separators (not +), httpx will encode
    # spaces correctly as %20, which GitHub Search API reliably interprets.
    query_parts = ["is:issue", "is:open"]

    if role == "assigned":
        query_parts.append(f"assignee:{target_user}")
    elif role == "created":
        query_parts.append(f"author:{target_user}")
    else:  # "both"
        query_parts.append(f"involves:{target_user}")

    if label:
        query_parts.append(f'label:"{label}"')

    if repo:
        repo = await _resolve_repo(token, username, repo)
        query_parts.append(f"repo:{repo}")

    query = " ".join(query_parts)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/search/issues",
            headers=get_github_headers(token),
            params={"q": query, "per_page": limit},
            timeout=15,
        )
        _raise_for_github_status(resp)
        data = resp.json()

    issues = [compress_issue(item) for item in data.get("items", [])]
    return {"issues": issues}


async def _execute_github_issue_detail(chat_id: int, repo: str, issue_number: int) -> dict:
    """Get full details of a specific issue including all comments."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    async with httpx.AsyncClient() as client:
        # Fetch issue
        issue_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}",
            headers=get_github_headers(token),
            timeout=10,
        )
        _raise_for_github_status(issue_resp)
        issue_data = issue_resp.json()

        # Fetch comments
        comments_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments",
            headers=get_github_headers(token),
            timeout=10,
        )
        raw_comments = comments_resp.json() if comments_resp.status_code == 200 else []

    labels = [lbl.get("name", "") for lbl in issue_data.get("labels", [])]
    assignees = [a.get("login", "") for a in issue_data.get("assignees", [])]
    body = issue_data.get("body") or ""

    comments = []
    for c in raw_comments:
        author = (c.get("user") or {}).get("login", "")
        comment_body = c.get("body") or ""
        created_at = c.get("created_at", "")
        comments.append({
            "author": author,
            "body": comment_body[:300],
            "created_at": _relative_time(created_at),
        })

    return {
        "number": issue_data.get("number"),
        "title": issue_data.get("title", ""),
        "repo": repo,
        "url": issue_data.get("html_url", ""),
        "state": issue_data.get("state", ""),
        "body": body[:600],
        "labels": labels,
        "assignees": assignees,
        "days_open": age_in_days(issue_data.get("created_at", "")),
        "comments": comments,
    }


async def _execute_github_repo_list(chat_id: int, limit: int = 30) -> dict:
    """List repositories the user owns or contributes to."""
    token, username = await _get_github_username_and_token(chat_id)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/user/repos",
            headers=get_github_headers(token),
            params={"affiliation": "owner,collaborator", "per_page": limit, "sort": "pushed"},
            timeout=15,
        )
        _raise_for_github_status(resp)
        data = resp.json()

    repos = []
    for r in data:
        repos.append({
            "full_name": r.get("full_name", ""),
            "description": (r.get("description") or "")[:120],
            "language": r.get("language") or "",
            "open_issues_count": r.get("open_issues_count", 0),
            "pushed_at": _relative_time(r.get("pushed_at", "")),
        })

    # Cache the repo list in session for future reference
    session = get_session(chat_id)
    session["ctx"]["github_default_repos"] = [r["full_name"] for r in repos]
    save_session(chat_id, session)

    return {"repos": repos}


async def _execute_github_repo_labels(chat_id: int, repo: str) -> dict:
    """List all labels defined in a repository."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/labels",
            headers=get_github_headers(token),
            params={"per_page": 100},
            timeout=10,
        )
        _raise_for_github_status(resp)
        data = resp.json()

    labels = [
        {
            "name": lbl.get("name", ""),
            "description": lbl.get("description") or "",
            "color": lbl.get("color", ""),
        }
        for lbl in data
    ]
    return {"repo": repo, "labels": labels}


async def _execute_github_recent_activity(
    chat_id: int,
    days: int = 1,
    repo: str = None,
) -> dict:
    """Get the user's GitHub activity over the past N days."""
    token, username = await _get_github_username_and_token(chat_id)

    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    repo_filter = ""
    if repo:
        repo = await _resolve_repo(token, username, repo)
        repo_filter = f" repo:{repo}"

    merged_query = f"is:pr is:merged author:@me merged:>{since_date}{repo_filter}"
    closed_query = f"is:issue is:closed assignee:@me closed:>{since_date}{repo_filter}"
    reviewed_query = f"is:pr is:open reviewed-by:@me updated:>{since_date}{repo_filter}"

    async with httpx.AsyncClient() as client:
        merged_resp = await client.get(
            f"{GITHUB_API_BASE}/search/issues",
            headers=get_github_headers(token),
            params={"q": merged_query, "per_page": 30},
            timeout=15,
        )
        _raise_for_github_status(merged_resp)
        merged_data = merged_resp.json()

        closed_resp = await client.get(
            f"{GITHUB_API_BASE}/search/issues",
            headers=get_github_headers(token),
            params={"q": closed_query, "per_page": 30},
            timeout=15,
        )
        _raise_for_github_status(closed_resp)
        closed_data = closed_resp.json()

        reviewed_resp = await client.get(
            f"{GITHUB_API_BASE}/search/issues",
            headers=get_github_headers(token),
            params={"q": reviewed_query, "per_page": 30},
            timeout=15,
        )
        _raise_for_github_status(reviewed_resp)
        reviewed_data = reviewed_resp.json()

    merged_prs = [compress_pr(item, username) for item in merged_data.get("items", [])]
    closed_issues = [compress_issue(item) for item in closed_data.get("items", [])]
    reviews_given = [compress_pr(item, username) for item in reviewed_data.get("items", [])]

    return {
        "merged_prs": merged_prs,
        "closed_issues": closed_issues,
        "reviews_given": reviews_given,
        "since": since_date,
    }


async def _execute_github_create_pr(
    chat_id: int,
    repo: str,
    title: str,
    head: str = "",
    base: str = "main",
    body: str = "",
    draft: bool = False,
) -> dict:
    """Create a pull request. If head is empty, returns available branches for user to pick."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    if not head:
        branches = await _list_branches(token, repo)
        return {"needs_branch_selection": True, "branches": branches}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls",
            headers=get_github_headers(token),
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
            timeout=15,
        )
        if resp.status_code == 422:
            raise RuntimeError("A PR for this branch already exists.")
        _raise_for_github_status(resp)
        data = resp.json()

    return {
        "number": data.get("number"),
        "title": data.get("title", ""),
        "url": data.get("html_url", ""),
        "head": head,
        "base": base,
        "draft": draft,
    }


async def _execute_github_pr_submit_review(
    chat_id: int,
    repo: str,
    pr_number: int,
    event: str,
    body: str = "",
) -> dict:
    """Submit a review on a PR (APPROVE, REQUEST_CHANGES, or COMMENT)."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/reviews",
            headers=get_github_headers(token),
            json={"event": event, "body": body},
            timeout=15,
        )
        _raise_for_github_status(resp)
        data = resp.json()

    return {
        "id": data.get("id"),
        "state": data.get("state", ""),
        "pr_number": pr_number,
        "repo": repo,
    }


async def _execute_github_pr_comment(
    chat_id: int,
    repo: str,
    pr_number: int,
    body: str,
) -> dict:
    """Add a comment to a PR's issue thread."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{repo}/issues/{pr_number}/comments",
            headers=get_github_headers(token),
            json={"body": body},
            timeout=15,
        )
        _raise_for_github_status(resp)
        data = resp.json()

    return {
        "id": data.get("id"),
        "url": data.get("html_url", ""),
        "pr_number": pr_number,
        "repo": repo,
    }


async def _execute_github_pr_merge(
    chat_id: int,
    repo: str,
    pr_number: int,
    merge_method: str = "squash",
) -> dict:
    """Merge a PR. Caller (Claude) must have confirmed with the user before calling."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/merge",
            headers=get_github_headers(token),
            json={"merge_method": merge_method},
            timeout=15,
        )
        if resp.status_code == 422:
            raise RuntimeError("Can't merge — there are conflicts or CI is failing.")
        _raise_for_github_status(resp)
        data = resp.json()

    return {
        "merged": data.get("merged", False),
        "sha": data.get("sha", ""),
        "message": data.get("message", ""),
        "pr_number": pr_number,
        "repo": repo,
    }


async def _execute_github_pr_close(
    chat_id: int,
    repo: str,
    pr_number: int,
) -> dict:
    """Close a PR without merging. Caller (Claude) must have confirmed with the user."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}",
            headers=get_github_headers(token),
            json={"state": "closed"},
            timeout=15,
        )
        _raise_for_github_status(resp)
        data = resp.json()

    return {
        "number": data.get("number"),
        "state": data.get("state", ""),
        "url": data.get("html_url", ""),
        "repo": repo,
    }


async def _execute_github_pr_request_reviewers(
    chat_id: int,
    repo: str,
    pr_number: int,
    reviewers: list[str],
) -> dict:
    """Request reviews from a list of GitHub logins."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API_BASE}/repos/{repo}/pulls/{pr_number}/requested_reviewers",
            headers=get_github_headers(token),
            json={"reviewers": reviewers},
            timeout=15,
        )
        if resp.status_code == 404:
            raise RuntimeError("Couldn't add reviewer — check they're a repo collaborator.")
        _raise_for_github_status(resp)
        data = resp.json()

    requested = [r.get("login", "") for r in data.get("requested_reviewers", [])]
    return {
        "pr_number": pr_number,
        "repo": repo,
        "requested_reviewers": requested,
    }


async def _execute_github_pr_set_labels(
    chat_id: int,
    repo: str,
    pr_number: int,
    add: list[str] = None,
    remove: list[str] = None,
) -> dict:
    """Add and/or remove labels on a PR. 404 on remove is silently ignored."""
    token, username = await _get_github_username_and_token(chat_id)
    repo = await _resolve_repo(token, username, repo)

    added: list[str] = []
    removed: list[str] = []

    async with httpx.AsyncClient() as client:
        if add:
            resp = await client.post(
                f"{GITHUB_API_BASE}/repos/{repo}/issues/{pr_number}/labels",
                headers=get_github_headers(token),
                json={"labels": add},
                timeout=15,
            )
            _raise_for_github_status(resp)
            added = add[:]

        for label in (remove or []):
            resp = await client.delete(
                f"{GITHUB_API_BASE}/repos/{repo}/issues/{pr_number}/labels/{quote(label, safe='')}",
                headers=get_github_headers(token),
                timeout=15,
            )
            if resp.status_code == 404:
                continue  # Label wasn't on the PR — not an error
            _raise_for_github_status(resp)
            removed.append(label)

    return {
        "pr_number": pr_number,
        "repo": repo,
        "added": added,
        "removed": removed,
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def dispatch_github_tool(chat_id: int, tool_name: str, tool_input: dict) -> str:
    """
    Route a GitHub tool call to the appropriate execution function.
    Returns a JSON string. Wraps all errors as {"error": "..."}.
    """
    logger.info("GitHub tool call: %s input=%s", tool_name, tool_input)
    try:
        if tool_name == "github_my_prs":
            result = await _execute_github_my_prs(
                chat_id,
                repo=tool_input.get("repo"),
                limit=tool_input.get("limit", 20),
            )
        elif tool_name == "github_pr_detail":
            result = await _execute_github_pr_detail(
                chat_id,
                repo=tool_input["repo"],
                pr_number=tool_input["pr_number"],
            )
        elif tool_name == "github_pr_review_requested":
            result = await _execute_github_pr_review_requested(
                chat_id,
                limit=tool_input.get("limit", 10),
            )
        elif tool_name == "github_my_issues":
            result = await _execute_github_my_issues(
                chat_id,
                repo=tool_input.get("repo"),
                assignee=tool_input.get("assignee"),
                role=tool_input.get("role", "assigned"),
                label=tool_input.get("label"),
                limit=tool_input.get("limit", 20),
            )
        elif tool_name == "github_search_user":
            result = await _execute_github_search_user(
                chat_id,
                name=tool_input["name"],
                org=tool_input.get("org"),
            )
        elif tool_name == "github_issue_detail":
            result = await _execute_github_issue_detail(
                chat_id,
                repo=tool_input["repo"],
                issue_number=tool_input["issue_number"],
            )
        elif tool_name == "github_repo_list":
            result = await _execute_github_repo_list(
                chat_id,
                limit=tool_input.get("limit", 30),
            )
        elif tool_name == "github_repo_labels":
            result = await _execute_github_repo_labels(
                chat_id,
                repo=tool_input["repo"],
            )
        elif tool_name == "github_recent_activity":
            result = await _execute_github_recent_activity(
                chat_id,
                days=tool_input.get("days", 1),
                repo=tool_input.get("repo"),
            )
        elif tool_name == "github_create_pr":
            result = await _execute_github_create_pr(
                chat_id,
                repo=tool_input["repo"],
                title=tool_input.get("title", ""),
                head=tool_input.get("head", ""),
                base=tool_input.get("base", "main"),
                body=tool_input.get("body", ""),
                draft=tool_input.get("draft", False),
            )
        elif tool_name == "github_pr_submit_review":
            result = await _execute_github_pr_submit_review(
                chat_id,
                repo=tool_input["repo"],
                pr_number=tool_input["pr_number"],
                event=tool_input["event"],
                body=tool_input.get("body", ""),
            )
        elif tool_name == "github_pr_comment":
            result = await _execute_github_pr_comment(
                chat_id,
                repo=tool_input["repo"],
                pr_number=tool_input["pr_number"],
                body=tool_input["body"],
            )
        elif tool_name == "github_pr_merge":
            result = await _execute_github_pr_merge(
                chat_id,
                repo=tool_input["repo"],
                pr_number=tool_input["pr_number"],
                merge_method=tool_input.get("merge_method", "squash"),
            )
        elif tool_name == "github_pr_close":
            result = await _execute_github_pr_close(
                chat_id,
                repo=tool_input["repo"],
                pr_number=tool_input["pr_number"],
            )
        elif tool_name == "github_pr_request_reviewers":
            result = await _execute_github_pr_request_reviewers(
                chat_id,
                repo=tool_input["repo"],
                pr_number=tool_input["pr_number"],
                reviewers=tool_input["reviewers"],
            )
        elif tool_name == "github_pr_set_labels":
            result = await _execute_github_pr_set_labels(
                chat_id,
                repo=tool_input["repo"],
                pr_number=tool_input["pr_number"],
                add=tool_input.get("add"),
                remove=tool_input.get("remove"),
            )
        else:
            result = {"error": f"Unknown GitHub tool: {tool_name}"}

        logger.info("GitHub tool %s result: %s items returned", tool_name, _result_size_hint(result))
        return json.dumps(result)

    except RuntimeError as exc:
        logger.warning("GitHub tool %s runtime error: %s", tool_name, exc)
        return json.dumps({"error": str(exc)})
    except httpx.TimeoutException:
        logger.error("GitHub tool %s timed out", tool_name)
        return json.dumps({"error": "GitHub API request timed out. Please try again."})
    except httpx.HTTPStatusError as exc:
        logger.error("GitHub tool %s HTTP error %s: %s", tool_name, exc.response.status_code, exc)
        return json.dumps({"error": f"GitHub API error: {exc.response.status_code}"})
    except Exception as exc:
        logger.exception("GitHub tool %s unexpected error: %s", tool_name, exc)
        return json.dumps({"error": f"Unexpected error: {str(exc)}"})


def _result_size_hint(result: dict) -> str:
    """Return a brief string summarising the size of a tool result for logging."""
    if not isinstance(result, dict):
        return "?"
    for key in ("authored", "issues", "prs", "repos", "labels", "merged_prs"):
        if key in result and isinstance(result[key], list):
            return f"{len(result[key])} {key}"
    return str(list(result.keys()))
