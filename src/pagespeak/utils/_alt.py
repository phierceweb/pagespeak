"""Image alt text normalization for markdown emission."""

from __future__ import annotations


def flatten_alt(alt: str) -> str:
    """Alt text as one line, safe to interpolate into `![alt](target)`.

    A blank line inside alt voids the ref for `parse_image_refs`, so every
    later pass skips the image. Apply where a ref is built, not in the parser.

    Whitespace-only alt keeps a space: emptying it would make the ref match
    `_cleanup_regexes.IMAGE_ONLY_RE` and aggressive cleanup would delete it.
    """
    if not alt:
        return ""
    return " ".join(alt.split()) or " "
