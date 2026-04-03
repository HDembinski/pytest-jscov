"""Transform raw V8 coverage entries into accumulated line-hit data."""

from urllib.parse import urlsplit

from pytest_jscov.source_filtering import filter_line_hits, source_executable_lines
from pytest_jscov.sourcemap import (
    gen_to_orig_line_map,
    normalise_source_key,
    parse_inline_sourcemap,
)
from pytest_jscov.utils import entry_to_line_hits, merge_hits


def process_entries(
    entries: list[dict],
    accumulated: dict[str, dict[int, int]],
    sources: dict[str, str],
) -> None:
    """Fold V8 coverage entries into accumulated line hits and source text."""
    for entry in entries:
        url: str = entry.get("url", "")
        path = urlsplit(url).path
        if not path.startswith("/static/"):
            continue

        source: str = entry.get("source", "")
        line_hits = filter_line_hits(source, entry_to_line_hits(entry))

        sourcemap = parse_inline_sourcemap(source)
        if sourcemap:
            gen_to_orig = gen_to_orig_line_map(sourcemap)
            src_contents: list[str] = sourcemap.get("sourcesContent") or []
            src_names: list[str] = sourcemap.get("sources") or []

            orig_hits: dict[int, dict[int, int]] = {}
            for gen_line, count in line_hits.items():
                for src_idx, orig_line in gen_to_orig.get(gen_line, []):
                    orig_hits.setdefault(src_idx, {})
                    orig_hits[src_idx][orig_line] = (
                        orig_hits[src_idx].get(orig_line, 0) + count
                    )

            for src_idx, hits in orig_hits.items():
                key = src_names[src_idx] if src_idx < len(src_names) else url
                key = normalise_source_key(url, key)
                executable_lines = source_executable_lines(
                    key,
                    src_contents[src_idx] if src_idx < len(src_contents) else None,
                )
                if executable_lines is not None:
                    hits = {
                        line: count
                        for line, count in hits.items()
                        if line in executable_lines
                    }
                accumulated[key] = merge_hits(accumulated.get(key, {}), hits)
                if key not in sources and src_idx < len(src_contents):
                    sources[key] = src_contents[src_idx]
        else:
            accumulated[path] = merge_hits(accumulated.get(path, {}), line_hits)
            if path not in sources:
                sources[path] = source
