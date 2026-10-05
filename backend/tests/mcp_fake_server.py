"""Fake MCP servers for the F6 tests (no network): tools shaped like the real presets' tools.

Run as ``python tests/mcp_fake_server.py <preset> <data.json>`` (stdio) or build in-process with
:func:`build`. The data file is re-read on every call so a test can change the « remote » content
between two syncs; every call is appended to ``<data>.calls.jsonl`` (tool name + arguments).
All contents are fictitious.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError


class Remote:
    def __init__(self, data_path: str | None) -> None:
        self.path = Path(data_path) if data_path else None

    def data(self) -> dict[str, Any]:
        if self.path is None or not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def log(self, tool: str, args: dict[str, Any]) -> None:
        if self.path is None:
            return
        with open(f"{self.path}.calls.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"tool": tool, "args": args}, ensure_ascii=False) + "\n")

    def check_token(self, value: str | None) -> None:
        expected = self.data().get("token")
        if expected and value != expected:
            raise ToolError("401 Unauthorized: invalid token " + str(value))


def _after(value: str | None, since: str | None) -> bool:
    return not since or (value or "") >= since


def build(preset: str, data_path: str | None = None, *, header_token: Any = None) -> MCPServer:
    remote = Remote(data_path)
    server = MCPServer(f"fake-{preset}", version="0.0-test")

    @server.tool()
    def debug_env() -> str:
        """Environment of the server process (tests of env isolation)."""
        remote.log("debug_env", {})
        return json.dumps({"env": dict(os.environ), "cwd": os.getcwd(), "pid": os.getpid()})

    @server.tool()
    def sleep_forever(seconds: float = 3600) -> str:
        """Never answers in time (timeout tests)."""
        time.sleep(seconds)
        return "réveillé"

    if preset == "atlassian":

        @server.tool()
        def confluence_search(query: str, limit: int = 10, spaces_filter: str | None = None) -> str:
            remote.log("confluence_search", {"query": query, "limit": limit})
            remote.check_token(os.environ.get("CONFLUENCE_API_TOKEN"))
            if query == "type = page":
                return "[]"
            space = re.search(r'space = "([^"]+)"', query)
            since = re.search(r'lastmodified >= "([^"]+)"', query)
            pages = [
                p
                for p in remote.data().get("pages", [])
                if (not space or p["space"] == space.group(1))
                and _after(p["updated"][:16].replace("T", " "), since.group(1) if since else None)
            ]
            pages.sort(key=lambda p: p["updated"])
            return json.dumps(
                [
                    {
                        "id": p["id"],
                        "title": p["title"],
                        "updated": p["updated"],
                        "url": p.get("url"),
                        "space": {"key": p["space"], "name": p["space"]},
                    }
                    for p in pages[:limit]
                ]
            )

        @server.tool()
        def confluence_get_page(
            page_id: str | None = None, convert_to_markdown: bool = True, include_metadata: bool = True
        ) -> str:
            remote.log("confluence_get_page", {"page_id": page_id})
            for page in remote.data().get("pages", []):
                if page["id"] == page_id:
                    return json.dumps(
                        {
                            "metadata": {
                                "id": page_id,
                                "title": page["title"],
                                "updated": page["updated"],
                                "author": "Ana Martin",
                                "version": {"number": 3},
                                "content": {"value": page["body"], "format": "markdown"},
                            }
                        }
                    )
            return json.dumps({"error": "Page not found with the provided identifiers."})

        @server.tool()
        def jira_search(
            jql: str,
            fields: str | None = None,
            limit: int = 10,
            start_at: int = 0,
            page_token: str | None = None,
        ) -> str:
            remote.log("jira_search", {"jql": jql, "start_at": start_at})
            remote.check_token(os.environ.get("JIRA_API_TOKEN"))
            since = re.search(r'updated >= "([^"]+)"', jql)
            issues = [
                i
                for i in remote.data().get("issues", [])
                if _after(
                    i["updated"][:16].replace("-", "/").replace("T", " "), since.group(1) if since else None
                )
            ]
            issues.sort(key=lambda i: i["updated"])
            page = issues[start_at : start_at + limit]
            return json.dumps(
                {"total": len(issues), "start_at": start_at, "max_results": limit, "issues": page}
            )

        @server.tool()
        def jira_get_issue(issue_key: str) -> str:
            return json.dumps({"key": issue_key})

    elif preset == "obsidian":

        @server.tool()
        def obsidian_list_files_in_vault() -> str:
            remote.log("obsidian_list_files_in_vault", {})
            remote.check_token(os.environ.get("OBSIDIAN_API_KEY"))
            names = {n.split("/")[0] + ("/" if "/" in n else "") for n in remote.data().get("notes", {})}
            return json.dumps(sorted(names))

        @server.tool()
        def obsidian_list_files_in_dir(dirpath: str) -> str:
            remote.log("obsidian_list_files_in_dir", {"dirpath": dirpath})
            prefix = dirpath.strip("/") + "/"
            names = set()
            for name in remote.data().get("notes", {}):
                if name.startswith(prefix):
                    rest = name[len(prefix) :]
                    names.add(rest.split("/")[0] + ("/" if "/" in rest else ""))
            return json.dumps(sorted(names))

        @server.tool()
        def obsidian_get_file_contents(filepath: str) -> str:
            remote.log("obsidian_get_file_contents", {"filepath": filepath})
            return remote.data().get("notes", {}).get(filepath, "")

    elif preset == "slack":

        @server.tool()
        def conversations_history(
            channel_id: str,
            include_activity_messages: bool = False,
            cursor: str | None = None,
            limit: str | None = None,
        ) -> str:
            remote.log("conversations_history", {"channel_id": channel_id, "limit": limit, "cursor": cursor})
            rows = ["MsgID,UserID,UserName,RealName,Channel,ThreadTs,Text,Time,Cursor"]
            for m in remote.data().get("messages", {}).get(channel_id, []):
                text = m["text"].replace('"', '""')
                rows.append(
                    f'{m["ts"]},U1,{m["user"]},{m["user"]},{channel_id},{m.get("thread", "")},"{text}",{m["ts"]},'
                )
            return "\n".join(rows)

        @server.tool()
        def conversations_replies(channel_id: str, thread_ts: str, cursor: str | None = None) -> str:
            remote.log("conversations_replies", {"channel_id": channel_id, "thread_ts": thread_ts})
            rows = ["MsgID,UserID,UserName,RealName,Channel,ThreadTs,Text,Time,Cursor"]
            for r in remote.data().get("replies", {}).get(thread_ts, []):
                rows.append(
                    f'{r["ts"]},U2,{r["user"]},{r["user"]},{channel_id},{thread_ts},"{r["text"]}",{r["ts"]},'
                )
            return "\n".join(rows)

        @server.tool()
        def channels_list(channel_types: str, limit: int = 100) -> str:
            return "ID,Name,Topic\nC0001,#projet-orbit,Projet\nC0002,#support,Support"

    elif preset == "github":

        def _auth() -> None:
            token = header_token() if callable(header_token) else None
            remote.check_token(token)

        @server.tool()
        def list_issues(
            owner: str,
            repo: str,
            since: str | None = None,
            orderBy: str | None = None,
            direction: str | None = None,
            perPage: int = 30,
            after: str | None = None,
        ) -> str:
            remote.log("list_issues", {"since": since, "after": after})
            _auth()
            issues = [i for i in remote.data().get("issues", []) if _after(i["updated_at"], since)]
            return json.dumps({"issues": issues, "pageInfo": {"hasNextPage": False, "endCursor": None}})

        @server.tool()
        def issue_read(method: str, owner: str, repo: str, issue_number: int) -> str:
            remote.log("issue_read", {"method": method, "issue_number": issue_number})
            comments = remote.data().get("comments", {}).get(str(issue_number), [])
            return json.dumps(comments)

        @server.tool()
        def list_pull_requests(
            owner: str,
            repo: str,
            state: str = "open",
            sort: str = "created",
            direction: str = "desc",
            perPage: int = 30,
            page: int = 1,
        ) -> str:
            remote.log("list_pull_requests", {"page": page})
            pulls = sorted(remote.data().get("pulls", []), key=lambda p: p["updated_at"], reverse=True)
            return json.dumps(pulls[(page - 1) * perPage : page * perPage])

        @server.tool()
        def get_file_contents(owner: str, repo: str, path: str = "/") -> Any:
            from mcp.types import EmbeddedResource, TextResourceContents

            remote.log("get_file_contents", {"path": path})
            files = remote.data().get("files", {})
            if path in files:
                return [
                    EmbeddedResource(
                        type="resource",
                        resource=TextResourceContents(
                            uri=f"repo://{owner}/{repo}/contents/{path}",
                            mime_type="text/markdown",
                            text=files[path],
                        ),
                    )
                ]
            entries = [
                {"type": "file", "name": name.rsplit("/", 1)[-1], "path": name, "sha": str(abs(hash(text)))}
                for name, text in files.items()
                if name.startswith(path.strip("/") + "/")
            ]
            if not entries:
                raise ToolError("404 Not Found")
            return json.dumps(entries)

    elif preset == "ms365":

        @server.tool(name="get-drive-delta")
        def get_drive_delta(driveId: str, driveItemId: str, skiptoken: str | None = None) -> str:
            remote.log("get-drive-delta", {"driveId": driveId})
            return json.dumps({"value": remote.data().get("drive_items", [])})

        @server.tool(name="download-bytes")
        def download_bytes(target: str) -> str:
            remote.log("download-bytes", {"target": target})
            item_id = target.split("/items/")[1].split("/")[0]
            content = remote.data().get("contents", {}).get(item_id, "")
            return json.dumps(
                {
                    "contentType": "text/markdown",
                    "encoding": "base64",
                    "contentBytes": base64.b64encode(content.encode()).decode(),
                }
            )

        @server.tool(name="list-mail-messages")
        def list_mail_messages(top: int = 50) -> str:
            return json.dumps({"value": []})

        @server.tool(name="list-channel-messages")
        def list_channel_messages(teamId: str, channelId: str, top: int = 50) -> str:
            return json.dumps({"value": []})

    elif preset == "custom":

        @server.resource("note://orbit/charte")
        def charte() -> str:
            return "# Charte fictive\n\nLes décisions sont tracées dans ORBIT."

    elif preset == "markitdown":

        @server.tool()
        def convert_to_markdown(uri: str) -> str:
            path = uri.removeprefix("file://")
            size = os.path.getsize(path)
            return f"# Diapositive 1\n\nPrésentation fictive convertie ({size} octets, {Path(path).suffix})."

    elif preset == "crash":
        sys.stderr.write(
            "fatal: Authentication failed for token " + os.environ.get("SLACK_MCP_XOXP_TOKEN", "") + "\n"
        )
        sys.stderr.flush()
        sys.exit(1)

    return server


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None).run()
