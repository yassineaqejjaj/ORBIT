"""HTML extraction with BeautifulSoup: navigation/scripts removed, headings kept as Markdown.

The main content (``<main>`` / ``<article>`` / ``role="main"``) is preferred when present.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from app.ingestion.extractors import HTML, ExtractedDocument, decode_text

_DROP_TAGS = (
    "script", "style", "noscript", "template", "nav", "header", "footer", "aside", "form",
    "button", "svg", "canvas", "iframe", "object", "embed", "select", "input", "textarea", "menu",
)  # fmt: skip
_BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "blockquote", "pre", "figure", "figcaption",
    "address", "dl", "dt", "dd", "details", "summary", "caption", "body",
}  # fmt: skip
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_NOISE_CLASS = re.compile(r"(cookie|consent|breadcrumb|sidebar|menu|navbar|footer|header|share|social)", re.I)
_SPACES = re.compile(r"[ \t\r\f\v]+")


def _inline_text(node: Tag) -> str:
    return _SPACES.sub(" ", node.get_text(" ", strip=True)).strip()


class _Renderer:
    def __init__(self) -> None:
        self.blocks: list[str] = []
        self.inline: list[str] = []

    def flush(self) -> None:
        text = _SPACES.sub(" ", "".join(self.inline)).strip()
        if text:
            self.blocks.append(text)
        self.inline = []

    def render(self, node: Tag | NavigableString) -> None:
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            self.inline.append(str(node).replace("\n", " "))
            return
        name = node.name.lower() if node.name else ""
        if name in _HEADINGS:
            self.flush()
            text = _inline_text(node)
            if text:
                self.blocks.append(f"{'#' * _HEADINGS[name]} {text}")
            return
        if name == "br":
            self.inline.append("\n")
            return
        if name in {"ul", "ol"}:
            self.flush()
            items = []
            for index, item in enumerate(node.find_all("li", recursive=False), start=1):
                text = _inline_text(item)
                if text:
                    items.append(f"{index}. {text}" if name == "ol" else f"- {text}")
            if items:
                self.blocks.append("\n".join(items))
            return
        if name == "table":
            self.flush()
            rows = []
            for row in node.find_all("tr"):
                cells = [_inline_text(c).replace("|", "/") for c in row.find_all(["th", "td"])]
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                self.blocks.append("\n".join(rows))
            return
        if name == "hr":
            self.flush()
            return
        is_block = name in _BLOCK_TAGS or name == "li"
        if is_block:
            self.flush()
        for child in node.children:
            if isinstance(child, Tag | NavigableString):
                self.render(child)
        if is_block:
            self.flush()


def _clean(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()
    noisy: list[Tag] = []
    for tag in soup.find_all(["div", "section", "ul"]):
        if not isinstance(tag, Tag):
            continue
        classes = " ".join(tag.get("class") or []) + " " + str(tag.get("id") or "")
        if _NOISE_CLASS.search(classes):
            noisy.append(tag)
    for tag in noisy:
        if not tag.decomposed:
            tag.decompose()


def extract_html(data: bytes, filename: str | None = None) -> ExtractedDocument:
    soup = BeautifulSoup(decode_text(data), "lxml")
    title_tag = soup.find("title")
    title = _inline_text(title_tag) if isinstance(title_tag, Tag) else None
    author_tag = soup.find("meta", attrs={"name": "author"})
    author = str(author_tag.get("content") or "").strip() if isinstance(author_tag, Tag) else ""
    lang = soup.html.get("lang") if isinstance(soup.html, Tag) else None

    _clean(soup)
    root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article") or soup.body or soup
    renderer = _Renderer()
    if isinstance(root, Tag | NavigableString):
        renderer.render(root)
    renderer.flush()

    if not title:
        heading = soup.find("h1")
        title = _inline_text(heading) if isinstance(heading, Tag) else None
    metadata: dict[str, object] = {}
    if lang:
        metadata["lang"] = str(lang)
    return ExtractedDocument(
        text="\n\n".join(renderer.blocks),
        format="html",
        mime_type=HTML,
        title=title or None,
        author=author or None,
        metadata=metadata,
    )
