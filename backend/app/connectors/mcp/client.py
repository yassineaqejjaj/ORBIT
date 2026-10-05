"""MCP client used by the MCP connectors and the MarkItDown extractor (docs/FEATURES.md F6).

One :class:`McpClient` owns one MCP session, opened over **stdio** (a server process started from an
allowlisted preset command) or **streamable HTTP** (remote server, ``Authorization: Bearer``).

Isolation and safety:

* the stdio process receives **only** a minimal allowlisted environment (``PATH``, a throw-away
  ``HOME``/``TMPDIR``, neutral ``USER``/``SHELL``/``LANG``…) plus the variables built from the
  connector's decrypted secrets and non-secret config — never the API process environment;
* every call has a timeout; on timeout the session task is cancelled, which makes the SDK close stdin
  and kill the server process tree;
* the server's stderr is captured to a temporary file and attached (tail, secrets redacted) to errors.

The session lives in a dedicated asyncio task (the SDK's anyio task groups must be entered and exited
by the same task): callers talk to it through a queue, so the client can be used from an async
generator (``changes()``) without cancel-scope leaks.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.connectors.base import ConnectorError

#: Test hook: maps a target onto another one (e.g. a preset command onto a fake server script) or onto
#: an in-process ``MCPServer`` instance. Returning ``None`` keeps the target.
target_override: Callable[[Any], Any] | None = None

STDERR_TAIL = 1500
REDACTED = "••••"
#: (pattern, keep the first group as prefix) — token-looking strings removed from logs and errors.
_TOKEN_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{6,}"), True),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;]{4,}"), True),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{4,}"), False),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})"), False),
    (re.compile(r"\blin_(?:api|oauth)_[A-Za-z0-9]{6,}"), False),
)
#: Minimal environment of a stdio server (plus HOME/TMPDIR pointing to a temporary directory).
_NEUTRAL_ENV = {
    "USER": "orbit",
    "LOGNAME": "orbit",
    "SHELL": "/bin/sh",
    "TERM": "dumb",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "NO_COLOR": "1",
    "PYTHONUNBUFFERED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "NODE_NO_WARNINGS": "1",
    "npm_config_update_notifier": "false",
}


@dataclass(slots=True)
class StdioTarget:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class HttpTarget:
    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ToolInfo:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


class McpCallError(ConnectorError):
    """A tool returned ``isError`` or the MCP call failed (French, redacted message)."""


def redact(text: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    """Remove secret values and token-looking strings from ``text``."""
    for secret in sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    for pattern, keep_prefix in _TOKEN_PATTERNS:
        text = pattern.sub((lambda m: m.group(1) + REDACTED) if keep_prefix else REDACTED, text)
    return text


def _looks_like_auth_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "401",
            "403",
            "unauthori",
            "invalid_auth",
            "invalid_token",
            "authentication failed",
            "not_authed",
            "forbidden",
            "bad credentials",
            "invalid api key",
        )
    )


def minimal_env(home: str, extra: dict[str, str]) -> dict[str, str]:
    """Environment of a stdio server: allowlist + ``extra`` (secrets/config). Nothing else is inherited."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": home,
        "TMPDIR": home,
        "XDG_CACHE_HOME": os.path.join(home, ".cache"),
        "XDG_CONFIG_HOME": os.path.join(home, ".config"),
        **_NEUTRAL_ENV,
    }
    env.update({k: v for k, v in extra.items() if v is not None})
    return env


def resolve_command(command: str, fallback: list[str] | None = None) -> list[str] | None:
    """``[binary, *prefix_args]`` for an installed binary, else the pinned ``fallback`` (uvx/npx)."""
    if os.path.isabs(command) and os.access(command, os.X_OK):
        return [command]
    found = shutil.which(command)
    if found:
        return [found]
    if fallback and shutil.which(fallback[0]):
        return [shutil.which(fallback[0]) or fallback[0], *fallback[1:]]
    return None


class McpClient:
    """One MCP session (see module docstring). Use ``async with McpClient(...) as client``."""

    def __init__(
        self,
        target: StdioTarget | HttpTarget | Any,
        *,
        timeout: float = 60.0,
        secrets: list[str] | None = None,
        label: str = "serveur MCP",
    ) -> None:
        self.target = target
        self.timeout = timeout
        self.secrets = [s for s in (secrets or []) if s]
        self.label = label
        self.server_name: str | None = None
        self.server_version: str | None = None
        self.calls = 0
        self._queue: asyncio.Queue[tuple[Callable[[Any], Awaitable[Any]], asyncio.Future[Any]] | None] = (
            asyncio.Queue()
        )
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] | None = None
        self._home: str | None = None
        self._stderr_path: str | None = None
        self._broken: str | None = None

    # --- lifecycle -------------------------------------------------------------------------------------

    async def __aenter__(self) -> McpClient:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _server_arg(self, stderr: Any) -> Any:
        from mcp.client.stdio import StdioServerParameters, stdio_client

        target = self.target
        if target_override is not None:
            replaced = target_override(target)
            if replaced is not None:
                target = replaced
        if isinstance(target, StdioTarget):
            assert self._home is not None
            params = StdioServerParameters(
                command=target.command,
                args=list(target.args),
                env=minimal_env(self._home, target.env),
                cwd=self._home,
            )
            return stdio_client(params, errlog=stderr)
        if isinstance(target, HttpTarget):
            import httpx2
            from mcp.client.streamable_http import streamable_http_client

            client = httpx2.AsyncClient(
                headers={"User-Agent": "ORBIT-MCP/1.0", **target.headers},
                timeout=httpx2.Timeout(self.timeout, read=max(self.timeout, 60.0)),
                follow_redirects=False,
            )
            return streamable_http_client(target.url, http_client=client)
        return target  # in-process server (tests) or transport

    async def start(self) -> None:
        self._home = tempfile.mkdtemp(prefix="orbit-mcp-")
        os.chmod(self._home, 0o700)
        self._stderr_path = os.path.join(self._home, ".stderr.log")
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(self._run(), name=f"mcp-session:{self.label}")
        try:
            await asyncio.wait_for(asyncio.shield(self._ready), self.timeout)
        except TimeoutError as exc:
            await self._kill()
            raise McpCallError(
                f"Le {self.label} n'a pas répondu dans le délai ({self.timeout:.0f} s) au démarrage"
                + self._stderr_suffix()
            ) from exc
        except ConnectorError:
            await self._kill()
            raise

    async def _run(self) -> None:
        from mcp import Client

        assert self._ready is not None and self._stderr_path is not None
        try:
            with open(self._stderr_path, "w", encoding="utf-8", errors="replace") as stderr:  # noqa: ASYNC230
                async with Client(self._server_arg(stderr), read_timeout_seconds=self.timeout) as client:
                    info = client.server_info
                    if info is not None:
                        self.server_name = info.name
                        self.server_version = info.version or None
                    if not self._ready.done():
                        self._ready.set_result(None)
                    while True:
                        item = await self._queue.get()
                        if item is None:
                            break
                        func, future = item
                        if future.done():
                            continue
                        try:
                            result = await func(client)
                        except asyncio.CancelledError:
                            if not future.done():
                                future.cancel()
                            raise
                        except Exception as exc:
                            if not future.done():
                                future.set_exception(exc)
                        else:
                            if not future.done():
                                future.set_result(result)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            message = self._describe_failure(exc)
            self._broken = message
            if not self._ready.done():
                self._ready.set_exception(McpCallError(message, auth=_looks_like_auth_error(message)))
        finally:
            self._broken = self._broken or "Session MCP fermée"
            self._fail_pending(self._broken)

    def _fail_pending(self, message: str) -> None:
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if item is not None and not item[1].done():
                item[1].set_exception(McpCallError(message))

    def _describe_failure(self, exc: BaseException) -> str:
        leaf = exc
        while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
            leaf = leaf.exceptions[0]
        if isinstance(leaf, FileNotFoundError):
            return f"Commande du {self.label} introuvable sur ce serveur ORBIT (outil non installé)"
        detail = redact(str(leaf) or type(leaf).__name__, self.secrets)[:300]
        return f"Le {self.label} s'est arrêté ou a refusé la connexion ({detail})" + self._stderr_suffix()

    def stderr_tail(self) -> str:
        if not self._stderr_path or not os.path.exists(self._stderr_path):
            return ""
        try:
            with open(self._stderr_path, encoding="utf-8", errors="replace") as handle:
                handle.seek(max(0, os.path.getsize(self._stderr_path) - 20_000))
                text = handle.read()
        except OSError:
            return ""
        lines = [line for line in text.splitlines() if line.strip()]
        return redact("\n".join(lines[-12:]), self.secrets)[-STDERR_TAIL:]

    def _stderr_suffix(self) -> str:
        tail = self.stderr_tail()
        return f" — journal du serveur : {tail}" if tail else ""

    async def _kill(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(task, 15)
        elif task is not None:
            with contextlib.suppress(BaseException):
                task.result()

    async def aclose(self) -> None:
        task = self._task
        if task is not None and not task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(asyncio.shield(task), 15)
            except BaseException:
                await self._kill()
        self._task = None
        if self._home:
            shutil.rmtree(self._home, ignore_errors=True)
            self._home = None

    # --- calls -----------------------------------------------------------------------------------------

    async def _submit(self, func: Callable[[Any], Awaitable[Any]], what: str) -> Any:
        if self._broken or self._task is None or self._task.done():
            raise McpCallError(self._broken or "Session MCP fermée")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        await self._queue.put((func, future))
        self.calls += 1
        try:
            return await asyncio.wait_for(asyncio.shield(future), self.timeout)
        except TimeoutError as exc:
            self._broken = f"Délai dépassé ({self.timeout:.0f} s) pour {what} : processus MCP arrêté"
            await self._kill()
            raise McpCallError(self._broken + self._stderr_suffix()) from exc
        except ConnectorError:
            raise
        except Exception as exc:
            message = redact(str(exc) or type(exc).__name__, self.secrets)[:500]
            raise McpCallError(
                f"Erreur MCP pendant {what} : {message}", auth=_looks_like_auth_error(message)
            ) from exc

    async def list_tools(self) -> list[ToolInfo]:
        async def run(client: Any) -> list[ToolInfo]:
            tools: list[ToolInfo] = []
            cursor: str | None = None
            for _ in range(20):
                page = await client.list_tools(cursor=cursor)
                tools.extend(
                    ToolInfo(t.name, (t.description or "")[:500], dict(t.input_schema or {}))
                    for t in page.tools
                )
                cursor = page.next_cursor
                if not cursor:
                    break
            return tools

        return await self._submit(run, "la liste des outils")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Raw ``CallToolResult``; raises :class:`McpCallError` when the tool reports an error."""

        async def run(client: Any) -> Any:
            return await client.call_tool(name, arguments)

        result = await self._submit(run, f"l'outil « {name} »")
        if getattr(result, "is_error", False):
            from app.connectors.mcp.mapper import result_text

            message = redact(result_text(result) or "erreur sans détail", self.secrets)[:500]
            raise McpCallError(
                f"L'outil « {name} » a renvoyé une erreur : {message}", auth=_looks_like_auth_error(message)
            )
        return result

    async def list_resources(self) -> list[Any]:
        async def run(client: Any) -> list[Any]:
            items: list[Any] = []
            cursor: str | None = None
            for _ in range(20):
                page = await client.list_resources(cursor=cursor)
                items.extend(page.resources)
                cursor = page.next_cursor
                if not cursor:
                    break
            return items

        return await self._submit(run, "la liste des ressources")

    async def read_resource(self, uri: str) -> Any:
        async def run(client: Any) -> Any:
            return await client.read_resource(uri)

        return await self._submit(run, f"la lecture de « {uri[:80]} »")
