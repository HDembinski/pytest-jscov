"""Helpers for inline sourcemap decoding and source resolution."""

import base64
import json
import re
from pathlib import Path

from pytest_jscov.vlq import vlq_decode_segment

_SOURCEMAP_RE = re.compile(
    r"//# sourceMappingURL=data:application/json;base64,([A-Za-z0-9+/=]+)"
)


def parse_inline_sourcemap(source: str) -> dict | None:
    """Extract and decode an inline sourcemap comment from JS source."""
    match = _SOURCEMAP_RE.search(source)
    if not match:
        return None
    return json.loads(base64.b64decode(match.group(1)))


def gen_to_orig_line_map(sourcemap: dict) -> dict[int, list[tuple[int, int]]]:
    """Build generated_line to original line mappings from a sourcemap."""
    mappings = sourcemap.get("mappings", "")
    gen_to_orig: dict[int, list[tuple[int, int]]] = {}

    src_idx = orig_line = orig_col = 0
    for gen_line_idx, line_str in enumerate(mappings.split(";")):
        gen_line = gen_line_idx + 1
        gen_col = 0
        for seg_str in line_str.split(","):
            if not seg_str:
                continue
            fields = vlq_decode_segment(seg_str)
            gen_col += fields[0]
            if len(fields) >= 4:
                src_idx += fields[1]
                orig_line += fields[2]
                orig_col += fields[3]
                gen_to_orig.setdefault(gen_line, []).append((src_idx, orig_line + 1))

    return gen_to_orig


def normalise_source_key(script_url: str, source_path: str) -> str:
    """Resolve a sourcemap source path to a canonical coverage key."""
    if source_path.startswith(("http://", "https://")):
        return source_path
    if source_path.startswith("/") or (len(source_path) >= 2 and source_path[1] == ":"):
        return str(Path(source_path).resolve())
    if source_path.startswith(("./", "../")):
        base = script_url.rsplit("/", 1)[0] + "/"
        parts = (base + source_path).split("/")
        resolved: list[str] = []
        for part in parts:
            if part == "..":
                if resolved:
                    resolved.pop()
            elif part != ".":
                resolved.append(part)
        return "/".join(resolved)
    return str(Path(source_path).resolve())
