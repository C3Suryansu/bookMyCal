# GitHub PR Write Actions — Design Spec
Date: 2026-04-06

## Overview

Add 7 write-action tools to the Telegram calendar-agent's GitHub integration, enabling the user to create PRs, submit reviews, comment, merge, close, request reviewers, and manage labels — all conversationally via Telegram.

---

## Architecture

No new files. All changes are additive to existing modules:

- **`github_tools.py`** — 7 new tool schemas in `GITHUB_TOOLS`, 7 new `_execute_*` functions, 7 new branches in `dispatch_github_tool`. An internal `_list_branches` helper (not a Claude-facing tool) is used by `github_create_pr` when the head branch is not specified.
- **`prompts.py`** — new `PR WRITE ACTIONS` section appended to the system prompt, covering conversation flows, confirmation gates, and branch resolution guidance.

Existing read tools (`github_my_prs`, `github_pr_detail`, etc.) are unchanged.

---

## Tools

### `github_create_pr`
**Inputs:** `repo` (owner/repo), `head` (branch), `base` (branch, default `main`), `title`, `body` (optional), `draft` (bool, default false)

**Behavior:** If `head` is not provided, call `_list_branches` to retrieve branch names and ask the user which one. Claude gathers title conversationally if not given. Confirms before creating: "Creating PR '[title]' from [head] → [base]. Ready to open? (yes/no)" — executes on yes.

**API:** `POST /repos/{repo}/pulls`

---

### `github_pr_submit_review`
**Inputs:** `repo`, `pr_number`, `event` (APPROVE | REQUEST_CHANGES | COMMENT), `body` (required for REQUEST_CHANGES, optional otherwise)

**Behavior:** Executes immediately. No confirmation gate — reviews are low-risk (can be dismissed). Body is required when requesting changes; Claude asks for it if not provided.

**API:** `POST /repos/{repo}/pulls/{pr_number}/reviews`

---

### `github_pr_comment`
**Inputs:** `repo`, `pr_number`, `body`

**Behavior:** Adds a comment to the PR's issue thread. Executes immediately.

**API:** `POST /repos/{repo}/issues/{pr_number}/comments`

---

### `github_pr_merge`
**Inputs:** `repo`, `pr_number`, `merge_method` (merge | squash | rebase, default squash)

**Behavior:** **Confirmation gate.** Claude always asks: "Merge `{repo}#{pr_number}` via {method}? (yes/no)" before calling this tool. Replies with the merge SHA on success.

**API:** `PUT /repos/{repo}/pulls/{pr_number}/merge`

---

### `github_pr_close`
**Inputs:** `repo`, `pr_number`

**Behavior:** **Confirmation gate.** Claude always asks: "Close `{repo}#{pr_number}` without merging? (yes/no)" before calling this tool.

**API:** `PATCH /repos/{repo}/pulls/{pr_number}` with `{"state": "closed"}`

---

### `github_pr_request_reviewers`
**Inputs:** `repo`, `pr_number`, `reviewers` (list of GitHub logins)

**Behavior:** Executes immediately. If the user gives display names instead of logins, Claude calls `github_search_user` first (existing tool). Confirms after: "Requested review from @alice and @bob."

**API:** `POST /repos/{repo}/pulls/{pr_number}/requested_reviewers`

---

### `github_pr_set_labels`
**Inputs:** `repo`, `pr_number`, `add` (list of label names, optional), `remove` (list of label names, optional)

**Behavior:** Executes immediately. If unsure of exact label names, Claude calls `github_repo_labels` first. Confirms after: "Added 'needs-review', removed 'WIP'."

**API:**
- Add: `POST /repos/{repo}/issues/{pr_number}/labels`
- Remove: `DELETE /repos/{repo}/issues/{pr_number}/labels/{name}` (one call per label)

---

## Confirmation Gates

Only merge and close require confirmation. All other write actions execute immediately because they are either low-risk or easily undone.

| Action | Gate? | Reason |
|---|---|---|
| Create PR | Yes (conversational gather) | Needs title/branch info — gathers before confirming |
| Submit review | No | Can be dismissed; expected to execute on request |
| Comment | No | Additive, non-destructive |
| Merge | **Yes** | Irreversible, affects main branch |
| Close | **Yes** | Irreversible without re-opening manually |
| Request reviewers | No | Additive, easy to remove |
| Set labels | No | Easily undone |

---

## Error Handling

All execution functions follow the existing pattern: errors surface as `{"error": "..."}` and Claude narrates the issue to the user. Specific cases:

- **422 on merge** (not mergeable / conflicts): "Can't merge — there are conflicts or CI is failing."
- **422 on create PR** (branch already has an open PR): "A PR for this branch already exists."
- **404 on reviewer** (user not found / not a collaborator): "Couldn't add reviewer — check they're a repo collaborator."
- **403** (insufficient token scopes): Prompt user to run `/github` and re-auth with `repo` scope.

---

## System Prompt Additions

New section `PR WRITE ACTIONS` added to `prompts.py`, covering:
- When to call each tool
- Confirmation gate wording for merge and close
- Branch resolution flow for create PR
- Reviewer resolution flow (use `github_search_user` for display names)
- Label resolution flow (use `github_repo_labels` if unsure of exact name)

---

## Token scope requirement

All write actions require `repo` scope on the GitHub PAT. This is already listed as required during `/github` onboarding. No changes needed to onboarding.
