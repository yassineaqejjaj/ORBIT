"""Project e-mails grouped per thread (docs/AI_CONTEXT_ENGINEERING.md §F3).

The Microsoft 365 and Google Workspace presets can watch a dedicated mailbox folder or Gmail label: each
conversation becomes **one document** (``external_id`` = conversation / thread id) re-versioned when a
reply arrives. Messages are sorted by date, quoted replies and signatures are stripped (« Le … a écrit : »,
« On … wrote: », ``>`` lines, Outlook « De : / Envoyé : » blocks, « -----Original Message----- »), and
attachments are listed by name (their content is not downloaded).
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

#: A line that starts the quoted part of a reply: everything from it on is dropped.
_QUOTE_HEADERS = (
    re.compile(r"^\s*(?:le|on)\s.{3,200}?(?:a écrit|a ecrit|wrote)\s*:\s*$", re.IGNORECASE),
    re.compile(
        r"^\s*-{2,}\s*(?:original message|message d'origine|message transféré|forwarded message)", re.I
    ),
    re.compile(r"^\s*_{10,}\s*$"),
    re.compile(r"^\s*(?:de|from)\s*:\s*.+$", re.IGNORECASE),  # Outlook block, confirmed by the next lines
)
_OUTLOOK_NEXT = re.compile(r"^\s*(?:envoyé|sent|date|à|to|objet|subject|cc)\s*:", re.IGNORECASE)
_SIGNATURE = re.compile(r"^\s*(?:--|—)\s*$")
_BLANKS = re.compile(r"\n{3,}")


@dataclass(slots=True)
class MailMessage:
    sender: str
    body: str
    sent_at: datetime | None = None
    to: str = ""
    attachments: list[str] = field(default_factory=list)
    message_id: str = ""


def html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(?:script|style)[^>]*>.*?</(?:script|style)>", "", value)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", text)
    text = re.sub(r"(?i)<blockquote[^>]*>", "\n> ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html_lib.unescape(text).replace("\xa0", " ")


def strip_quoted(text: str) -> str:
    """The new part of a reply: quoted history, forwarded headers and signature removed."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    for index, line in enumerate(lines):
        if _SIGNATURE.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        header = next((p for p in _QUOTE_HEADERS if p.match(line)), None)
        if header is not None:
            if header is _QUOTE_HEADERS[3]:  # « De : … » only when followed by « Envoyé : / À : … »
                following = [n for n in lines[index + 1 : index + 4] if n.strip()]
                if not following or not _OUTLOOK_NEXT.match(following[0]):
                    kept.append(line)
                    continue
            break
        kept.append(line.rstrip())
    return _BLANKS.sub("\n\n", "\n".join(kept)).strip()


def parse_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None


def _display(sender: str) -> str:
    """« Claire Dubois <claire@exemple.test> » → « Claire Dubois »."""
    name = re.sub(r"\s*<[^>]+>\s*$", "", sender).strip().strip('"')
    return name or sender.strip()


def thread_markdown(subject: str, messages: Sequence[MailMessage]) -> str:
    ordered = sorted(messages, key=lambda m: (m.sent_at is None, m.sent_at or datetime.min))
    participants = list(dict.fromkeys(_display(m.sender) for m in ordered if m.sender))
    lines = [f"# {subject}", ""]
    if participants:
        lines.append(f"Participants : {', '.join(participants)}")
    lines += [f"Messages : {len(ordered)}", ""]
    for message in ordered:
        stamp = message.sent_at.strftime("%Y-%m-%d %H:%M") if message.sent_at else "date inconnue"
        lines += [f"## {stamp} — {_display(message.sender) or 'expéditeur inconnu'}", ""]
        body = strip_quoted(message.body)
        lines += [body or "(message sans texte nouveau)", ""]
        if message.attachments:
            lines += [f"Pièces jointes : {', '.join(message.attachments)}", ""]
    return "\n".join(lines).rstrip() + "\n"


def thread_metadata(kind: str, messages: Sequence[MailMessage]) -> dict[str, Any]:
    return {
        "kind": kind,
        "message_count": len(messages),
        "participants": list(dict.fromkeys(_display(m.sender) for m in messages if m.sender)),
        "attachments": [a for m in messages for a in m.attachments][:100],
    }


def latest(messages: Iterable[MailMessage]) -> datetime | None:
    dates = [m.sent_at for m in messages if m.sent_at is not None]
    return max(dates) if dates else None


# --- Gmail (workspace-mcp get_gmail_thread_content text) ---------------------------------------------------

_GMAIL_THREAD_ID = re.compile(r"Thread ID\s*:\s*([A-Za-z0-9_-]{6,})")
_GMAIL_MESSAGE = re.compile(r"^=== Message \d+ ===\s*$", re.MULTILINE)
_GMAIL_HEADER = re.compile(
    r"^(From|Date|To|Cc|Subject|Reply-To|Message-ID|In-Reply-To|References)\s*:\s*(.*)$"
)
_GMAIL_ATTACHMENT = re.compile(r"^\s*\d+\.\s+(.+?)\s+\(([^,()]+),\s*([\d.]+ KB)\)")


def gmail_thread_ids(text: str) -> list[str]:
    """Thread ids of a ``search_gmail_messages`` result (one per thread, in order)."""
    return list(dict.fromkeys(_GMAIL_THREAD_ID.findall(text)))


def parse_gmail_thread(text: str) -> tuple[str, list[MailMessage]]:
    """``(subject, messages)`` of a ``get_gmail_thread_content`` result."""
    subject_match = re.search(r"(?m)^Subject:\s*(.+)$", text)
    subject = subject_match.group(1).strip() if subject_match else "(sans objet)"
    messages: list[MailMessage] = []
    for block in _GMAIL_MESSAGE.split(text)[1:]:
        headers: dict[str, str] = {}
        lines = block.strip("\n").split("\n")
        index = 0
        while index < len(lines) and lines[index].strip():
            header = _GMAIL_HEADER.match(lines[index])
            if header:
                headers[header.group(1).lower()] = header.group(2).strip()
            index += 1
        body_lines: list[str] = []
        attachments: list[str] = []
        in_attachments = False
        for line in lines[index:]:
            if line.strip() == "--- ATTACHMENTS ---":
                in_attachments = True
                continue
            if in_attachments:
                match = _GMAIL_ATTACHMENT.match(line)
                if match:
                    attachments.append(f"{match.group(1)} ({match.group(3).replace('KB', 'Ko')})")
                continue
            body_lines.append(line)
        messages.append(
            MailMessage(
                sender=headers.get("from", ""),
                body="\n".join(body_lines).strip(),
                sent_at=parse_date(headers.get("date")),
                to=headers.get("to", ""),
                attachments=attachments,
                message_id=headers.get("message-id", ""),
            )
        )
    return subject, messages


# --- Microsoft Graph messages (ms-365-mcp-server list-mail-folder-messages) -------------------------------


def graph_message(item: dict[str, Any]) -> MailMessage:
    body = item.get("uniqueBody") if isinstance(item.get("uniqueBody"), dict) else item.get("body")
    body = body if isinstance(body, dict) else {}
    content = str(body.get("content") or item.get("bodyPreview") or "")
    if str(body.get("contentType", "")).lower() == "html":
        content = html_to_text(content)
    sender = item.get("from") if isinstance(item.get("from"), dict) else {}
    address = sender.get("emailAddress") if isinstance(sender.get("emailAddress"), dict) else {}
    attachments = [
        f"{a.get('name')}" + (f" ({round(int(a['size']) / 1024)} Ko)" if a.get("size") else "")
        for a in item.get("attachments") or []
        if isinstance(a, dict) and a.get("name") and not a.get("isInline")
    ]
    return MailMessage(
        sender=str(address.get("name") or address.get("address") or ""),
        body=content,
        sent_at=parse_date(item.get("receivedDateTime") or item.get("sentDateTime")),
        attachments=attachments,
        message_id=str(item.get("id") or ""),
    )


__all__ = [
    "MailMessage",
    "gmail_thread_ids",
    "graph_message",
    "html_to_text",
    "latest",
    "parse_date",
    "parse_gmail_thread",
    "strip_quoted",
    "thread_markdown",
    "thread_metadata",
]
