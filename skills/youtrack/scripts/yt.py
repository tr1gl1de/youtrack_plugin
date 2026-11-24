#!/usr/bin/env python3
"""yt — small YouTrack REST API client for Claude Code (stdlib only).

Configuration (each key resolved independently, first match wins):
  1. process environment
  2. .env in the current git repository root (or the nearest parent with a .env)
  3. ~/.config/youtrack/.env

Keys:
  YOUTRACK_URL      e.g. https://example.youtrack.cloud  (required)
  YOUTRACK_TOKEN    permanent token, perm:...            (required)
  YOUTRACK_PROJECT  default project short name, e.g. KIN (optional)

The token is never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KEYS = ("YOUTRACK_URL", "YOUTRACK_TOKEN", "YOUTRACK_PROJECT")

ISSUE_FIELDS = (
    "idReadable,summary,description,created,updated,resolved,"
    "reporter(login,name),project(shortName,name),"
    "customFields(name,value(name,login,presentation,text,minutes)),"
    "tags(name),links(direction,linkType(name,sourceToTarget,targetToSource),issues(idReadable,summary))"
)
ISSUE_LIST_FIELDS = "idReadable,summary,customFields(name,value(name,login,presentation))"
COMMENT_FIELDS = "id,text,created,author(login,name)"
ARTICLE_FIELDS = (
    "idReadable,summary,content,updated,project(shortName),"
    "parentArticle(idReadable,summary),childArticles(idReadable,summary)"
)
WORKITEM_FIELDS = "id,date,duration(minutes,presentation),text,author(login,name),type(name)"


# ---------------------------------------------------------------- config

def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
    return out


def _repo_env_file() -> Path | None:
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if root and (Path(root) / ".env").is_file():
            return Path(root) / ".env"
    except (OSError, subprocess.CalledProcessError):
        pass
    for d in [Path.cwd(), *Path.cwd().parents]:
        if (d / ".env").is_file():
            return d / ".env"
    return None


def load_config() -> tuple[dict[str, str], dict[str, str]]:
    """Return (config, source-per-key)."""
    sources: list[tuple[str, dict[str, str]]] = [("env", dict(os.environ))]
    repo_env = _repo_env_file()
    if repo_env:
        sources.append((str(repo_env), _parse_env_file(repo_env)))
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    sources.append((str(xdg / "youtrack" / ".env"), _parse_env_file(xdg / "youtrack" / ".env")))

    cfg: dict[str, str] = {}
    src: dict[str, str] = {}
    for key in KEYS:
        for name, values in sources:
            if values.get(key):
                cfg[key], src[key] = values[key], name
                break
    if "YOUTRACK_URL" in cfg:
        cfg["YOUTRACK_URL"] = cfg["YOUTRACK_URL"].rstrip("/")
        if cfg["YOUTRACK_URL"].endswith("/api"):
            cfg["YOUTRACK_URL"] = cfg["YOUTRACK_URL"][:-4]
    return cfg, src


def die(msg: str, code: int = 1) -> None:
    print(f"yt: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- http

class Client:
    def __init__(self, cfg: dict[str, str]):
        for key in ("YOUTRACK_URL", "YOUTRACK_TOKEN"):
            if not cfg.get(key):
                die(f"{key} is not set. Put it in the environment, the repo .env, "
                    "or ~/.config/youtrack/.env (run `yt.py config` to see what is resolved).", 2)
        self.base = cfg["YOUTRACK_URL"] + "/api"
        self.token = cfg["YOUTRACK_TOKEN"]

    def request(self, method: str, path: str, params: dict | None = None, body=None):
        url = self.base + "/" + path.lstrip("/")
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None})
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "youtrack-claude-plugin",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                j = json.loads(detail)
                detail = j.get("error_description") or j.get("error") or detail
            except ValueError:
                pass
            die(f"HTTP {e.code} {method} {path}: {detail}", 3)
        except urllib.error.URLError as e:
            die(f"cannot reach {self.base}: {e.reason}", 3)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode("utf-8", "replace")

    def get(self, path, **params):
        return self.request("GET", path, params)

    def post(self, path, body, **params):
        return self.request("POST", path, params, body)

    def paged(self, path, top: int, **params):
        """Fetch up to `top` items (top<=0 means all)."""
        out, skip, page = [], 0, 100
        while True:
            n = page if top <= 0 else min(page, top - len(out))
            if n <= 0:
                break
            chunk = self.get(path, **params, **{"$top": n, "$skip": skip}) or []
            out.extend(chunk)
            if len(chunk) < n:
                break
            skip += n
        return out


# ---------------------------------------------------------------- helpers

def field_value(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, list):
        return ", ".join(field_value(x) for x in v) or "—"
    if isinstance(v, dict):
        for k in ("presentation", "name", "login", "text", "minutes"):
            if v.get(k) not in (None, ""):
                return str(v[k])
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def ts(ms) -> str:
    if not ms:
        return "—"
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def emit(args, data, render):
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        render(data)


def read_text_arg(value: str | None) -> str | None:
    """`-` reads stdin, `@path` reads a file, anything else is literal."""
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


def parse_duration(text: str) -> int:
    """'1h30m', '90m', '2h', '1d' (=8h), '45' (minutes) -> minutes."""
    t = text.strip().lower().replace(" ", "")
    if t.isdigit():
        return int(t)
    m = re.fullmatch(r"(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?", t)
    if not m or not any(m.groups()):
        die(f"bad duration '{text}', use e.g. 1h30m, 45m, 2h")
    w, d, h, mi = (int(x or 0) for x in m.groups())
    return ((w * 5 + d) * 8 + h) * 60 + mi


# ---------------------------------------------------------------- commands

def cmd_config(args, cfg, src):
    for key in KEYS:
        if key in cfg:
            shown = "<set>" if key == "YOUTRACK_TOKEN" else cfg[key]
            print(f"{key} = {shown}   (from {src[key]})")
        else:
            print(f"{key} = <not set>")


def cmd_whoami(args, c):
    emit(args, c.get("users/me", fields="login,name,email"),
         lambda d: print(f"{d.get('login')} ({d.get('name')})"))


def cmd_projects(args, c):
    data = c.get("admin/projects", fields="shortName,name,archived", **{"$top": 500})
    emit(args, data, lambda d: [print(f"{p['shortName']:<10} {p['name']}{'  [archived]' if p.get('archived') else ''}") for p in d])


def cmd_fields(args, c, cfg):
    project = args.project or cfg.get("YOUTRACK_PROJECT") or die("project required (or set YOUTRACK_PROJECT)")
    projects = c.get("admin/projects", fields="id,shortName", query=project, **{"$top": 50})
    pid = next((p["id"] for p in projects if p["shortName"].lower() == project.lower()), None)
    if not pid:
        die(f"project {project} not found")
    data = c.get(f"admin/projects/{pid}/customFields",
                 fields="field(name,fieldType(id)),canBeEmpty,bundle(values(name,archived))", **{"$top": 200})

    def render(d):
        for f in d:
            name = f["field"]["name"]
            ftype = f["field"].get("fieldType", {}).get("id", "")
            vals = [v["name"] for v in (f.get("bundle") or {}).get("values", []) if not v.get("archived")]
            print(f"{name}  [{ftype}]{'' if f.get('canBeEmpty') else ' required'}")
            if vals:
                print("    " + " | ".join(vals))
    emit(args, data, render)


def render_issue(d):
    print(f"{d['idReadable']}: {d['summary']}")
    print(f"Project: {d['project']['shortName']}   Reporter: {field_value(d.get('reporter'))}   "
          f"Created: {ts(d.get('created'))}   Updated: {ts(d.get('updated'))}"
          + (f"   Resolved: {ts(d['resolved'])}" if d.get("resolved") else ""))
    for f in d.get("customFields", []):
        print(f"  {f['name']}: {field_value(f.get('value'))}")
    if d.get("tags"):
        print("Tags: " + ", ".join(t["name"] for t in d["tags"]))
    for link in d.get("links", []):
        if not link.get("issues"):
            continue
        lt = link["linkType"]
        label = lt.get("targetToSource") if link["direction"] == "INWARD" else lt.get("sourceToTarget")
        label = label or lt["name"]
        for i in link["issues"]:
            print(f"  ↳ {label}: {i['idReadable']} {i['summary']}")
    print("\n" + (d.get("description") or "(no description)"))


def cmd_issue_get(args, c):
    d = c.get(f"issues/{args.id}", fields=ISSUE_FIELDS)
    if args.comments:
        d["comments"] = c.paged(f"issues/{args.id}/comments", 0, fields=COMMENT_FIELDS)

    def render(x):
        render_issue(x)
        for cm in x.get("comments", []):
            print(f"\n--- {field_value(cm.get('author'))} @ {ts(cm.get('created'))} [comment {cm['id']}]")
            print(cm.get("text") or "")
    emit(args, d, render)


def cmd_issue_search(args, c, cfg):
    query = args.query
    if args.project or (cfg.get("YOUTRACK_PROJECT") and "project:" not in query.lower() and not args.all_projects):
        query = f"project: {args.project or cfg['YOUTRACK_PROJECT']} {query}".strip()
    data = c.paged("issues", args.top, query=query, fields=ISSUE_LIST_FIELDS)

    def render(d):
        if not d:
            print(f"(no issues for query: {query})")
        for i in d:
            fs = {f["name"]: field_value(f.get("value")) for f in i.get("customFields", [])}
            extra = "  ".join(f"{k}={fs[k]}" for k in ("State", "Priority", "Assignee", "Type") if k in fs)
            print(f"{i['idReadable']:<10} {i['summary']}" + (f"   [{extra}]" if extra else ""))
    emit(args, data, render)


def run_command(c, issue_ids: list[str], command: str, comment: str | None = None):
    body = {"query": command, "issues": [{"idReadable": i} for i in issue_ids]}
    if comment:
        body["comment"] = comment
    return c.post("commands", body, fields="query")


def cmd_issue_create(args, c, cfg):
    project = args.project or cfg.get("YOUTRACK_PROJECT") or die("project required (or set YOUTRACK_PROJECT)")
    projects = c.get("admin/projects", fields="id,shortName", query=project, **{"$top": 50})
    pid = next((p["id"] for p in projects if p["shortName"].lower() == project.lower()), None)
    if not pid:
        die(f"project {project} not found")
    body = {"project": {"id": pid}, "summary": args.summary,
            "description": read_text_arg(args.description) or ""}
    d = c.post("issues", body, fields="idReadable,summary")
    if args.command:
        run_command(c, [d["idReadable"]], args.command)
    emit(args, d, lambda x: print(f"created {x['idReadable']}: {x['summary']}  {cfg['YOUTRACK_URL']}/issue/{x['idReadable']}"))


def cmd_issue_update(args, c, cfg):
    body = {}
    if args.summary is not None:
        body["summary"] = args.summary
    if args.description is not None:
        body["description"] = read_text_arg(args.description)
    if not body:
        die("nothing to update: pass --summary and/or --description")
    d = c.post(f"issues/{args.id}", body, fields="idReadable,summary")
    emit(args, d, lambda x: print(f"updated {x['idReadable']}: {x['summary']}"))


def cmd_issue_command(args, c):
    run_command(c, args.ids, args.command, read_text_arg(args.comment))
    print(f"applied '{args.command}' to {', '.join(args.ids)}")


def cmd_comment_list(args, c):
    data = c.paged(f"issues/{args.id}/comments", args.top, fields=COMMENT_FIELDS)

    def render(d):
        for cm in d:
            print(f"--- {field_value(cm.get('author'))} @ {ts(cm.get('created'))} [comment {cm['id']}]")
            print((cm.get("text") or "") + "\n")
    emit(args, data, render)


def cmd_comment_add(args, c):
    text = read_text_arg(args.text)
    if not text or not text.strip():
        die("empty comment")
    d = c.post(f"issues/{args.id}/comments", {"text": text}, fields="id")
    emit(args, d, lambda x: print(f"comment {x['id']} added to {args.id}"))


def cmd_article_get(args, c):
    emit(args, c.get(f"articles/{args.id}", fields=ARTICLE_FIELDS), lambda d: (
        print(f"{d['idReadable']}: {d['summary']}   (updated {ts(d.get('updated'))})"),
        d.get("parentArticle") and print(f"Parent: {d['parentArticle']['idReadable']} {d['parentArticle']['summary']}"),
        [print(f"  child: {ch['idReadable']} {ch['summary']}") for ch in d.get("childArticles", [])],
        print("\n" + (d.get("content") or "")),
    ))


def cmd_article_search(args, c, cfg):
    query = args.query
    project = args.project or cfg.get("YOUTRACK_PROJECT")
    if project and "project:" not in query.lower() and not args.all_projects:
        query = f"project: {project} {query}".strip()
    data = c.paged("articles", args.top, query=query, fields="idReadable,summary,parentArticle(idReadable)")
    emit(args, data, lambda d: [print(f"{a['idReadable']:<12} {a['summary']}"
                                      + (f"   (in {a['parentArticle']['idReadable']})" if a.get("parentArticle") else ""))
                                for a in d] or print("(no articles)"))


def cmd_article_update(args, c):
    body = {}
    if args.summary is not None:
        body["summary"] = args.summary
    if args.content is not None:
        body["content"] = read_text_arg(args.content)
    if not body:
        die("nothing to update: pass --summary and/or --content")
    d = c.post(f"articles/{args.id}", body, fields="idReadable,summary")
    emit(args, d, lambda x: print(f"updated {x['idReadable']}: {x['summary']}"))


def cmd_time_list(args, c):
    data = c.paged(f"issues/{args.id}/timeTracking/workItems", 0, fields=WORKITEM_FIELDS)

    def render(d):
        total = 0
        for w in d:
            mins = (w.get("duration") or {}).get("minutes") or 0
            total += mins
            print(f"{ts(w.get('date'))[:10]}  {(w.get('duration') or {}).get('presentation', mins):>8}  "
                  f"{field_value(w.get('author'))}  {field_value(w.get('type')) if w.get('type') else ''}  {w.get('text') or ''}")
        print(f"total: {total // 60}h {total % 60}m")
    emit(args, data, render)


def cmd_time_add(args, c):
    import time
    body = {"duration": {"minutes": parse_duration(args.duration)},
            "date": int(time.time() * 1000), "text": args.text or ""}
    if args.type:
        body["type"] = {"name": args.type}
    d = c.post(f"issues/{args.id}/timeTracking/workItems", body, fields=WORKITEM_FIELDS)
    emit(args, d, lambda x: print(f"logged {x['duration']['presentation']} on {args.id}"))


def cmd_api(args, c):
    params = dict(p.split("=", 1) for p in args.param)
    body = json.loads(read_text_arg(args.data)) if args.data else None
    print(json.dumps(c.request(args.method.upper(), args.path, params, body), ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="yt", description="YouTrack REST client for Claude Code")
    p.add_argument("--json", action="store_true", help="print raw JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("config", help="show resolved configuration (token hidden)")
    sub.add_parser("whoami", help="current user")
    sub.add_parser("projects", help="list projects")
    f = sub.add_parser("fields", help="custom fields and allowed values of a project")
    f.add_argument("project", nargs="?")

    issue = sub.add_parser("issue").add_subparsers(dest="sub", required=True)
    g = issue.add_parser("get"); g.add_argument("id"); g.add_argument("--comments", "-c", action="store_true")
    s = issue.add_parser("search", help="YouTrack query, e.g. 'for: me #Unresolved'")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--project", "-p"); s.add_argument("--all-projects", "-A", action="store_true")
    s.add_argument("--top", "-n", type=int, default=50)
    cr = issue.add_parser("create")
    cr.add_argument("--project", "-p"); cr.add_argument("--summary", "-s", required=True)
    cr.add_argument("--description", "-d", help="text, '-' for stdin, '@file'")
    cr.add_argument("--command", help="command applied after creation, e.g. 'Type Bug Priority Major for me'")
    up = issue.add_parser("update"); up.add_argument("id")
    up.add_argument("--summary", "-s"); up.add_argument("--description", "-d", help="text, '-' for stdin, '@file'")
    cm = issue.add_parser("command", help="apply a YouTrack command, e.g. 'State In Progress'")
    cm.add_argument("command"); cm.add_argument("ids", nargs="+")
    cm.add_argument("--comment", help="comment to add together with the command")

    comment = sub.add_parser("comment").add_subparsers(dest="sub", required=True)
    cl = comment.add_parser("list"); cl.add_argument("id"); cl.add_argument("--top", "-n", type=int, default=0)
    ca = comment.add_parser("add"); ca.add_argument("id"); ca.add_argument("text", help="text, '-' for stdin, '@file'")

    article = sub.add_parser("article").add_subparsers(dest="sub", required=True)
    ag = article.add_parser("get"); ag.add_argument("id")
    asr = article.add_parser("search"); asr.add_argument("query", nargs="?", default="")
    asr.add_argument("--project", "-p"); asr.add_argument("--all-projects", "-A", action="store_true")
    asr.add_argument("--top", "-n", type=int, default=50)
    au = article.add_parser("update"); au.add_argument("id")
    au.add_argument("--summary", "-s"); au.add_argument("--content", help="text, '-' for stdin, '@file'")

    tt = sub.add_parser("time", help="time tracking work items").add_subparsers(dest="sub", required=True)
    tl = tt.add_parser("list"); tl.add_argument("id")
    ta = tt.add_parser("add"); ta.add_argument("id"); ta.add_argument("duration", help="e.g. 1h30m, 45m")
    ta.add_argument("--text", "-t"); ta.add_argument("--type")

    api = sub.add_parser("api", help="raw call: yt api GET issues/KIN-1 -P fields=summary")
    api.add_argument("method"); api.add_argument("path")
    api.add_argument("--param", "-P", action="append", default=[], help="key=value query param")
    api.add_argument("--data", "-D", help="JSON body, '-' for stdin, '@file'")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg, src = load_config()
    if args.cmd == "config":
        return cmd_config(args, cfg, src)
    c = Client(cfg)
    key = (args.cmd, getattr(args, "sub", None))
    table = {
        ("whoami", None): lambda: cmd_whoami(args, c),
        ("projects", None): lambda: cmd_projects(args, c),
        ("fields", None): lambda: cmd_fields(args, c, cfg),
        ("issue", "get"): lambda: cmd_issue_get(args, c),
        ("issue", "search"): lambda: cmd_issue_search(args, c, cfg),
        ("issue", "create"): lambda: cmd_issue_create(args, c, cfg),
        ("issue", "update"): lambda: cmd_issue_update(args, c, cfg),
        ("issue", "command"): lambda: cmd_issue_command(args, c),
        ("comment", "list"): lambda: cmd_comment_list(args, c),
        ("comment", "add"): lambda: cmd_comment_add(args, c),
        ("article", "get"): lambda: cmd_article_get(args, c),
        ("article", "search"): lambda: cmd_article_search(args, c, cfg),
        ("article", "update"): lambda: cmd_article_update(args, c),
        ("time", "list"): lambda: cmd_time_list(args, c),
        ("time", "add"): lambda: cmd_time_add(args, c),
        ("api", None): lambda: cmd_api(args, c),
    }
    table[key]()


if __name__ == "__main__":
    main()
