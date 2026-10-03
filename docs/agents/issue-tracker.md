# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Repository: `010m010/PMSChartAnalyzer` (https://github.com/010m010/PMSChartAnalyzer). Prefer the authenticated GitHub connector when its tools are available. The repository owner `010m010` and repository administration access were verified during setup. Use the `gh` CLI as a fallback when it is available and authenticated.

## GitHub connector

- Read the repository with `github_get_repo`, and resolve the signed-in account with `github_get_user_login`.
- Find or read tickets with `github_search_issues` / `github_fetch_issue`.
- Create, edit, comment, label, or close tickets with the corresponding GitHub connector tools. Pass `010m010/PMSChartAnalyzer` explicitly as the repository selector.
- Verify the current authentication and repository permissions before the first write of a session. Follow the user's requested operation; setup itself does not create tickets or comments.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. For multi-line bodies in PowerShell, write UTF-8 text to a file and pass `--body-file <path>`.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

The Git remote `origin` points to this repository. For CLI operations, pass `--repo 010m010/PMSChartAnalyzer` explicitly to every `gh issue` / `gh pr` command. Use `repos/010m010/PMSChartAnalyzer/...` for `gh api` endpoints.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue with the connector, or the CLI when using the fallback.

## When a skill says "fetch the relevant ticket"

Fetch the issue and its comments with the connector, or run `gh issue view <number> --comments --repo 010m010/PMSChartAnalyzer`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.

## GitHub access

Check the connector's signed-in account and repository permissions. If the connector is unavailable, check `gh --version` and `gh auth status` before CLI operations. When neither authenticated method is available, keep proposed writes local and request the missing authentication. Public reads can use the GitHub API or browser. Keep the selected tracker as GitHub Issues.
