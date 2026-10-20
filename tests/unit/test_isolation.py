# SPDX-License-Identifier: Apache-2.0
"""RH-09: OS resource limits and bubblewrap contain a hostile child.

Layer 2 (``rlimit``) caps memory, CPU, file size, and process count. It does
not block the network or writes outside the workspace; those are layer 3 and
run under bubblewrap. nsjail and gVisor are not launched.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

import pytest

from tersalang.cli import main
from tersalang.harness import load_task, run_episode, run_episode_isolated
from tersalang.isolation import (
    CPU_MESSAGE,
    ENV_ALLOWLIST,
    MEMORY_MESSAGE,
    WINDOWS_JOB_REASON,
    WORKSPACE,
    IsolationUnavailable,
    OsLimits,
    _job_objects_usable,
    backend_available,
    bwrap_available,
    bwrap_read_only,
    bwrap_symlinks,
    child_env,
    classify_os_death,
    package_root,
    process_count,
    resolve,
    rlimit_available,
    run_argv,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "tasks" / "add_one"

_MEMORY_BOMB = """chunks = []
try:
    for _ in range(40):
        chunks.append(bytearray(8 * 1024 * 1024))
    print("allocated", len(chunks))
except MemoryError:
    raise
"""

_CPU_BOMB = """x = 0
while True:
    x += 1
"""

_FORK_BOMB = """import os
n = 0
try:
    while n < 40:
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        n += 1
    print("forked", n)
except OSError as exc:
    print("stopped", n, exc.errno)
"""

_NETWORK = """import socket
sock = socket.socket()
sock.settimeout(2)
try:
    sock.connect(("1.1.1.1", 443))
    print("connected")
except OSError as exc:
    print("blocked", exc.errno)
"""


def _need_rlimit() -> None:
    if not rlimit_available():
        pytest.skip("setrlimit is not available on this host")


def _need_bwrap() -> None:
    if not bwrap_available():
        pytest.skip("bubblewrap is not installed")


def _episode(text: str) -> dict[str, object]:
    body = json.loads(text)
    assert isinstance(body, dict)
    return body


def test_signal_mapping_does_not_treat_a_crash_hook_as_a_kill() -> None:
    cpu = getattr(signal, "SIGXCPU", 24)
    assert classify_os_death(-cpu, "") == ("T6207", CPU_MESSAGE)
    assert classify_os_death(128 + cpu, "") == ("T6207", CPU_MESSAGE)
    assert classify_os_death(1, "Traceback\nMemoryError\n") == ("T6206", MEMORY_MESSAGE)
    for name in ("SIGKILL", "SIGSEGV", "SIGBUS", "SIGABRT"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        assert classify_os_death(-number, "") == ("T6206", MEMORY_MESSAGE)
        assert classify_os_death(128 + number, "") == ("T6206", MEMORY_MESSAGE)
    assert classify_os_death(2, "") is None


def _assert_scored_kill(body: dict[str, object], code: str) -> None:
    assert body["reward"] == 0.0
    assert body["infrastructure_error"] is None
    breakdown = body["breakdown"]
    assert isinstance(breakdown, dict)
    assert breakdown["C"] == 0.0
    assert breakdown["E"] == 0.0
    tests = body["tests"]
    assert isinstance(tests, dict)
    cases = tests["cases"]
    assert isinstance(cases, list)
    assert [case.get("id") for case in cases if isinstance(case, dict)] == [
        "h_forty_one",
        "h_property",
    ]
    assert tests["total"] == 2
    assert tests["passed"] == 0
    assert tests["failed"] == 2
    assert tests["trapped"] == 0
    assert all(
        isinstance(case, dict) and case.get("status") == "failed" and "trap" not in case
        for case in cases
    )
    diagnostics = body["diagnostics"]
    assert isinstance(diagnostics, list)
    assert any(isinstance(item, dict) and item.get("code") == code for item in diagnostics)


def test_stronger_backends_are_not_launched() -> None:
    assert backend_available("nsjail") is False
    assert backend_available("gvisor") is False
    assert _job_objects_usable() is False
    assert "unsupported" in WINDOWS_JOB_REASON
    with pytest.raises(IsolationUnavailable) as nsjail:
        resolve("nsjail")
    assert nsjail.value.code == "I9024"
    assert nsjail.value.message == "nsjail is not available"
    with pytest.raises(IsolationUnavailable) as gvisor:
        resolve("gvisor")
    assert gvisor.value.message == "gvisor is not available"


def test_default_backend_is_the_strongest_available() -> None:
    backend, warning = resolve(None)
    if bwrap_available() and sys.platform == "linux":
        assert backend == "bwrap"
        assert warning == "gvisor is not available; nsjail is not available"
    elif rlimit_available():
        assert backend == "rlimit"
        assert warning is not None
        assert "bwrap is not available" in warning
        assert "gvisor is not available" in warning
    else:
        assert backend == "none"
        assert warning is not None
        assert "rlimit is not available" in warning


def test_in_process_episode_records_no_isolation() -> None:
    task = load_task(EXAMPLE)
    episode = run_episode(task, task.reference_text, filename="reference/solution.tersa")
    assert episode.isolation == "none"
    assert episode.isolation_warning is None
    assert episode.reward == 1.0


def test_rlimit_memory_bomb_scores_as_failure() -> None:
    _need_rlimit()
    result = run_argv(
        [sys.executable, "-c", _MEMORY_BOMB],
        backend="rlimit",
        limits=OsLimits(address_bytes=64 * 1024 * 1024),
        timeout=20,
    )
    classified = classify_os_death(result.returncode, result.stderr)
    if classified is None and sys.platform != "linux":
        pytest.skip("this OS did not enforce the address cap")
    assert classified == ("T6206", MEMORY_MESSAGE)
    body = _episode(
        run_episode_isolated(
            EXAMPLE,
            EXAMPLE / "reference" / "solution.tersa",
            seed=0,
            attempt_id="memory",
            isolation="rlimit",
            os_limits=OsLimits(address_bytes=16 * 1024 * 1024),
        )
    )
    _assert_scored_kill(body, "T6206")
    assert body["isolation"] == "rlimit"


def test_rlimit_cpu_bomb_scores_as_failure() -> None:
    _need_rlimit()
    result = run_argv(
        [sys.executable, "-c", _CPU_BOMB],
        backend="rlimit",
        limits=OsLimits(cpu_seconds=1),
        timeout=15,
    )
    classified = classify_os_death(result.returncode, result.stderr)
    if classified is None and sys.platform != "linux":
        pytest.skip("RLIMIT_CPU did not deliver SIGXCPU on this host")
    assert classified == ("T6207", CPU_MESSAGE)
    body = _episode(
        run_episode_isolated(
            EXAMPLE,
            EXAMPLE / "reference" / "solution.tersa",
            seed=0,
            attempt_id="cpu",
            isolation="rlimit",
            os_limits=OsLimits(cpu_seconds=0),
        )
    )
    _assert_scored_kill(body, "T6207")
    assert body["isolation"] == "rlimit"


def test_os_kill_under_none_scores_as_failure() -> None:
    """Backend none applies no cap. A self-signal still scores 0."""
    if sys.platform == "win32":
        pytest.skip("POSIX signals are not delivered as wait statuses on Windows")
    attempt = EXAMPLE / "reference" / "solution.tersa"
    previous = os.environ.get("TERSALANG_HARNESS_SIGNAL")
    try:
        for name, code in (("SIGSEGV", "T6206"), ("SIGXCPU", "T6207")):
            os.environ["TERSALANG_HARNESS_SIGNAL"] = name
            body = _episode(
                run_episode_isolated(EXAMPLE, attempt, seed=0, attempt_id=name, isolation="none")
            )
            _assert_scored_kill(body, code)
            assert body["isolation"] == "none"
            assert body["reward"] == 0.0
    finally:
        if previous is None:
            os.environ.pop("TERSALANG_HARNESS_SIGNAL", None)
        else:
            os.environ["TERSALANG_HARNESS_SIGNAL"] = previous


def test_rlimit_fork_bomb_is_contained() -> None:
    _need_rlimit()
    counted = process_count()
    cap = (counted if counted is not None else 8) + 4
    result = run_argv(
        [sys.executable, "-c", _FORK_BOMB],
        backend="rlimit",
        limits=OsLimits(processes=cap),
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    parts = result.stdout.split()
    assert parts[0] == "stopped", result.stdout
    assert int(parts[1]) < 20
    if sys.platform == "linux":
        assert int(parts[1]) < 15


def test_rlimit_file_size_is_contained(tmp_path: Path) -> None:
    _need_rlimit()
    target = tmp_path / "big.bin"
    code = (
        "try:\n"
        f"    open({str(target)!r}, 'wb').write(b'x' * 200000)\n"
        "    print('wrote')\n"
        "except OSError as exc:\n"
        "    print('blocked', exc.errno)\n"
    )
    result = run_argv(
        [sys.executable, "-c", code],
        backend="rlimit",
        limits=OsLimits(file_bytes=4096),
        timeout=15,
    )
    assert result.stdout.startswith("blocked"), result.stdout
    assert not target.exists() or target.stat().st_size <= 4096


def test_bwrap_memory_and_fork_are_contained() -> None:
    _need_bwrap()
    memory = run_argv(
        [sys.executable, "-c", _MEMORY_BOMB],
        backend="bwrap",
        limits=OsLimits(address_bytes=64 * 1024 * 1024),
        timeout=20,
    )
    assert classify_os_death(memory.returncode, memory.stderr) == ("T6206", MEMORY_MESSAGE)
    # The pid namespace starts empty, so a small absolute cap is the limit.
    fork = run_argv(
        [sys.executable, "-c", _FORK_BOMB],
        backend="bwrap",
        limits=OsLimits(processes=8),
        timeout=15,
    )
    parts = fork.stdout.split()
    assert parts[0] == "stopped", fork.stdout
    assert int(parts[1]) < 20


def test_bwrap_network_and_outside_writes_are_contained() -> None:
    _need_bwrap()
    network = run_argv([sys.executable, "-c", _NETWORK], backend="bwrap", timeout=15)
    assert network.stdout.startswith("blocked"), network.stdout
    assert "connected" not in network.stdout
    escape = ROOT / "tersa-rh09-escape.txt"
    etc = Path("/etc/tersalang-escape")
    inside = Path(WORKSPACE) / "ok.txt"
    escape.unlink(missing_ok=True)
    inside.unlink(missing_ok=True)
    code = (
        "from pathlib import Path\n"
        f"escape = {str(escape)!r}\n"
        f"inside = {str(inside)!r}\n"
        "try:\n"
        "    Path(escape).write_text('no')\n"
        "    print('repo-wrote')\n"
        "except OSError as exc:\n"
        "    print('repo-blocked', exc.errno)\n"
        "try:\n"
        "    Path('/etc/tersalang-escape').write_text('no')\n"
        "    print('etc-wrote')\n"
        "except OSError as exc:\n"
        "    print('etc-blocked', exc.errno)\n"
        "Path(inside).write_text('ok')\n"
        "print('tmp-ok')\n"
    )
    try:
        result = run_argv([sys.executable, "-c", code], backend="bwrap", timeout=15)
    finally:
        escape.unlink(missing_ok=True)
    assert "repo-blocked 30" in result.stdout, result.stdout
    assert "etc-blocked 30" in result.stdout, result.stdout
    assert "tmp-ok" in result.stdout
    assert not escape.exists()
    assert not etc.exists()
    assert not inside.exists()


def test_bwrap_child_cannot_reach_the_callers_terminal() -> None:
    _need_bwrap()
    # getsid reports 0 when the session leader lives outside the sandbox's PID namespace,
    # which means the child still shares the caller's session and terminal.
    code = "import os\nprint(os.getsid(0))\n"
    result = run_argv([sys.executable, "-c", code], backend="bwrap", timeout=15)
    assert result.stdout.strip() not in {"", "0"}, result.stdout + result.stderr


def test_missing_backend_scores_as_infrastructure_failure() -> None:
    text = run_episode_isolated(
        EXAMPLE,
        EXAMPLE / "reference" / "solution.tersa",
        seed=0,
        attempt_id="missing",
        isolation="nsjail",
    )
    body = _episode(text)
    error = body["infrastructure_error"]
    assert isinstance(error, dict)
    assert error["code"] == "I9024"
    assert error["message"] == "nsjail is not available"
    assert body["reward"] is None
    assert body["isolation"] == "none"
    code = main(
        [
            "harness",
            "run",
            str(EXAMPLE),
            "--attempt",
            str(EXAMPLE / "reference" / "solution.tersa"),
            "--isolation",
            "gvisor",
        ]
    )
    assert code == 4


def test_normal_program_is_unchanged_apart_from_the_isolation_field() -> None:
    _need_rlimit()
    attempt = EXAMPLE / "reference" / "solution.tersa"
    first = run_episode_isolated(
        EXAMPLE, attempt, seed=0, attempt_id="reference", isolation="rlimit"
    )
    second = run_episode_isolated(
        EXAMPLE, attempt, seed=0, attempt_id="reference", isolation="rlimit"
    )
    assert first == second
    body = _episode(first)
    assert body["reward"] == 1.0
    assert body["isolation"] == "rlimit"
    assert body["isolation_warning"] is None
    assert body["schema"] == "tersa.result/0.9"
    if not bwrap_available():
        return
    wrapped = run_episode_isolated(
        EXAMPLE, attempt, seed=0, attempt_id="reference", isolation="bwrap"
    )
    again = run_episode_isolated(
        EXAMPLE, attempt, seed=0, attempt_id="reference", isolation="bwrap"
    )
    assert wrapped == again
    sandboxed = _episode(wrapped)
    assert sandboxed["reward"] == 1.0
    assert sandboxed["isolation"] == "bwrap"
    assert sandboxed["breakdown"] == body["breakdown"]


_PRINT_ENV = "import json, os\nprint(json.dumps(dict(os.environ)))\n"


@pytest.mark.parametrize("backend", ["none", "rlimit", "bwrap"])
def test_child_gets_only_the_allowlisted_environment(
    backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not backend_available(backend):
        pytest.skip(f"{backend} is not available on this host")
    monkeypatch.setenv("TERSALANG_PROBE_SECRET", "hunter2")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "hunter2")
    monkeypatch.setenv("TERSALANG_HARNESS_SIGNAL", "")
    result = run_argv([sys.executable, "-c", _PRINT_ENV], backend=backend, timeout=15)
    seen = json.loads(result.stdout)
    assert "hunter2" not in result.stdout
    assert "TERSALANG_HARNESS_SIGNAL" in seen
    expected = child_env()
    assert {name: seen.get(name) for name in expected} == expected
    # Python, bwrap, and the OS add their own names: LC_CTYPE (PEP 538), PWD,
    # macOS __CF_USER_TEXT_ENCODING, and the Windows venv __PYVENV_LAUNCHER__.
    extra = {
        name
        for name in set(seen) - set(expected)
        if name not in {"LC_CTYPE", "PWD"} and not name.startswith(("__", "="))
    }
    assert extra <= set(ENV_ALLOWLIST), extra


def test_child_env_points_at_the_parents_tersalang() -> None:
    env = child_env()
    assert env["PYTHONPATH"] == package_root()
    assert Path(package_root(), "tersalang", "__init__.py").is_file()
    assert set(env) - set(ENV_ALLOWLIST) == {
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONIOENCODING",
        "PYTHONNOUSERSITE",
        "PYTHONPATH",
        "PYTHONUTF8",
    }


def test_bwrap_sees_only_python_tersalang_and_the_bound_paths(tmp_path: Path) -> None:
    _need_bwrap()
    hidden = tmp_path / "hidden"
    shared = tmp_path / "shared"
    hidden.mkdir()
    shared.mkdir()
    (hidden / "secret.txt").write_text("no", encoding="utf-8")
    (shared / "task.txt").write_text("yes", encoding="utf-8")
    probes = {
        "repo_file": str(ROOT / "pyproject.toml"),
        "home": os.path.expanduser("~/.bashrc"),
        "passwd": "/etc/passwd",
        "host_tmp": str(hidden / "secret.txt"),
        "shared": str(shared / "task.txt"),
    }
    code = (
        "import errno, json, os, sys\n"
        "import tersalang\n"
        f"probes = {probes!r}\n"
        "seen = {name: os.path.exists(path) for name, path in probes.items()}\n"
        "try:\n"
        "    open(probes['shared'], 'w').close()\n"
        "    seen['shared_write'] = 'wrote'\n"
        "except OSError as exc:\n"
        "    seen['shared_write'] = errno.errorcode[exc.errno]\n"
        "seen['cwd'] = os.getcwd()\n"
        "print(json.dumps(seen))\n"
    )
    result = run_argv([sys.executable, "-c", code], backend="bwrap", timeout=15, read_only=[shared])
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout)
    assert seen == {
        "repo_file": False,
        "home": False,
        "passwd": False,
        "host_tmp": False,
        "shared": True,
        "shared_write": "EROFS",
        "cwd": WORKSPACE,
    }
    assert (shared / "task.txt").read_text(encoding="utf-8") == "yes"


def test_bwrap_binds_are_absolute_and_never_the_root(tmp_path: Path) -> None:
    binds = bwrap_read_only([tmp_path])
    assert "/" not in binds
    assert all(os.path.isabs(item) for item in binds)
    assert os.path.realpath(tmp_path) in binds
    for link, target in bwrap_symlinks([tmp_path]):
        assert os.path.islink(link)
        assert os.readlink(link) == target


def test_bwrap_episode_reads_a_task_and_attempt_outside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _need_bwrap()
    import shutil

    task = tmp_path / "task"
    shutil.copytree(EXAMPLE, task)
    elsewhere = tmp_path / "attempts"
    elsewhere.mkdir()
    attempt = elsewhere / "solution.tersa"
    attempt.write_bytes((EXAMPLE / "reference" / "solution.tersa").read_bytes())
    monkeypatch.chdir(tmp_path)
    text = run_episode_isolated(
        Path("task"),
        Path("attempts") / "solution.tersa",
        seed=0,
        attempt_id="reference",
        isolation="bwrap",
    )
    body = _episode(text)
    assert body["reward"] == 1.0, body
    assert body["isolation"] == "bwrap"
