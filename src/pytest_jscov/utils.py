"""General-purpose helpers shared across the jscov plugin modules."""

from pathlib import Path

from pytest_jscov import covplugin


def line_offsets(source: str) -> list[int]:
    """Return the byte offset of the start of each 1-based line in *source*."""
    offsets = [0]
    for index, char in enumerate(source):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def entry_to_line_hits(entry: dict) -> dict[int, int]:
    """Convert one V8 coverage entry into per-line hit counts."""
    source: str = entry.get("source", "")
    if not source:
        return {}

    offsets = line_offsets(source)

    all_ranges: list[tuple[int, int, int]] = []
    for func in entry.get("functions", []):
        for rng in func["ranges"]:
            all_ranges.append((rng["startOffset"], rng["endOffset"], rng["count"]))

    if not all_ranges:
        return {}

    result: dict[int, int] = {}
    for line_idx, line_start in enumerate(offsets):
        line_num = line_idx + 1
        best_count: int | None = None
        best_size = float("inf")
        for start, end, count in all_ranges:
            if start <= line_start < end:
                size = end - start
                if size < best_size:
                    best_size = size
                    best_count = count
        if best_count is not None:
            result[line_num] = best_count

    return result


def merge_hits(accumulated: dict[int, int], new_hits: dict[int, int]) -> dict[int, int]:
    """Combine accumulated and new line-hit counts by summing per line."""
    merged = dict(accumulated)
    for line, count in new_hits.items():
        merged[line] = merged.get(line, 0) + count
    return merged


def url_key_to_path(key: str, static_root: str) -> Path | None:
    """Map a coverage key to an absolute filesystem path."""
    if key.startswith(("http://", "https://")):
        key = key[key.index("/", 8) :]
    static_prefix = "/static/"
    if key.startswith(static_prefix):
        rel = key[len(static_prefix) :]
        return (Path(static_root) / rel).resolve()
    path = Path(key)
    if path.is_absolute():
        return path
    return None


def is_js_cov_source(path: Path) -> bool:
    """Return True when *path* points only at reportable JS or TS sources."""
    if path.is_file():
        return path.suffix in {".js", ".ts"} and not path.name.endswith(".d.ts")

    if not path.is_dir():
        return False

    has_reportable_js = False
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        if covplugin._is_reportable_js(child):
            has_reportable_js = True
            continue
        if child.suffix == ".py":
            return False

    return has_reportable_js


def matches_cov_source(path: Path, source_paths: list[Path] | None) -> bool:
    """Return True when *path* is allowed by the active path-based cov targets."""
    if source_paths is None:
        return True

    for source in source_paths:
        if source.is_file() and path == source:
            return True
        if source.is_dir():
            try:
                path.relative_to(source)
            except ValueError:
                continue
            return True
    return False
