# tests/test_github_write_tools.py
import pytest
import respx
from httpx import Response

from tools.github_tools import _list_branches

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


from tools.github_tools import _execute_github_create_pr


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


# ---------------------------------------------------------------------------
# Task 4: github_pr_submit_review
# ---------------------------------------------------------------------------

from tools.github_tools import _execute_github_pr_submit_review


@pytest.mark.asyncio
async def test_submit_review_approve(mock_auth, mock_resolve_repo):
    """github_pr_submit_review returns state=APPROVED on approve."""
    with respx.mock:
        respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/5/reviews").mock(
            return_value=Response(200, json={
                "id": 99,
                "state": "APPROVED",
                "body": "",
            })
        )
        result = await _execute_github_pr_submit_review(
            chat_id=1,
            repo="owner/repo",
            pr_number=5,
            event="APPROVE",
        )

    assert result["state"] == "APPROVED"
    assert result["id"] == 99
    assert result["pr_number"] == 5


@pytest.mark.asyncio
async def test_submit_review_request_changes(mock_auth, mock_resolve_repo):
    """github_pr_submit_review passes body correctly for REQUEST_CHANGES."""
    with respx.mock:
        route = respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/5/reviews").mock(
            return_value=Response(200, json={
                "id": 100,
                "state": "CHANGES_REQUESTED",
                "body": "Please fix the tests",
            })
        )
        result = await _execute_github_pr_submit_review(
            chat_id=1,
            repo="owner/repo",
            pr_number=5,
            event="REQUEST_CHANGES",
            body="Please fix the tests",
        )

    assert result["state"] == "CHANGES_REQUESTED"
    import json as _json
    sent_body = route.calls[0].request.content
    assert _json.loads(sent_body)["body"] == "Please fix the tests"


# ---------------------------------------------------------------------------
# Task 5: github_pr_comment
# ---------------------------------------------------------------------------

from tools.github_tools import _execute_github_pr_comment


@pytest.mark.asyncio
async def test_pr_comment_success(mock_auth, mock_resolve_repo):
    """github_pr_comment returns comment id and url on success."""
    with respx.mock:
        respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/issues/7/comments").mock(
            return_value=Response(201, json={
                "id": 55,
                "html_url": "https://github.com/owner/repo/pull/7#issuecomment-55",
            })
        )
        result = await _execute_github_pr_comment(
            chat_id=1,
            repo="owner/repo",
            pr_number=7,
            body="LGTM!",
        )

    assert result["id"] == 55
    assert "issuecomment-55" in result["url"]
    assert result["pr_number"] == 7


@pytest.mark.asyncio
async def test_pr_comment_sends_body(mock_auth, mock_resolve_repo):
    """github_pr_comment sends the body text in the POST payload."""
    with respx.mock:
        route = respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/issues/7/comments").mock(
            return_value=Response(201, json={"id": 56, "html_url": "https://github.com/owner/repo/pull/7#issuecomment-56"})
        )
        await _execute_github_pr_comment(
            chat_id=1,
            repo="owner/repo",
            pr_number=7,
            body="Please rebase this branch.",
        )

    import json as _json
    sent = _json.loads(route.calls[0].request.content)
    assert sent["body"] == "Please rebase this branch."


# ---------------------------------------------------------------------------
# Task 6: github_pr_merge
# ---------------------------------------------------------------------------

from tools.github_tools import _execute_github_pr_merge


@pytest.mark.asyncio
async def test_pr_merge_success(mock_auth, mock_resolve_repo):
    """github_pr_merge returns merged=True and sha on success."""
    with respx.mock:
        respx.put(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/10/merge").mock(
            return_value=Response(200, json={
                "merged": True,
                "sha": "abc123def456",
                "message": "Pull Request successfully merged",
            })
        )
        result = await _execute_github_pr_merge(
            chat_id=1,
            repo="owner/repo",
            pr_number=10,
            merge_method="squash",
        )

    assert result["merged"] is True
    assert result["sha"] == "abc123def456"
    assert result["pr_number"] == 10


@pytest.mark.asyncio
async def test_pr_merge_422_conflicts(mock_auth, mock_resolve_repo):
    """github_pr_merge raises RuntimeError on 422 (conflicts/CI failing)."""
    with respx.mock:
        respx.put(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/10/merge").mock(
            return_value=Response(422, json={"message": "Merge conflict"})
        )
        with pytest.raises(RuntimeError, match="conflicts"):
            await _execute_github_pr_merge(
                chat_id=1,
                repo="owner/repo",
                pr_number=10,
            )


@pytest.mark.asyncio
async def test_pr_merge_default_method_is_squash(mock_auth, mock_resolve_repo):
    """github_pr_merge defaults to squash merge method."""
    with respx.mock:
        route = respx.put(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/10/merge").mock(
            return_value=Response(200, json={"merged": True, "sha": "abc", "message": "ok"})
        )
        await _execute_github_pr_merge(chat_id=1, repo="owner/repo", pr_number=10)

    import json as _json
    sent = _json.loads(route.calls[0].request.content)
    assert sent["merge_method"] == "squash"


# ---------------------------------------------------------------------------
# Task 7: github_pr_close
# ---------------------------------------------------------------------------

from tools.github_tools import _execute_github_pr_close


@pytest.mark.asyncio
async def test_pr_close_success(mock_auth, mock_resolve_repo):
    """github_pr_close returns state=closed on success."""
    with respx.mock:
        respx.patch(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/12").mock(
            return_value=Response(200, json={
                "number": 12,
                "state": "closed",
                "html_url": "https://github.com/owner/repo/pull/12",
            })
        )
        result = await _execute_github_pr_close(
            chat_id=1,
            repo="owner/repo",
            pr_number=12,
        )

    assert result["state"] == "closed"
    assert result["number"] == 12
    assert result["repo"] == "owner/repo"


@pytest.mark.asyncio
async def test_pr_close_sends_state_closed(mock_auth, mock_resolve_repo):
    """github_pr_close sends state=closed in the PATCH payload."""
    with respx.mock:
        route = respx.patch(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/12").mock(
            return_value=Response(200, json={"number": 12, "state": "closed", "html_url": ""})
        )
        await _execute_github_pr_close(chat_id=1, repo="owner/repo", pr_number=12)

    import json as _json
    sent = _json.loads(route.calls[0].request.content)
    assert sent["state"] == "closed"


# ---------------------------------------------------------------------------
# Task 8: github_pr_request_reviewers
# ---------------------------------------------------------------------------

from tools.github_tools import _execute_github_pr_request_reviewers


@pytest.mark.asyncio
async def test_request_reviewers_success(mock_auth, mock_resolve_repo):
    """github_pr_request_reviewers returns the list of requested reviewers."""
    with respx.mock:
        respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/15/requested_reviewers").mock(
            return_value=Response(201, json={
                "number": 15,
                "requested_reviewers": [
                    {"login": "alice"},
                    {"login": "bob"},
                ],
            })
        )
        result = await _execute_github_pr_request_reviewers(
            chat_id=1,
            repo="owner/repo",
            pr_number=15,
            reviewers=["alice", "bob"],
        )

    assert result["requested_reviewers"] == ["alice", "bob"]
    assert result["pr_number"] == 15


@pytest.mark.asyncio
async def test_request_reviewers_404_not_collaborator(mock_auth, mock_resolve_repo):
    """github_pr_request_reviewers raises RuntimeError on 404 (not a collaborator)."""
    with respx.mock:
        respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/15/requested_reviewers").mock(
            return_value=Response(404, json={"message": "Not Found"})
        )
        with pytest.raises(RuntimeError, match="collaborator"):
            await _execute_github_pr_request_reviewers(
                chat_id=1,
                repo="owner/repo",
                pr_number=15,
                reviewers=["notacollab"],
            )


# ---------------------------------------------------------------------------
# Task 9: github_pr_set_labels
# ---------------------------------------------------------------------------

from tools.github_tools import _execute_github_pr_set_labels


@pytest.mark.asyncio
async def test_set_labels_add_only(mock_auth, mock_resolve_repo):
    """github_pr_set_labels adds labels and returns added list."""
    with respx.mock:
        respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/issues/20/labels").mock(
            return_value=Response(200, json=[{"name": "needs-review"}, {"name": "P1"}])
        )
        result = await _execute_github_pr_set_labels(
            chat_id=1,
            repo="owner/repo",
            pr_number=20,
            add=["needs-review", "P1"],
        )

    assert result["added"] == ["needs-review", "P1"]
    assert result["removed"] == []


@pytest.mark.asyncio
async def test_set_labels_remove_only(mock_auth, mock_resolve_repo):
    """github_pr_set_labels removes labels and returns removed list."""
    with respx.mock:
        respx.delete(f"{GITHUB_API_BASE}/repos/owner/repo/issues/20/labels/WIP").mock(
            return_value=Response(200, json=[])
        )
        result = await _execute_github_pr_set_labels(
            chat_id=1,
            repo="owner/repo",
            pr_number=20,
            remove=["WIP"],
        )

    assert result["removed"] == ["WIP"]
    assert result["added"] == []


@pytest.mark.asyncio
async def test_set_labels_add_and_remove(mock_auth, mock_resolve_repo):
    """github_pr_set_labels handles add and remove in a single call."""
    with respx.mock:
        respx.post(f"{GITHUB_API_BASE}/repos/owner/repo/issues/20/labels").mock(
            return_value=Response(200, json=[{"name": "ready"}])
        )
        respx.delete(f"{GITHUB_API_BASE}/repos/owner/repo/issues/20/labels/WIP").mock(
            return_value=Response(200, json=[])
        )
        result = await _execute_github_pr_set_labels(
            chat_id=1,
            repo="owner/repo",
            pr_number=20,
            add=["ready"],
            remove=["WIP"],
        )

    assert result["added"] == ["ready"]
    assert result["removed"] == ["WIP"]


@pytest.mark.asyncio
async def test_set_labels_remove_404_silently_ignored(mock_auth, mock_resolve_repo):
    """github_pr_set_labels silently ignores 404 when removing a label not on the PR."""
    with respx.mock:
        respx.delete(f"{GITHUB_API_BASE}/repos/owner/repo/issues/20/labels/ghost-label").mock(
            return_value=Response(404, json={"message": "Label does not exist"})
        )
        result = await _execute_github_pr_set_labels(
            chat_id=1,
            repo="owner/repo",
            pr_number=20,
            remove=["ghost-label"],
        )

    assert result["removed"] == []
    assert "error" not in result
