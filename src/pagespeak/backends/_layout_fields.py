"""Layout backend: a profile's mappings read strictly — an unknown key is refused and
every value's type is checked, with the field named in the error."""

from __future__ import annotations

import re
from typing import Any

from pw_foundation.exceptions import InvalidInputError

_REQUIRED: Any = object()


def bad(message: str) -> InvalidInputError:
    return InvalidInputError(f"layout profile: {message}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class Section:
    """One mapping of a profile. `name` is its dotted path ("" for the profile itself);
    `keys` are the keys it may hold (None: any)."""

    def __init__(self, data: Any, name: str, keys: tuple[str, ...] | None) -> None:
        label = name or "the profile"
        if not isinstance(data, dict):
            raise bad(f"{label} must be a mapping")
        unknown = sorted(str(k) for k in data if keys is not None and k not in keys)
        if unknown:
            raise bad(f"{label} has unknown key(s): {', '.join(unknown)}")
        self.data, self.name = data, name

    def at(self, key: object) -> str:
        return f"{self.name}.{key}" if self.name else str(key)

    def _get(self, key: str, kind: type, what: str, default: Any = _REQUIRED) -> Any:
        if key not in self.data:
            if default is _REQUIRED:
                raise bad(f"{self.at(key)} is missing")
            return default
        value = self.data[key]
        if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
            raise bad(f"{self.at(key)} must be {what}, got {value!r}")
        return value

    def num(self, key: str) -> float:
        value = self._get(key, object, "a number")
        if not _is_number(value):
            raise bad(f"{self.at(key)} must be a number, got {value!r}")
        return float(value)

    def whole(self, key: str) -> int:
        return int(self._get(key, int, "a whole number"))

    def text(self, key: str) -> str:
        return str(self._get(key, str, "text"))

    def word(self, key: str) -> str:
        value = self.text(key)
        if not value:
            raise bad(f"{self.at(key)} must not be empty")
        return value

    def opt_text(self, key: str) -> str | None:
        value = self._get(key, str, "text", None)
        return None if value is None else str(value)

    def flag(self, key: str) -> bool:
        return bool(self._get(key, bool, "true or false", False))

    def items(self, key: str, default: Any = _REQUIRED) -> list[Any]:
        return list(self._get(key, list, "a list", default))

    def texts(self, key: str) -> tuple[str, ...]:
        value = self.items(key)
        if not all(isinstance(v, str) for v in value):
            raise bad(f"{self.at(key)} must be a list of text, got {value!r}")
        return tuple(value)

    def words(self, key: str) -> tuple[str, ...]:
        value = self.texts(key)
        if "" in value:
            raise bad(f"{self.at(key)} must not hold an empty text")
        return value

    def wholes(self, key: str) -> frozenset[int]:
        value = self.items(key)
        if not all(_is_whole(v) for v in value):
            raise bad(f"{self.at(key)} must be a list of whole numbers, got {value!r}")
        return frozenset(value)

    def nums(self, key: str, count: int) -> list[float]:
        value = self.data.get(key)
        if not (isinstance(value, list) and len(value) == count and all(map(_is_number, value))):
            raise bad(f"{self.at(key)} must be {count} numbers, got {value!r}")
        return [float(v) for v in value]

    def pairs(self, key: str) -> tuple[tuple[str, str], ...]:
        """An optional list of two-text entries."""
        out = []
        for i, item in enumerate(self.items(key, [])):
            if not (
                isinstance(item, list) and len(item) == 2 and all(isinstance(v, str) for v in item)
            ):
                raise bad(f"{self.at(key)}[{i}] must be 2 texts, got {item!r}")
            out.append((item[0], item[1]))
        return tuple(out)

    def pattern(self, key: str, flags: int = 0, *, blank_ok: bool = False) -> re.Pattern[str]:
        """A regular expression. One that matches the empty string would match every line,
        so it is refused unless `blank_ok`."""
        try:
            found = re.compile(self.text(key), flags)
        except re.error as exc:
            raise bad(f"{self.at(key)} is not a valid pattern: {exc}") from exc
        if not blank_ok and found.search("") is not None:
            raise bad(
                f"{self.at(key)} matches the empty string, so it would match every line; "
                "a rule the book does not need takes the pattern '(?!)'"
            )
        return found

    def child(self, key: str, keys: tuple[str, ...] | None, *, optional: bool = False) -> Section:
        if key not in self.data and not optional:
            raise bad(f"{self.at(key)} is missing")
        return Section(self.data.get(key, {}), self.at(key), keys)

    def children(self, key: str, keys: tuple[str, ...]) -> list[Section]:
        """An optional list of mappings."""
        return [
            Section(raw, f"{self.at(key)}[{i}]", keys) for i, raw in enumerate(self.items(key, []))
        ]
