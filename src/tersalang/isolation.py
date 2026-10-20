# SPDX-License-Identifier: Apache-2.0
"""OS isolation for the harness child: rlimits and bubblewrap.

Layer 2 is `setrlimit` on Linux and macOS. Windows job objects are not launched,
so Windows has no layer 2: the default there is `none` with a warning, and an
explicit `rlimit` is `I9024`. Layer 3–4 on Linux is bubblewrap. nsjail has no
launcher here. gVisor `runsc` needs host cgroup access this build does not use,
so an explicit request is refused instead of launched.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

BACKENDS = ("none", "rlimit", "bwrap", "nsjail", "gvisor")
# The only writable path inside bubblewrap. Everything else that is visible is
# bound read-only, and paths that are not bound do not exist.
WORKSPACE = "/tmp/tersalang-workspace"
# The only variables the child inherits. Windows cannot start Python without
# SYSTEMROOT. The TERSALANG_HARNESS_* names are test hooks read by the worker.
ENV_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "TERSALANG_HARNESS_CRASH",
    "TERSALANG_HARNESS_FORGE",
    "TERSALANG_HARNESS_SIGNAL",
)
# Shared libraries and the loader cache. A merged-/usr host has /lib and
# /lib64 as symlinks into /usr, which bubblewrap recreates as symlinks.
_SYSTEM_LINKS = ("/lib", "/lib32", "/lib64", "/libx32")
_SYSTEM_DIRS = ("/usr/lib", "/usr/lib32", "/usr/lib64", "/usr/libx32", "/etc/ld.so.cache")
_STRONGEST_FIRST = ("gvisor", "nsjail", "bwrap", "rlimit", "none")

# Catalog messages for the two scored OS traps. Callers emit these strings.
MEMORY_CODE = "T6206"
CPU_CODE = "T6207"
MEMORY_MESSAGE = "OS memory limit exceeded"
CPU_MESSAGE = "OS CPU limit exceeded"


class IsolationUnavailable(Exception):
    """The caller asked for a backend this host cannot launch; reported as `I9024`."""

    def __init__(self, backend: str) -> None:
        self.backend = backend
        self.code = "I9024"
        self.message = f"{backend} is not available"
        super().__init__(self.message)


@dataclass(frozen=True)
class OsLimits:
    """Hard OS caps applied to a child before it runs."""

    address_bytes: int = 4 * 1024**3
    cpu_seconds: int = 30
    file_bytes: int = 64 * 1024**2
    open_files: int = 256
    core_bytes: int = 0
    processes: int | None = None


@dataclass(frozen=True)
class SpawnResult:
    """How one child run ended.

    A timeout has `returncode` -1 and `timed_out` set, with whatever output the
    child wrote before it was killed.
    """

    returncode: int
    stdout: str
    stderr: str
    backend: str
    warning: str | None
    timed_out: bool


def rlimit_available() -> bool:
    """True when the host has `setrlimit` with an address-space cap; never on Windows."""
    if sys.platform == "win32":
        return False
    try:
        import resource
    except ImportError:
        return False
    return hasattr(resource, "RLIMIT_AS")


def bwrap_available() -> bool:
    """True when a `bwrap` executable is on `PATH`."""
    return shutil.which("bwrap") is not None


def backend_available(name: str) -> bool:
    """True when this build can launch `name` on the current host."""
    if name == "none":
        return True
    if name == "rlimit":
        if sys.platform == "win32":
            return _job_objects_usable()
        return rlimit_available()
    if name == "bwrap":
        return sys.platform == "linux" and bwrap_available()
    # nsjail is not packaged for the Ubuntu runner and has no launcher.
    # gVisor runsc hangs or is denied cgroup setup, so it is not launched.
    return False


def resolve(requested: str | None) -> tuple[str, str | None]:
    """Pick a backend. `None` means the strongest one that can launch.

    An explicit missing backend raises. The default records which stronger
    backends were skipped.
    """
    if requested is not None:
        if requested not in BACKENDS:
            raise IsolationUnavailable(requested)
        if not backend_available(requested):
            raise IsolationUnavailable(requested)
        return requested, None
    skipped: list[str] = []
    for name in _STRONGEST_FIRST:
        if backend_available(name):
            warning = None
            if skipped:
                warning = "; ".join(f"{item} is not available" for item in skipped)
            return name, warning
        if name != "none":
            skipped.append(name)
    return "none", None


def process_count() -> int | None:
    """Processes with this real uid, which is what `RLIMIT_NPROC` counts.

    `/proc` is Linux-only. Other hosts return `None` and the default
    process cap is left unset.
    """
    if sys.platform == "win32":
        return None
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    uid = str(os.getuid())
    count = 0
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            text = (entry / "status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("Uid:"):
                parts = line.split()
                if len(parts) > 1 and parts[1] == uid:
                    count += 1
                break
    return count or None


def apply_rlimits(limits: OsLimits) -> None:
    """Set resource limits in the child. Missing knobs are skipped."""
    if sys.platform == "win32":
        return
    import resource

    def _set(name: str, soft: int, hard: int) -> None:
        key = getattr(resource, name, None)
        if key is None:
            return
        try:
            resource.setrlimit(key, (soft, hard))
        except (OSError, ValueError):
            return

    _set("RLIMIT_CORE", limits.core_bytes, limits.core_bytes)
    _set("RLIMIT_NOFILE", limits.open_files, limits.open_files)
    _set("RLIMIT_FSIZE", limits.file_bytes, limits.file_bytes)
    cpu_hard = limits.cpu_seconds + 1
    _set("RLIMIT_CPU", limits.cpu_seconds, cpu_hard)
    _set("RLIMIT_AS", limits.address_bytes, limits.address_bytes)
    _set("RLIMIT_DATA", limits.address_bytes, limits.address_bytes)
    cap = limits.processes
    if cap is None:
        counted = process_count()
        cap = None if counted is None else counted + 64
    if cap is not None and cap > 0:
        _set("RLIMIT_NPROC", cap, cap)


def _signal_of(returncode: int) -> int | None:
    """Signal number from a wait status.

    A direct child killed by a signal has a negative code. bubblewrap exits
    `128 + signal` instead, because the sandboxed command is pid 1.
    """
    if returncode < 0:
        return -returncode
    if returncode > 128:
        return returncode - 128
    return None


def classify_os_death(returncode: int, stderr: str) -> tuple[str, str] | None:
    """Map an OS kill to a scored trap. A clean exit is not a kill.

    These deaths are the candidate's own resource use. The same mapping
    applies under every backend, including `none`.
    """
    if "MemoryError" in stderr:
        return MEMORY_CODE, MEMORY_MESSAGE
    sig = _signal_of(returncode)
    if sig is None:
        return None
    if sig == getattr(signal, "SIGXCPU", 24):
        return CPU_CODE, CPU_MESSAGE
    if sig in {
        getattr(signal, "SIGKILL", 9),
        getattr(signal, "SIGSEGV", 11),
        getattr(signal, "SIGBUS", 7),
        getattr(signal, "SIGABRT", 6),
    }:
        return MEMORY_CODE, MEMORY_MESSAGE
    return None


# Applies limits, then replaces this process. The interpreter starts under the
# cap, and bubblewrap itself is not capped so it can build the namespaces.
_LAUNCH = (
    "import json, os, sys\n"
    "from tersalang.isolation import OsLimits, apply_rlimits\n"
    "spec = json.loads(sys.argv[1])\n"
    "apply_rlimits(OsLimits(**spec['limits']))\n"
    "os.execv(spec['argv'][0], spec['argv'])\n"
)


def _launch_argv(argv: list[str], limits: OsLimits) -> list[str]:
    spec = json.dumps({"limits": asdict(limits), "argv": argv})
    return [sys.executable, "-c", _LAUNCH, spec]


def run_argv(
    argv: list[str],
    *,
    backend: str,
    stdin: str = "",
    limits: OsLimits | None = None,
    timeout: float = 30.0,
    cwd: str | None = None,
    read_only: Sequence[str | Path] = (),
) -> SpawnResult:
    """Run `argv` under `backend`. The parent stays up if the child dies.

    The child gets only `child_env()`. Under bubblewrap it sees the Python
    install, the tersalang package, the system libraries, `read_only`, and
    an empty `WORKSPACE`. `read_only` paths must be absolute.
    """
    chosen = limits or OsLimits()
    if sys.platform == "win32" and backend == "rlimit":
        raise IsolationUnavailable("rlimit")
    if backend in {"rlimit", "bwrap"} and rlimit_available():
        argv = _launch_argv(argv, chosen)
    if backend == "bwrap":
        argv = _bwrap_argv(argv, read_only)
    try:
        completed = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            cwd=cwd,
            env=child_env(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return SpawnResult(-1, stdout, stderr, backend, None, True)
    return SpawnResult(
        completed.returncode,
        completed.stdout,
        completed.stderr,
        backend,
        None,
        False,
    )


def package_root() -> str:
    """The directory that holds the `tersalang` package the parent imported."""
    import tersalang

    return str(Path(tersalang.__file__).resolve().parent.parent)


def child_env() -> dict[str, str]:
    """The child's whole environment: the allowlist plus fixed Python settings."""
    env = {name: os.environ[name] for name in ENV_ALLOWLIST if name in os.environ}
    env.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
        PYTHONNOUSERSITE="1",
        PYTHONPATH=package_root(),
        PYTHONUTF8="1",
    )
    return env


def _wanted(extra: Sequence[str | Path]) -> list[str]:
    return [
        sys.executable,
        sys.prefix,
        sys.base_prefix,
        sys.exec_prefix,
        sys.base_exec_prefix,
        package_root(),
        *_SYSTEM_LINKS,
        *_SYSTEM_DIRS,
        *(str(item) for item in extra),
    ]


def _symlink_hops(path: str) -> list[tuple[str, str]]:
    """Every `(link, target)` met while resolving `path` one part at a time."""
    hops: list[tuple[str, str]] = []
    current = Path("/")
    parts = list(Path(path).parts[1:])
    while parts and len(hops) < 40:
        part = parts.pop(0)
        if part == "..":
            current = current.parent
            continue
        candidate = current / part
        if not candidate.is_symlink():
            current = candidate
            continue
        target = os.readlink(candidate)
        hops.append((str(candidate), target))
        if os.path.isabs(target):
            current = Path("/")
            parts = list(Path(target).parts[1:]) + parts
        else:
            parts = list(Path(target).parts) + parts
    return hops


def bwrap_read_only(extra: Sequence[str | Path] = ()) -> list[str]:
    """Real paths bound read-only under bubblewrap, outermost first, none nested."""
    wanted = _wanted(extra)
    executable = Path(os.path.realpath(sys.executable))
    found = {os.path.realpath(item) for item in wanted if os.path.exists(item)}
    found.add(str(executable.parent.parent))
    found.discard(str(executable))
    kept: list[str] = []
    for item in sorted(found, key=lambda path: (len(Path(path).parts), path)):
        if not any(Path(item).is_relative_to(parent) for parent in kept):
            kept.append(item)
    return kept


def bwrap_symlinks(extra: Sequence[str | Path] = ()) -> list[tuple[str, str]]:
    """Symlinks recreated under bubblewrap so each wanted path resolves the same way."""
    bound = bwrap_read_only(extra)
    links: dict[str, str] = {}
    for item in _wanted(extra):
        if not os.path.lexists(item):
            continue
        for link, target in _symlink_hops(item):
            if not any(Path(link).is_relative_to(parent) for parent in bound):
                links.setdefault(link, target)
    return sorted(links.items())


def _bwrap_argv(inner: list[str], extra: Sequence[str | Path] = ()) -> list[str]:
    bwrap = shutil.which("bwrap") or "bwrap"
    mounts: list[str] = []
    for path in bwrap_read_only(extra):
        mounts += ["--ro-bind", path, path]
    for link, target in bwrap_symlinks(extra):
        mounts += ["--symlink", target, link]
    # A user namespace is what lets a non-root bubblewrap configure the
    # sandbox network namespace. Ubuntu's AppArmor policy blocks that until
    # the CI job relaxes it for the disposable runner.
    return [
        bwrap,
        "--die-with-parent",
        # Without a new session the child can push keystrokes into the caller's
        # terminal with TIOCSTI (CVE-2017-5226).
        "--new-session",
        "--unshare-user",
        "--uid",
        "0",
        "--gid",
        "0",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        *mounts,
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        WORKSPACE,
        "--remount-ro",
        "/",
        "--chdir",
        WORKSPACE,
        "--cap-drop",
        "ALL",
        "--",
        *inner,
    ]


def _job_objects_usable() -> bool:
    """Windows Job Objects are not launched.

    `subprocess` starts the child before a job can be assigned, and a nested
    job is commonly denied on hosted runners. Layer 2 on Windows falls back.
    """
    return False


WINDOWS_JOB_REASON = (
    "Windows job objects are unsupported in this build: a child would start "
    "before the job could be assigned, and nested jobs are commonly denied"
)
