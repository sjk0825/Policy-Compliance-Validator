import os
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class BuildInfo:
    commit: str
    commit_short: str
    branch: str
    dirty: bool

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _read_git_dir() -> tuple[Optional[str], Optional[str]]:
    """git 실행 파일이 없는 환경(컨테이너 등)을 위한 .git 직접 파싱."""
    head_file = _REPO_ROOT / ".git" / "HEAD"
    if not head_file.exists():
        return None, None

    head = head_file.read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head, "HEAD"

    ref = head[5:]
    branch = ref.rsplit("/", 1)[-1]

    ref_file = _REPO_ROOT / ".git" / ref
    if ref_file.exists():
        return ref_file.read_text(encoding="utf-8").strip(), branch

    packed = _REPO_ROOT / ".git" / "packed-refs"
    if packed.exists():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or " " not in line:
                continue
            sha, name = line.split(" ", 1)
            if name.strip() == ref:
                return sha, branch

    return None, branch


def _resolve() -> BuildInfo:
    # 이미지 빌드 시 주입한 값이 있으면 최우선 (컨테이너에는 .git이 없다)
    commit = os.getenv("GIT_COMMIT")
    branch = os.getenv("GIT_BRANCH")
    dirty: Optional[bool] = None

    if not commit:
        commit = _git("rev-parse", "HEAD")
    if not branch:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if commit is None or branch is None:
        file_commit, file_branch = _read_git_dir()
        commit = commit or file_commit
        branch = branch or file_branch

    status = _git("status", "--porcelain")
    if status is not None:
        dirty = bool(status)

    commit = commit or "unknown"
    return BuildInfo(
        commit=commit,
        commit_short=commit[:7],
        branch=branch or "unknown",
        dirty=bool(dirty),
    )


_CACHED: Optional[BuildInfo] = None


def current_build() -> BuildInfo:
    """프로세스 기동 시점의 빌드 정보. 판정마다 재계산하지 않는다."""
    global _CACHED
    if _CACHED is None:
        _CACHED = _resolve()
    return _CACHED
