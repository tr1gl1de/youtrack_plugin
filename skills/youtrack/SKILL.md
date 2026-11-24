---
name: youtrack
description: Work with YouTrack issues and Knowledge Base articles over the REST API — read and search issues, create/update them, change state/assignee/fields via commands, comment, log time, and read or update articles. Use whenever the user mentions a YouTrack issue ID (e.g. KIN-12, ABC-345), a youtrack.cloud link, "задача"/"тикет"/"issue" in YouTrack, the project's Knowledge Base/articles, or asks to pick up, report on, or update a task.
---

# YouTrack

All calls go through the bundled CLI `scripts/yt.py` (Python 3 stdlib, no install). Run it from the user's
current repository so it can find that repo's `.env`:

```bash
python3 <this-skill-dir>/scripts/yt.py <command> ...
```

`<this-skill-dir>` is the base directory shown when this skill loads. Add `--json` (before the command) for
raw JSON when you need fields the text output omits.

## Configuration

Each key is resolved independently: process env → `.env` in the git repo root → `~/.config/youtrack/.env`.

| Key | Required | Example |
|---|---|---|
| `YOUTRACK_URL` | yes | `https://example.youtrack.cloud` |
| `YOUTRACK_TOKEN` | yes | `perm:...` (Profile → Account Security → Tokens) |
| `YOUTRACK_PROJECT` | no | default project short name for search/create, e.g. `KIN` |

Run `yt.py config` to see what was resolved and from where. **Never print, echo, `cat`, or log the token or the
`.env` file contents**, and never pass the token on a command line yourself — the script reads it.
If something is missing, tell the user which key and where to put it; do not ask them to paste the token into the chat.

## Commands

```bash
yt.py whoami | projects | config
yt.py fields KIN                               # custom fields + allowed values (State, Priority, Type...)

yt.py issue get KIN-12 --comments              # full issue: fields, links, description, comments
yt.py issue search "#Unresolved for: me"       # YouTrack query language; scoped to YOUTRACK_PROJECT
yt.py issue search "State: {In Progress}" -p KIN -n 20
yt.py issue search "..." -A                    # all projects, ignore default project
yt.py issue create -s "Summary" -d @desc.md --command "Type Task Priority Normal"
yt.py issue update KIN-12 -s "New summary" -d - <<'EOF'
new description (markdown)
EOF
yt.py issue command "State In Progress" KIN-12 # any YouTrack command: fields, assignee, tags, links
yt.py issue command "for me" KIN-12 KIN-13
yt.py issue command "State Fixed" KIN-12 --comment "Done in PR #4"

yt.py comment list KIN-12
yt.py comment add KIN-12 "text"                # or '-' for stdin, '@file'

yt.py article get KIN-A-1                      # content + parent + child articles
yt.py article search "runner" -p KIN
yt.py article update KIN-A-5 --content @article.md

yt.py time list KIN-12
yt.py time add KIN-12 1h30m -t "implementation" [--type Development]

yt.py api GET issues/KIN-12/activities -P fields=... -P categories=CustomFieldCategory   # escape hatch
```

Commands use YouTrack command syntax: `State In Progress`, `Assignee john`, `for me`, `Priority Critical`,
`tag needs-review`, `relates to KIN-3`, `subtask of KIN-1`. Values with spaces work as written; field names and
values must exist in the project — check with `yt.py fields <PROJECT>` before guessing. Projects name their
workflow field differently (`State`, `Stage`, `Status`...): the one marked `[state[1]]` in `fields` output is it,
so use e.g. `Stage Develop` rather than assuming `State In Progress`.

## How to work

**Reading is free.** Fetch issues, comments, articles and search results whenever they help. When the user
names an issue, start with `issue get <ID> --comments`, then follow links/articles it references
(`article get` for `/articles/<ID>` URLs).

**Writing is visible to the whole team.** Create issues, post comments, change state/assignee, log time,
or edit articles only when the user asked for that action (or the repository's instructions define it as part
of the workflow). Before writing:
- Show the exact text/command you are about to send when it was not dictated by the user.
- Never change an article's content wholesale without fetching the current version first and preserving what
  you were not asked to change; `article update --content` replaces the full body.
- Do not log time (`time add`) unless asked; report the duration you would log instead.
- There is deliberately no delete command. If deletion is requested, use `api DELETE ...` only after explicit
  confirmation of exactly what will be deleted.

**Picking up a task** (typical flow when the user says "take KIN-12"):
1. `issue get KIN-12 --comments`, read linked issues/articles needed for context.
2. Summarize the requirement and acceptance criteria; ask about genuine gaps.
3. If the repo has its own git/branch conventions (CLAUDE.md), follow them; otherwise name the branch
   `feature/KIN-12-<short-slug>`.
4. When asked, move the workflow field to its "in progress" value (look it up with `fields`; e.g.
   `issue command "Stage Develop" KIN-12`) and later comment with the
   result — what changed, PR link, how it was verified.

Formatting: descriptions, comments and articles are Markdown. Issue IDs in text (`KIN-3`) auto-link in YouTrack.

## Errors

- `HTTP 401` — token invalid/expired. `HTTP 403` — token lacks permission for that project/action.
- `HTTP 404` — wrong ID, or the issue/article is not visible to this user.
- `HTTP 400` on a command — unknown field or value; run `yt.py fields <PROJECT>`.
