import sys
import os
import pytest
from unittest.mock import patch

# Project root is one level up from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def mock_auth():
    async def _fake_auth(chat_id):
        return ("ghp_faketoken", "testuser")

    with patch("tools.github_tools._get_github_username_and_token", side_effect=_fake_auth):
        yield


@pytest.fixture
def mock_resolve_repo():
    async def _fake_resolve(token, username, repo_hint):
        return repo_hint

    with patch("tools.github_tools._resolve_repo", side_effect=_fake_resolve):
        yield
