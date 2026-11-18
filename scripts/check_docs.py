#!/usr/bin/env python3
"""Validate repository-local Markdown links, images, fences, and optional HTTP links."""

from __future__ import annotations

import argparse
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
AUTOLINK_RE = re.compile(r"<((?:https?://)[^>]+)>")
REFERENCE_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)")
HTTP_SCHEMES = {"http", "https"}
IGNORED_SCHEMES = {"mailto", "tel", "data"}
UNPUBLISHED_REPO_PREFIX = "https://github.com/albertwickous-droid/voice-input-bridge"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass(frozen=True)
class Link:
    source: Path
    line: int
    target: str
    is_image: bool = False


def markdown_files(root: Path) -> list[Path]:
    files = sorted(root.glob("*.md"))
    files.extend(sorted((root / "docs").glob("*.md")))
    files.extend(sorted((root / ".github").rglob("*.md")))
    return sorted(set(files))


def links_in_file(path: Path) -> tuple[list[Link], list[str]]:
    links: list[Link] = []
    errors: list[str] = []
    fence: str | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is not None:
            continue
        for match in LINK_RE.finditer(line):
            image_marker, alt, target = match.group(1), match.group(2), match.group(3)
            if image_marker and not alt.strip():
                errors.append(f"{path}:{number}: image has empty alt text: {target}")
            links.append(Link(path, number, target, bool(image_marker)))
        for match in AUTOLINK_RE.finditer(line):
            links.append(Link(path, number, match.group(1)))
        reference = REFERENCE_RE.match(line)
        if reference:
            links.append(Link(path, number, reference.group(1)))
    if fence is not None:
        errors.append(f"{path}: unclosed Markdown code fence")
    return links, errors


def split_target(target: str) -> tuple[str, str]:
    target = target.strip().strip("<>")
    parsed = urllib.parse.urlsplit(target)
    if not parsed.scheme and not parsed.netloc:
        path, _, fragment = target.partition("#")
        path = path.split("?", 1)[0]
        return urllib.parse.unquote(path), fragment
    return target, parsed.fragment


def check_local_link(link: Link, root: Path) -> str | None:
    target = link.target.strip().strip("<>")
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme in HTTP_SCHEMES or parsed.scheme in IGNORED_SCHEMES:
        return None
    if target.startswith("#"):
        return None
    relative, _fragment = split_target(target)
    if not relative:
        return None
    candidate = Path(relative)
    if not candidate.is_absolute():
        candidate = (link.source.parent / candidate).resolve()
    else:
        candidate = (root / relative.lstrip("/")).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return f"{link.source}:{link.line}: local link escapes repository: {link.target}"
    if not candidate.exists():
        kind = "image" if link.is_image else "link"
        return f"{link.source}:{link.line}: broken local {kind}: {link.target}"
    return None


def check_external_link(url: str) -> tuple[str, int | None, str | None]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "voice-input-bridge-doc-check/1.0 (+https://github.com/albertwickous-droid/voice-input-bridge)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return url, response.status, None
    except urllib.error.HTTPError as exc:
        return url, exc.code, None
    except Exception as exc:
        return url, None, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--external", action="store_true", help="also request external HTTP(S) links"
    )
    parser.add_argument(
        "--strict-external", action="store_true", help="fail on external transport errors"
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    errors: list[str] = []
    external: set[str] = set()
    checked_files = markdown_files(root)
    for path in checked_files:
        links, file_errors = links_in_file(path)
        errors.extend(file_errors)
        for link in links:
            parsed = urllib.parse.urlsplit(link.target.strip().strip("<>"))
            if parsed.scheme in HTTP_SCHEMES:
                if parsed.hostname not in LOOPBACK_HOSTS:
                    external.add(link.target.strip().strip("<>"))
            else:
                problem = check_local_link(link, root)
                if problem:
                    errors.append(problem)

    if errors:
        print("Documentation check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"Documentation check passed: {len(checked_files)} Markdown files, local links and fences valid."
    )

    if args.external:
        results = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(check_external_link, sorted(external)))
        external_errors: list[str] = []
        warnings: list[str] = []
        for url, status, transport_error in results:
            if status is None:
                message = f"{url}: {transport_error}"
                (external_errors if args.strict_external else warnings).append(message)
            elif status in {401, 403, 405, 429}:
                warnings.append(f"{url}: HTTP {status} (automated clients blocked or rate-limited)")
            elif status == 404 and url.startswith(UNPUBLISHED_REPO_PREFIX):
                warnings.append(f"{url}: HTTP 404 (repository not published yet)")
            elif status >= 400:
                external_errors.append(f"{url}: HTTP {status}")
        for warning in warnings:
            print(f"warning: {warning}")
        if external_errors:
            print("External documentation check failed:")
            for error in external_errors:
                print(f"- {error}")
            return 1
        print(f"External documentation check passed: {len(external)} URLs checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
