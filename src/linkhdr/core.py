"""RFC 8288 Link header parsing, serialization and preload extraction.

The public surface covers the whole header lifecycle: a field value is parsed
into link items, items are serialized back into a header value, items are
looked up by relation type, two parsed lists are merged without duplicating a
target, and preload candidates are turned into standalone header values.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

# Characters permitted in an HTTP token (RFC 7230 section 3.2.6).  A parameter
# value may be emitted unquoted only when every character is in this set.
_TOKEN_CHARS = frozenset(
    "!#$%&'*+-.^_`|~"
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)


def _is_token(value: str) -> bool:
    """Return True when *value* can be emitted without surrounding quotes."""
    return bool(value) and all(ch in _TOKEN_CHARS for ch in value)


def _split(text: str, separator: str, angle: bool = False) -> List[str]:
    """Split *text* on *separator*, ignoring separators inside quoting.

    When *angle* is true, separators inside a ``<...>`` span are ignored as
    well.  Quoted strings (with backslash escapes) are always skipped.
    """
    parts: List[str] = []
    buf: List[str] = []
    in_quotes = False
    escaped = False
    in_angle = False
    for ch in text:
        if in_quotes:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_quotes = False
            continue
        if angle and in_angle:
            buf.append(ch)
            if ch == ">":
                in_angle = False
            continue
        if ch == '"':
            in_quotes = True
            buf.append(ch)
            continue
        if angle and ch == "<":
            in_angle = True
            buf.append(ch)
            continue
        if ch == separator:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        out: List[str] = []
        escaped = False
        for ch in raw[1:-1]:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                escaped = True
            else:
                out.append(ch)
        return "".join(out)
    return raw


def _quote_forced(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _quote(value: str) -> str:
    """Quote *value* only when it is not a valid token."""
    if _is_token(value):
        return value
    return _quote_forced(value)


def _rel_values(link: Mapping[str, Any]) -> List[Any]:
    """Return the relation tokens of *link*, matching the key case-insensitively."""
    for name, values in link["params"].items():
        if name.lower() == "rel":
            return list(values)
    return []


def parse(value: str) -> List[Dict[str, Any]]:
    """Parse a Link header value into a list of link items."""
    links: List[Dict[str, Any]] = []
    for chunk in _split(value, ",", angle=True):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.startswith("<"):
            raise ValueError("invalid-link")
        end = chunk.find(">")
        if end < 0:
            raise ValueError("invalid-link")
        uri = chunk[1:end]
        params: Dict[str, List[str]] = {}
        for part in _split(chunk[end + 1 :], ";"):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                name, raw = part.split("=", 1)
                name = name.strip().lower()
                item = _unquote(raw.strip())
            else:
                name = part.lower()
                item = ""
            if name == "rel":
                values = item.split()
            else:
                values = [item]
            if name in params:
                params[name].extend(values)
            else:
                params[name] = list(values)
        links.append({"uri": uri, "params": params})
    return links


def serialize(links: Sequence[Mapping[str, Any]]) -> str:
    """Serialize link items back into a single Link header value."""
    rendered: List[str] = []
    for link in links:
        parts = ["<" + str(link["uri"]) + ">"]
        for name, values in link["params"].items():
            if name.lower() == "rel":
                parts.append(
                    "; rel=" + _quote_forced(" ".join(str(v) for v in values))
                )
            else:
                for value in values:
                    parts.append("; " + str(name) + "=" + _quote(str(value)))
        rendered.append("".join(parts))
    return ", ".join(rendered)


def find(links: Sequence[Mapping[str, Any]], rel: str) -> List[Dict[str, Any]]:
    """Return every link whose relation list contains the requested type."""
    target = rel.strip().lower()
    if not target:
        return []
    matches: List[Dict[str, Any]] = []
    for link in links:
        values = _rel_values(link)
        if any(str(value).lower() == target for value in values):
            matches.append(
                {
                    "uri": link["uri"],
                    "params": {
                        name: list(values) for name, values in link["params"].items()
                    },
                }
            )
    return matches


def merge_links(
    first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge two link lists, de-duplicating by target URI."""
    merged: List[Dict[str, Any]] = []
    seen: Dict[str, Dict[str, Any]] = {}
    for link in list(first) + list(second):
        uri = str(link["uri"])
        params = link["params"]
        entry = seen.get(uri)
        if entry is None:
            entry = {
                "uri": uri,
                "params": {name: list(values) for name, values in params.items()},
            }
            seen[uri] = entry
            merged.append(entry)
            continue
        existing = {name.lower(): name for name in entry["params"]}
        for name, values in params.items():
            key = name.lower()
            if key == "rel":
                if key in existing:
                    target = entry["params"][existing[key]]
                    for value in values:
                        if not any(value == current for current in target):
                            target.append(value)
                else:
                    entry["params"][name] = list(values)
                    existing[key] = name
            elif key not in existing:
                entry["params"][name] = list(values)
                existing[key] = name
            # A non-relation conflict keeps the value that appeared first.
    return merged


def to_preload_headers(links: Sequence[Mapping[str, Any]]) -> List[str]:
    """Render preload candidates: items declaring both ``preload`` and ``as``."""
    headers: List[str] = []
    for link in links:
        relations = [str(value).lower() for value in _rel_values(link)]
        if "preload" not in relations:
            continue
        params = link["params"]
        as_key: Optional[str] = next(
            (name for name in params if name.lower() == "as"), None
        )
        if as_key is None:
            continue
        values = params[as_key]
        if not values:
            continue
        headers.append(
            "<"
            + str(link["uri"])
            + ">; rel=preload; as="
            + _quote(str(values[0]))
        )
    return headers
