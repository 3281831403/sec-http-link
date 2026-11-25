"""Public smoke tests for Link header parsing and preload extraction."""

from __future__ import annotations

from linkhdr import find, merge_links, parse, serialize, to_preload_headers


def test_parse_keeps_quoted_commas_inside_params() -> None:
    links = parse('</a>; rel="next", </b>; title="x,y"')
    assert links == [
        {"uri": "/a", "params": {"rel": ["next"]}},
        {"uri": "/b", "params": {"title": ["x,y"]}},
    ]


def test_serialize_quotes_values_with_specials() -> None:
    links = [{"uri": "/a", "params": {"title": ["a,b"], "rel": ["next"]}}]
    assert serialize(links) == '</a>; title="a,b"; rel="next"'


def test_find_returns_every_match() -> None:
    links = [
        {"uri": "/a", "params": {"rel": ["next"]}},
        {"uri": "/b", "params": {"rel": ["next", "preload"]}},
        {"uri": "/c", "params": {"rel": ["prev"]}},
    ]
    assert [item["uri"] for item in find(links, "next")] == ["/a", "/b"]


def test_preload_requires_as() -> None:
    links = [
        {"uri": "/a.css", "params": {"rel": ["preload"], "as": ["style"]}},
        {"uri": "/b.js", "params": {"rel": ["preload"]}},
        {"uri": "/c", "params": {"rel": ["next"], "as": ["document"]}},
    ]
    assert to_preload_headers(links) == ["</a.css>; rel=preload; as=style"]


def test_merge_deduplicates_by_uri() -> None:
    first = [{"uri": "/a", "params": {"rel": ["next"]}}]
    second = [{"uri": "/a", "params": {"rel": ["prev"]}}]
    merged = merge_links(first, second)
    assert len(merged) == 1
    assert merged[0]["params"]["rel"] == ["next", "prev"]