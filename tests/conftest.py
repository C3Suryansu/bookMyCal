import sys
import os
import pytest
from unittest.mock import patch

# Add the calendar-agent directory to sys.path so test imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def mock_auth():
    """Patch _get_github_username_and_token to return a fixed (token, username) pair."""
    async def _fake_auth(chat_id):
        return ("ghp_faketoken", "testuser")

    with patch("github_tools._get_github_username_and_token", side_effect=_fake_auth):
        yield


@pytest.fixture
def mock_resolve_repo():
    """Patch _resolve_repo to return its repo_hint unchanged (already owner/repo format)."""
    async def _fake_resolve(token, username, repo_hint):
        return repo_hint

    with patch("github_tools._resolve_repo", side_effect=_fake_resolve):
        yield
