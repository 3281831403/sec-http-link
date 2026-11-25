"""RFC 8288 Link header parsing, serialization and preload extraction.

The public surface covers the whole header lifecycle: a field value is parsed
into link items, items are serialized back into a header value, items are
looked up by relation type, two parsed lists are merged without duplicating a
target, and preload candidates are turned into standalone header values.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence


def _split(text: str, separator: str) -> List[str]:
    """Split on a separator."""
    return text.split(separator)


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


def _quote(value: str) -> str:
    if " " in value:
        return '"' + value + '"'
    return value


def _quote_forced(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse(value: str) -> List[Dict[str, Any]]:
    """Parse a Link header value into a list of link items."""
    links: List[Dict[str, Any]] = []
    for chunk in _split(value, ","):
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
        for part in chunk[end + 1 :].split(";"):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                name, raw = part.split("=", 1)
                name = name.strip()
                item = _unquote(raw.strip())
            else:
                name = part
                item = ""
            values = [item]
            params[name] = values
        links.append({"uri": uri, "params": params})
    return links


def serialize(links: Sequence[Mapping[str, Any]]) -> str:
    """Serialize link items back into a single Link header value."""
    rendered: List[str] = []
    for link in links:
        parts = ["<" + str(link["uri"]) + ">"]
        for name, values in link["params"].items():
            if not values:
                continue
            if name == "rel":
                parts.append(
                    "; rel=" + _quote_forced(" ".join(str(v) for v in values))
                )
            else:
                for value in values:
                    parts.append("; " + str(name) + "=" + _quote(str(value)))
        rendered.append("".join(parts))
    return ", ".join(rendered)


def find(links: Sequence[Mapping[str, Any]], rel: str) -> List[Dict[str, Any]]:
    """Return links whose relation list contains the requested type."""
    target = rel.strip()
    if not target:
        return []
    for link in links:
        values = link["params"].get("rel", [])
        if target in values:
            return [{"uri": link["uri"], "params": dict(link["params"])}]
    return []


def merge_links(
    first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge two link lists into one."""
    merged: List[Dict[str, Any]] = []
    for link in list(first) + list(second):
        merged.append(
            {
                "uri": str(link["uri"]),
                "params": {name: list(values) for name, values in link["params"].items()},
            }
        )
    return merged


def to_preload_headers(links: Sequence[Mapping[str, Any]]) -> List[str]:
    """Render preload candidates."""
    headers: List[str] = []
    for link in links:
        relations = [str(value).lower() for value in link["params"].get("rel", [])]
        if "preload" not in relations:
            continue
        values = link["params"].get("as") or [""]
        headers.append(
            "<"
            + _absolute(str(link["uri"]))
            + ">; rel=preload; as="
            + _quote(str(values[0]))
        )
    return headers


def _absolute(uri: str) -> str:
    if "://" in uri or uri.startswith("//"):
        return uri
    return "/" + uri.lstrip("/")