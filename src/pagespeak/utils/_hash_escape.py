"""Keep HTML text that starts with ``#`` from becoming a markdown heading.

markitdown copies text verbatim, so ``<p># comment</p>`` converts to a
``# comment`` heading. :func:`mark_leading_hashes` puts a marker before each
``#`` run that opens a text node outside code, before conversion;
:func:`escape_marked_hashes` turns the markers that landed at the start of a
markdown line into ``\\`` and drops the rest.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import NavigableString

# Alphanumeric, so markitdown passes it through untouched (as `_mathml` does).
_MARK = "xpagespeakhashx"
_LEADING_HASH_RE = re.compile(r"^(\s*)(?=#{1,6}(?:\s|$))")
# The tags markitdown renders as code; script and style text is a NavigableString subclass.
_CODE_TAGS = ["pre", "code", "kbd", "samp"]
# A line start, after any blockquote or list-item markers.
_LINE_START_MARK_RE = re.compile(
    rf"^((?:[ \t]*(?:>|[*+-][ \t]|\d+[.)][ \t]))*[ \t]*){_MARK}", re.MULTILINE
)


def mark_leading_hashes(html: str) -> str:
    """Put the marker before every text node's leading ``#`` run outside code.

    Returns `html` itself when no text node starts with one, or when the page
    already holds the marker text (it would be removed with the markers).
    """
    if _MARK in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    hits = [
        s
        for s in soup.find_all(string=_LEADING_HASH_RE)
        if type(s) is NavigableString and s.find_parent(_CODE_TAGS) is None
    ]
    if not hits:
        return html
    for s in hits:
        s.replace_with(NavigableString(_LEADING_HASH_RE.sub(rf"\1{_MARK}", s, count=1)))
    return str(soup)


def escape_marked_hashes(markdown: str) -> str:
    """Escape each marked ``#`` that starts a markdown line; drop the other markers."""
    if _MARK not in markdown:
        return markdown
    return _LINE_START_MARK_RE.sub(r"\1\\", markdown).replace(_MARK, "")
