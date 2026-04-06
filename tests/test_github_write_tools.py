# calendar-agent/tests/test_github_write_tools.py
import pytest
import respx
from httpx import Response

from github_tools import _list_branches

GITHUB_API_BASE = "https://api.github.com"


@pytest.mark.asyncio
async def test_list_branches_returns_names():
    """_list_branches returns a list of branch name strings."""
    with respx.mock:
        respx.get(f"{GITHUB_API_BASE}/repos/owner/repo/branches").mock(
            return_value=Response(200, json=[
                {"name": "main"},
                {"name": "feature/add-login"},
                {"name": "fix/typo"},
            ])
        )
        result = await _list_branches("ghp_token", "owner/repo")

    assert result == ["main", "feature/add-login", "fix/typo"]


@pytest.mark.asyncio
async def test_list_branches_empty_repo():
    """_list_branches returns an empty list when the repo has no branches."""
    with respx.mock:
        respx.get(f"{GITHUB_API_BASE}/repos/owner/repo/branches").mock(
            return_value=Response(200, json=[])
        )
        result = await _list_branches("ghp_token", "owner/repo")

    assert result == []


from github_tools import _execute_github_create_pr


@pytest.mark.asyncio
async def test_create_pr_success(mock_auth, mock_resolve_repo):
    """github_create_pr returns number, title, and url on success."""
    with respx.mock:
        respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/pulls").mock(
            return_value=Response(201, json={
                "number": 42,
                "title": "Add feature X",
                "html_url": "https://github.com/owner/repo/pull/42",
                "draft": False,
            })
        )
        result = await _execute_github_create_pr(
            chat_id=1,
            repo="owner/repo",
            head="feature/add-x",
            base="main",
            title="Add feature X",
            body="Implements feature X",
            draft=False,
        )

    assert result["number"] == 42
    assert result["title"] == "Add feature X"
    assert result["url"] == "https://github.com/owner/repo/pull/42"
    assert result["head"] == "feature/add-x"
    assert result["base"] == "main"


@pytest.mark.asyncio
async def test_create_pr_422_existing_pr(mock_auth, mock_resolve_repo):
    """github_create_pr raises RuntimeError when a PR already exists for the branch."""
    with respx.mock:
        respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/pulls").mock(
            return_value=Response(422, json={"message": "Validation Failed"})
        )
        with pytest.raises(RuntimeError, match="already exists"):
            await _execute_github_create_pr(
                chat_id=1,
                repo="owner/repo",
                head="feature/add-x",
                base="main",
                title="Add feature X",
            )
