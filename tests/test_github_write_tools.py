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
