"""Isolated working copies, and the only place model-written code is executed.

Runs use a macOS sandbox profile: no network, no writes outside the copy, and no
reads of the home folder. If the sandbox is unavailable the run is refused, never
run without it.
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
OUTPUT_LIMIT = 6000
MAX_FILE_BYTES = 100_000
SKIP = {".git", "__pycache__", ".pytest_cache"}
ALLOWED_COMMAND = re.compile(r"^python3? -m (unittest|pytest)( [\w./=:-]+)*$")


class SandboxError(RuntimeError):
    pass


def available():
    return Path(SANDBOX_EXEC).exists() and not Path(os.path.realpath(sys.executable)).is_relative_to(Path.home())


def copy_repo(path, destination):
    shutil.copytree(path, destination, symlinks=True, ignore=shutil.ignore_patterns(*SKIP))
    return destination


def _profile(work):
    root = str(Path(work).resolve())
    return f"""(version 1)(allow default)(deny network*)(deny file-write*)
(allow file-write* (subpath "{root}") (literal "/dev/null"))
(deny file-read* (subpath "{Path.home()}"))
(allow file-read* (subpath "{root}"))"""


def run_command(work, command, timeout):
    """Runs one allowlisted test command, parsed without a shell."""
    if not ALLOWED_COMMAND.match(command.strip()):
        return {"code": None, "output": "Refused. Only 'python -m unittest ...' or 'python -m pytest ...' may run."}
    if not available():
        raise SandboxError("The macOS sandbox is unavailable, so model-written code was not run.")
    args = shlex.split(command)
    args[0] = os.path.realpath(sys.executable)
    with tempfile.TemporaryDirectory(prefix="agentready-profile-") as tmp:
        profile = Path(tmp) / "run.sb"
        profile.write_text(_profile(work), encoding="utf-8")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(work), "TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            done = subprocess.run([SANDBOX_EXEC, "-f", str(profile), *args], cwd=work, env=env,
                                  capture_output=True, text=True, timeout=timeout)
            return {"code": done.returncode, "output": (done.stdout + done.stderr)[-OUTPUT_LIMIT:]}
        except subprocess.TimeoutExpired:
            return {"code": 124, "output": f"Timed out after {timeout} seconds"}


class Workspace:
    """File access confined to one directory. Writes are off unless asked for."""

    def __init__(self, root, writable=False):
        self.root = Path(root).resolve()
        self.writable = writable
        self.read_paths = set()

    def _resolve(self, rel):
        target = (self.root / str(rel).lstrip("/")).resolve()
        if target != self.root and not target.is_relative_to(self.root):
            raise ValueError("Path is outside the repository.")
        if ".git" in target.relative_to(self.root).parts:
            raise ValueError("Path is not allowed.")
        return target

    def files(self):
        rows = []
        for base, dirs, names in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP]
            rows += [(Path(base) / n).relative_to(self.root).as_posix() for n in names if not (Path(base) / n).is_symlink()]
        return sorted(rows)

    def list_files(self, path=""):
        prefix = str(path or "").strip("./")
        return "\n".join(f for f in self.files() if f.startswith(prefix)) or "No files."

    def read_file(self, path):
        target = self._resolve(path)
        if not target.is_file():
            return f"{path} does not exist."
        self.read_paths.add(target.relative_to(self.root).as_posix())
        return target.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_BYTES]

    def search(self, text):
        hits = []
        for rel in self.files():
            content = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            hits += [f"{rel}:{n}: {line.strip()}" for n, line in enumerate(content.splitlines(), 1) if str(text) in line]
        return "\n".join(hits[:40]) or "No matches."

    def write_file(self, path, content):
        if not self.writable:
            raise ValueError("This agent cannot change files.")
        target = self._resolve(path)
        if target == self.root or target.is_symlink():
            raise ValueError("Path is not allowed.")
        if len(str(content)) > MAX_FILE_BYTES:
            raise ValueError("File is too large.")
        rel = target.relative_to(self.root).as_posix()
        if target.exists() and rel not in self.read_paths:
            raise ValueError(f"Read {rel} before you change it, so that nothing in it is lost.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        self.read_paths.add(rel)
        return f"Wrote {rel}."

    def quote_in_file(self, path, quote):
        target = self.root / path
        if not target.is_file():
            return False
        normal = lambda text: "".join(text.replace(",", " ").split()).lower()
        return normal(quote) in normal(target.read_text(encoding="utf-8", errors="replace"))


def repo_diff(before, after):
    import difflib
    a, b = Workspace(before), Workspace(after)
    chunks, changed = [], []
    for rel in sorted(set(a.files()) | set(b.files())):
        old = (a.root / rel).read_text(encoding="utf-8", errors="replace") if (a.root / rel).is_file() else ""
        new = (b.root / rel).read_text(encoding="utf-8", errors="replace") if (b.root / rel).is_file() else ""
        if old != new:
            changed.append(rel)
            chunks += difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{rel}", f"b/{rel}", lineterm="")
    return changed, "\n".join(chunks)
