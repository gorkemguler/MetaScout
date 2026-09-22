"""In-place self-update behind `metascout update`.

MetaScout isn't published on PyPI: it's installed from a git clone (pip or
pipx editable install, per the README), from a GitHub release archive with
plain pip, or baked into a Docker image. Each needs a different update step,
so this works out which kind of copy is running and does the matching thing.
"""
from __future__ import annotations

import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Callable

import requests

from .config import DEFAULT_USER_AGENT

REPO = "gorkemguler/MetaScout"
REPO_URL = f"https://github.com/{REPO}"
_LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
# The release tag ends up on git/pip command lines, so only a plain version
# tag is ever accepted from the API (never anything starting with "-").
_TAG_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")
_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


class UpdateError(RuntimeError):
    pass


def parse_version(version: str) -> tuple[int, ...]:
    m = _TAG_RE.match(version.strip())
    if not m:
        raise ValueError(f"not a version: {version!r}")
    return tuple(int(part) for part in m.group(1).split("."))


def latest_release_tag(timeout: int = 10) -> str:
    try:
        resp = requests.get(
            _LATEST_RELEASE_API, timeout=timeout,
            headers={"Accept": "application/vnd.github+json", "User-Agent": DEFAULT_USER_AGENT},
        )
        resp.raise_for_status()
        tag = str(resp.json().get("tag_name", ""))
    except (requests.RequestException, ValueError) as exc:
        raise UpdateError(f"Could not reach GitHub to look up the latest release: {exc}") from exc
    if not _TAG_RE.match(tag):
        raise UpdateError(f"Unexpected release tag from GitHub: {tag!r}")
    return tag


def source_checkout() -> Path | None:
    """Repo root when this copy runs straight from a git clone (editable
    install): src/metascout/ inside a directory with .git and pyproject.toml."""
    root = Path(__file__).resolve().parent.parent.parent
    if (root / ".git").exists() and (root / "pyproject.toml").is_file():
        return root
    return None


def in_docker() -> bool:
    return Path("/.dockerenv").exists()


def installed_extras() -> list[str]:
    """Extras whose requirements are all installed already (e.g. the user
    once ran `pip install -e '.[content-scan]'`), so a reinstall keeps them
    and picks up any dependency a new release added to them."""
    try:
        dist = metadata.distribution("metascout")
    except metadata.PackageNotFoundError:
        return []
    requires = dist.requires or []
    extras = []
    for extra in dist.metadata.get_all("Provides-Extra") or []:
        marker = re.compile(rf"extra\s*==\s*['\"]{re.escape(extra)}['\"]")
        names = [m.group(1) for r in requires if marker.search(r) and (m := _REQ_NAME_RE.match(r))]
        if names and all(_is_installed(n) for n in names):
            extras.append(extra)
    return extras


def _is_installed(name: str) -> bool:
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def _extras_suffix() -> str:
    extras = installed_extras()
    return f"[{','.join(extras)}]" if extras else ""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise UpdateError(f"`{cmd[0]}` not found on PATH.") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        raise UpdateError(f"`{' '.join(cmd)}` failed:\n  " + "\n  ".join(detail))
    return proc


def _pip_install(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", *args]
    try:
        _run(cmd)
    except UpdateError as exc:
        # Typical on Windows: the running metascout.exe can't be replaced.
        raise UpdateError(f"{exc}\nRun it yourself instead:\n  {subprocess.list2cmdline(cmd)}") from exc


def update_git_checkout(root: Path, tag: str, log: Callable[[str], None], repo_url: str = REPO_URL) -> None:
    """Fast-forward the clone to the release tag; reinstall only if
    pyproject.toml (dependencies/entry points) changed — with an editable
    install, new code is live as soon as the files change."""
    git = ["git", "-C", str(root)]
    if _run([*git, "status", "--porcelain", "--untracked-files=no"]).stdout.strip():
        raise UpdateError(f"{root} has local changes. Commit or stash them, then run `metascout update` again.")
    old_head = _run([*git, "rev-parse", "HEAD"]).stdout.strip()

    log(f"fetching {tag} from {repo_url} ...")
    # Fetch from the canonical repo URL rather than a remote name, so a clone
    # whose "origin" was renamed or points at a fork still gets the release.
    _run([*git, "fetch", "--quiet", "--no-tags", repo_url, f"+refs/tags/{tag}:refs/tags/{tag}"])
    try:
        _run([*git, "merge", "--ff-only", "--quiet", f"refs/tags/{tag}^{{commit}}"])
    except UpdateError as exc:
        raise UpdateError(
            f"{exc}\nYour checkout has diverged from the release (local commits?); "
            f"update it by hand, e.g. `git -C {root} pull`."
        ) from exc

    if _run([*git, "diff", "--name-only", old_head, "HEAD", "--", "pyproject.toml"]).stdout.strip():
        log("dependencies changed, reinstalling ...")
        _pip_install(["-e", f"{root}{_extras_suffix()}"])


def update_pip_install(tag: str, log: Callable[[str], None]) -> None:
    """Reinstall from the release's source archive — no git needed."""
    log(f"installing {tag} with pip ...")
    _pip_install(["--upgrade", f"metascout{_extras_suffix()} @ {REPO_URL}/archive/refs/tags/{tag}.tar.gz"])
