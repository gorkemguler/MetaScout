import shutil
import subprocess
from unittest.mock import patch

import pytest
import requests
from click.testing import CliRunner

from metascout import __version__, updater
from metascout.cli import main

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo, files, message, tag=None):
    for name, content in files.items():
        (repo / name).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", message)
    if tag:
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "tag", "-a", tag, "-m", tag)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def release_repos(tmp_path):
    """An upstream repo with releases v1.0.0 and v1.1.0, and a user's clone
    still sitting on v1.0.0."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _commit(upstream, {"pyproject.toml": 'version = "1.0.0"\n', "code.py": "a = 1\n"}, "v1.0.0", tag="v1.0.0")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(upstream), str(clone)], check=True)
    return upstream, clone


def test_parse_version():
    assert updater.parse_version("v0.2.10") == (0, 2, 10)
    assert updater.parse_version("0.3") < updater.parse_version("0.3.1")
    with pytest.raises(ValueError):
        updater.parse_version("latest")


@pytest.mark.parametrize("tag", ["--upload-pack=touch /tmp/x", "v1.0; rm -rf ~", ""])
def test_latest_release_tag_rejects_anything_but_a_version_tag(tag):
    with patch.object(updater.requests, "get") as get:
        get.return_value.json.return_value = {"tag_name": tag}
        with pytest.raises(updater.UpdateError):
            updater.latest_release_tag()


def test_latest_release_tag_network_error():
    with patch.object(updater.requests, "get", side_effect=requests.ConnectionError("offline")):
        with pytest.raises(updater.UpdateError, match="Could not reach GitHub"):
            updater.latest_release_tag()


@needs_git
def test_update_git_checkout_fast_forwards_and_reinstalls_on_dependency_change(release_repos, monkeypatch):
    upstream, clone = release_repos
    new_head = _commit(upstream, {"pyproject.toml": 'version = "1.1.0"\n', "code.py": "a = 2\n"}, "v1.1.0", tag="v1.1.0")
    _commit(upstream, {"code.py": "a = 3\n"}, "unreleased work on main")
    pip_calls = []
    monkeypatch.setattr(updater, "_pip_install", pip_calls.append)
    monkeypatch.setattr(updater, "installed_extras", lambda: ["content-scan"])

    updater.update_git_checkout(clone, "v1.1.0", log=lambda m: None, repo_url=str(upstream))

    assert _git(clone, "rev-parse", "HEAD") == new_head  # the release, not unreleased main
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "main"  # still on a branch
    assert (clone / "code.py").read_text() == "a = 2\n"
    assert pip_calls == [["-e", f"{clone}[content-scan]"]]


@needs_git
def test_update_git_checkout_skips_reinstall_when_dependencies_unchanged(release_repos, monkeypatch):
    upstream, clone = release_repos
    _commit(upstream, {"code.py": "a = 2\n"}, "v1.0.1", tag="v1.0.1")
    pip_calls = []
    monkeypatch.setattr(updater, "_pip_install", pip_calls.append)

    updater.update_git_checkout(clone, "v1.0.1", log=lambda m: None, repo_url=str(upstream))

    assert (clone / "code.py").read_text() == "a = 2\n"
    assert pip_calls == []


@needs_git
def test_update_git_checkout_refuses_local_changes(release_repos):
    upstream, clone = release_repos
    _commit(upstream, {"code.py": "a = 2\n"}, "v1.0.1", tag="v1.0.1")
    (clone / "code.py").write_text("a = 'my edit'\n")

    with pytest.raises(updater.UpdateError, match="local changes"):
        updater.update_git_checkout(clone, "v1.0.1", log=lambda m: None, repo_url=str(upstream))
    assert (clone / "code.py").read_text() == "a = 'my edit'\n"


@needs_git
def test_update_git_checkout_refuses_diverged_history(release_repos):
    upstream, clone = release_repos
    _commit(upstream, {"code.py": "a = 2\n"}, "v1.0.1", tag="v1.0.1")
    local_head = _commit(clone, {"notes.txt": "mine\n"}, "local commit")

    with pytest.raises(updater.UpdateError, match="diverged"):
        updater.update_git_checkout(clone, "v1.0.1", log=lambda m: None, repo_url=str(upstream))
    assert _git(clone, "rev-parse", "HEAD") == local_head


def test_update_pip_install_uses_release_archive_and_keeps_extras(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "_run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(updater, "installed_extras", lambda: ["api", "ocr"])

    updater.update_pip_install("v9.9.9", log=lambda m: None)

    [cmd] = calls
    assert cmd[1:] == [
        "-m", "pip", "install", "--quiet", "--upgrade",
        "metascout[api,ocr] @ https://github.com/gorkemguler/MetaScout/archive/refs/tags/v9.9.9.tar.gz",
    ]


def test_installed_extras_only_lists_fully_installed_ones(monkeypatch):
    class FakeDist:
        requires = [
            "click>=8.1",
            'pypdf>=4.0; extra == "content-scan"',
            'phonenumbers>=8.13; extra == "content-scan"',
            'fastapi>=0.110; extra == "api"',
        ]
        metadata = type("M", (), {"get_all": staticmethod(lambda key: ["content-scan", "api"])})()

    monkeypatch.setattr(updater.metadata, "distribution", lambda name: FakeDist())
    monkeypatch.setattr(updater, "_is_installed", lambda name: name in {"pypdf", "phonenumbers"})

    assert updater.installed_extras() == ["content-scan"]


def _invoke_update(*args, latest):
    with patch.object(updater, "latest_release_tag", return_value=latest):
        return CliRunner().invoke(main, ["update", *args])


def test_cli_update_already_up_to_date():
    with patch.object(updater, "update_git_checkout") as git_up, patch.object(updater, "update_pip_install") as pip_up:
        result = _invoke_update(latest=f"v{__version__}")
    assert result.exit_code == 0
    assert "Already up to date" in result.output
    git_up.assert_not_called()
    pip_up.assert_not_called()


def test_cli_update_check_only_reports():
    with patch.object(updater, "update_git_checkout") as git_up, patch.object(updater, "update_pip_install") as pip_up:
        result = _invoke_update("--check", latest="v99.0.0")
    assert result.exit_code == 0
    assert "New version available: 99.0.0" in result.output
    git_up.assert_not_called()
    pip_up.assert_not_called()


def test_cli_update_git_checkout(tmp_path):
    with patch.object(updater, "source_checkout", return_value=tmp_path), \
         patch.object(updater, "update_git_checkout") as git_up:
        result = _invoke_update(latest="v99.0.0")
    assert result.exit_code == 0, result.output
    assert git_up.call_args.args[:2] == (tmp_path, "v99.0.0")
    assert "Updated to 99.0.0" in result.output


def test_cli_update_plain_pip_install():
    with patch.object(updater, "source_checkout", return_value=None), \
         patch.object(updater, "in_docker", return_value=False), \
         patch.object(updater, "update_pip_install") as pip_up:
        result = _invoke_update(latest="v99.0.0")
    assert result.exit_code == 0, result.output
    assert pip_up.call_args.args[0] == "v99.0.0"


def test_cli_update_in_docker_explains_rebuild():
    with patch.object(updater, "source_checkout", return_value=None), \
         patch.object(updater, "in_docker", return_value=True), \
         patch.object(updater, "update_pip_install") as pip_up:
        result = _invoke_update(latest="v99.0.0")
    assert result.exit_code == 1
    assert "docker compose up -d --build" in result.output
    pip_up.assert_not_called()


def test_cli_update_reports_failure():
    with patch.object(updater, "source_checkout", return_value=None), \
         patch.object(updater, "in_docker", return_value=False), \
         patch.object(updater, "update_pip_install", side_effect=updater.UpdateError("pip exploded")):
        result = _invoke_update(latest="v99.0.0")
    assert result.exit_code == 1
    assert "pip exploded" in result.output
