"""
Pure utility functions for the GitHub integration.
No API calls — just data transformation helpers.
"""

from datetime import datetime, timezone


def age_in_days(iso_str: str) -> int:
    """Return the number of days since an ISO 8601 date string."""
    if not iso_str:
        return 0
    # Handle both offset-aware and offset-naive strings
    try:
        # Try with timezone info first (e.g. "2024-01-15T10:30:00Z")
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(0, delta.days)
    except (ValueError, TypeError):
        return 0


def get_github_headers(token: str) -> dict:
    """Return the headers dict required for authenticated GitHub API calls."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def compress_pr(raw: dict, username: str) -> dict:
    """
    Extract only the needed fields from a raw GitHub PR API response.

    Handles both the search API format (where repo info comes from repository_url
    and pull_request sub-key) and the pulls API format.
    """
    # Determine repo name
    repo = ""
    repo_url = raw.get("repository_url", "")
    if repo_url:
        # "https://api.github.com/repos/owner/repo" -> "owner/repo"
        parts = repo_url.rstrip("/").split("/")
        if len(parts) >= 2:
            repo = f"{parts[-2]}/{parts[-1]}"
    if not repo:
        base = raw.get("base", {})
        repo_data = base.get("repo", {})
        repo = repo_data.get("full_name", "")

    # Determine days open
    created_at = raw.get("created_at", "")
    days_open = age_in_days(created_at)

    # Review decision — may be present in a "review_decision" key if enriched
    review_decision = raw.get("review_decision") or raw.get("reviewDecision") or ""

    # Unresolved comments — from reviews list if available, else raw count
    unresolved_comments = raw.get("_unresolved_comments", 0)

    # CI status — enriched externally; raw search results won't have this
    ci_status = raw.get("_ci_status", "unknown")

    # Labels
    labels = [lbl.get("name", "") for lbl in raw.get("labels", [])]

    # Mergeable
    mergeable = raw.get("mergeable")

    return {
        "number": raw.get("number"),
        "title": raw.get("title", ""),
        "repo": repo,
        "url": raw.get("html_url", ""),
        "draft": raw.get("draft", False),
        "days_open": days_open,
        "review_decision": review_decision,
        "unresolved_comments": unresolved_comments,
        "ci_status": ci_status,
        "labels": labels,
        "mergeable": mergeable,
    }


def compress_issue(raw: dict) -> dict:
    """
    Extract only the needed fields from a raw GitHub issue API response.
    Works for both search results and direct issues API responses.
    """
    # Determine repo name
    repo = ""
    repo_url = raw.get("repository_url", "")
    if repo_url:
        parts = repo_url.rstrip("/").split("/")
        if len(parts) >= 2:
            repo = f"{parts[-2]}/{parts[-1]}"

    created_at = raw.get("created_at", "")
    days_open = age_in_days(created_at)

    labels = [lbl.get("name", "") for lbl in raw.get("labels", [])]
    assignees = [a.get("login", "") for a in raw.get("assignees", [])]

    body = raw.get("body") or ""
    body_preview = body[:300]

    return {
        "number": raw.get("number"),
        "title": raw.get("title", ""),
        "repo": repo,
        "url": raw.get("html_url", ""),
        "state": raw.get("state", ""),
        "days_open": days_open,
        "labels": labels,
        "assignees": assignees,
        "body": body_preview,
    }


def compress_review_threads(reviews: list, comments: list) -> list:
    """
    Group inline PR comments by reviewer and return a structured list.

    reviews: list of review objects from /pulls/{pr}/reviews
    comments: list of comment objects from /pulls/{pr}/comments

    Returns a list of:
      {
        reviewer: str,
        resolved: bool,
        comments: [{body, file, line}]
      }
    """
    # Build a map of reviewer -> review state
    reviewer_state: dict[str, str] = {}
    for review in reviews:
        login = (review.get("user") or {}).get("login", "")
        state = review.get("state", "")
        if login:
            # Later reviews override earlier ones
            reviewer_state[login] = state

    # Group inline comments by reviewer
    reviewer_comments: dict[str, list] = {}
    for comment in comments:
        login = (comment.get("user") or {}).get("login", "")
        if not login:
            continue
        body = comment.get("body", "")
        file_path = comment.get("path", "")
        line = comment.get("line") or comment.get("original_line") or 0
        entry = {"body": body, "file": file_path, "line": line}
        reviewer_comments.setdefault(login, []).append(entry)

    # Merge reviewers from both sets
    all_reviewers = set(reviewer_state.keys()) | set(reviewer_comments.keys())

    threads = []
    for reviewer in sorted(all_reviewers):
        state = reviewer_state.get(reviewer, "")
        # A thread is considered resolved if the reviewer's last review is APPROVED
        # or DISMISSED. CHANGES_REQUESTED = unresolved.
        resolved = state in ("APPROVED", "DISMISSED")
        threads.append({
            "reviewer": reviewer,
            "resolved": resolved,
            "comments": reviewer_comments.get(reviewer, []),
        })

    return threads
