"""Безопасный вывод ответа модели: небольшой набор разметки Markdown → HTML.

Текст сначала экранируется целиком, поэтому HTML из ответа модели не исполняется.
Поддерживаются заголовки, списки, **жирный**, *курсив* и `код`.
"""

import re

from markupsafe import Markup, escape

_RE_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
_RE_BOLD_LINE = re.compile(r"^\*\*([^*]+)\*\*:?$")
_RE_BULLET = re.compile(r"^[-*•]\s+(.*)$")
_RE_NUMBER = re.compile(r"^(\d{1,3})[.)]\s+(.*)$")
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RE_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_RE_CODE = re.compile(r"`([^`\n]+)`")


def _inline(text: str) -> str:
    html = str(escape(text))
    html = _RE_CODE.sub(r"<code>\1</code>", html)
    html = _RE_BOLD.sub(r"<strong>\1</strong>", html)
    return _RE_ITALIC.sub(r"<em>\1</em>", html)


def render_markdown(text: str | None) -> Markup:
    """Преобразует текст модели в HTML: абзацы, заголовки, маркированные и нумерованные списки."""
    out: list[str] = []
    paragraph: list[str] = []
    open_list = ""  # "ul", "ol" или пусто

    def close_paragraph() -> None:
        if paragraph:
            out.append("<p>" + "<br>".join(paragraph) + "</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal open_list
        if open_list:
            out.append(f"</{open_list}>")
            open_list = ""

    def item(kind: str, html: str) -> None:
        nonlocal open_list
        close_paragraph()
        if open_list != kind:
            close_list()
            out.append(f"<{kind}>")
            open_list = kind
        out.append(html)

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            close_paragraph()
            continue
        heading = _RE_HEADING.match(line) or _RE_BOLD_LINE.match(line)
        if heading:
            close_paragraph()
            close_list()
            out.append(f"<h4>{_inline(heading[1].strip('* '))}</h4>")
        elif m := _RE_BULLET.match(line):
            item("ul", f"<li>{_inline(m[1])}</li>")
        elif m := _RE_NUMBER.match(line):
            # value сохраняет номер, даже если список разорван абзацем
            item("ol", f'<li value="{int(m[1])}">{_inline(m[2])}</li>')
        else:
            close_list()
            paragraph.append(_inline(line))
    close_paragraph()
    close_list()
    return Markup("\n".join(out))
