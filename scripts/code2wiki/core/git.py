"""Git history analysis.

Runs ``git log`` / ``git shortlog`` against the project root to surface:
  - Hot files (most-touched in the last N months)
  - Active contributors
  - Business keywords mined from commit messages
  - Per-domain activity (hot files mapped to their FileInfo domain)

The analysis is language-agnostic — it walks the FileInfo records produced by
whichever plugin scanned the project, so a Python project's hot files are
mapped to the Python plugin's domain assignments.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

from code2wiki.core.io import write
from code2wiki.core.markdown import md_table
from code2wiki.core.models import GitContext


# ──────────────────────────────────────────────────────────────────────────────
# Configuration knobs
# ──────────────────────────────────────────────────────────────────────────────

# Generic Chinese commit-message words filtered out of the keyword extractor —
# they describe the change action ("修复", "优化", …) rather than business
# vocabulary.
_GENERIC_COMMIT_WORDS = {
    "修改", "修复", "优化", "更新", "调整", "添加", "新增", "删除", "重构",
    "合并", "提交", "测试", "代码", "功能", "逻辑", "接口", "方法", "配置",
    "处理", "问题", "需求", "开发", "上线", "版本", "分支", "合入",
}


# ──────────────────────────────────────────────────────────────────────────────
# Git subprocess helper
# ──────────────────────────────────────────────────────────────────────────────

def _git_cmd(project: Path, args: list[str], timeout: int = 30) -> str | None:
    """Run a git command in ``project``; return stdout or None on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project)] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# History analysis
# ──────────────────────────────────────────────────────────────────────────────

def analyze_git_history(project: Path, infos: list, top_domains: list[str],
                         months: int = 6,
                         file_pathspec: str = "*.java") -> GitContext:
    """Build a :class:`GitContext` from the project's git log.

    Args:
      project: Project root (must contain a ``.git`` dir or be inside a worktree).
      infos: FileInfo list — used to translate hot-file paths into domains.
      top_domains: Domain whitelist applied to per-domain activity counters.
      months: How far back to look. Defaults to 6.
      file_pathspec: ``--`` pathspec passed to ``git log`` for hot-file
        detection. Defaults to ``*.java`` for backward compatibility with the
        legacy Java pipeline; plugins should override this when they call
        directly (e.g. ``*.py`` for Python).

    Returns an empty :class:`GitContext` when the project is not a git repo.
    """
    ctx = GitContext()

    if _git_cmd(project, ["rev-parse", "--is-inside-work-tree"]) is None:
        return ctx
    ctx.is_git_repo = True

    since = f"{months} months ago"

    # Hot files
    raw = _git_cmd(project, ["log", f"--since={since}", "--format=",
                              "--name-only", "--diff-filter=AMRC", "--", file_pathspec])
    if raw:
        file_counter = Counter(line.strip() for line in raw.splitlines() if line.strip())
        ctx.hot_files = [{"path": path, "count": count}
                         for path, count in file_counter.most_common(50)]

    # Commit messages → recent commits + business keywords
    raw = _git_cmd(project, ["log", f"--since={since}", "--format=%s", "-200"])
    if raw:
        ctx.recent_commits = [line.strip() for line in raw.splitlines() if line.strip()][:200]
        all_text = " ".join(ctx.recent_commits)
        cn_words = re.findall(r"[一-鿿]{2,8}", all_text)
        word_counter = Counter(cn_words)
        ctx.commit_keywords = [w for w, c in word_counter.most_common(30)
                                if w not in _GENERIC_COMMIT_WORDS and c >= 2][:15]

    # Contributors
    raw = _git_cmd(project, ["shortlog", "-sne", f"--since={since}", "HEAD"])
    if raw:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                count_str = parts[0].strip()
                name_email = parts[1].strip()
                name = name_email.split("<")[0].strip() if "<" in name_email else name_email
                try:
                    ctx.contributors.append({"name": name, "count": int(count_str)})
                except ValueError:
                    pass

    # Per-domain activity (only counts whitelisted top_domains)
    if ctx.hot_files:
        path_to_domain: dict[str, str] = {info.path: info.domain for info in infos}
        domain_commits: Counter[str] = Counter()
        for hf in ctx.hot_files:
            domain = path_to_domain.get(hf["path"], "unknown")
            if domain in top_domains:
                domain_commits[domain] += hf["count"]
        ctx.domain_activity = dict(domain_commits.most_common(20))

    return ctx


# ──────────────────────────────────────────────────────────────────────────────
# Report generation
# ──────────────────────────────────────────────────────────────────────────────

def generate_git_activity(output: Path, git_ctx: GitContext, top_domains: list[str]) -> None:
    """Write ``05_indexes/git_activity.md`` from a :class:`GitContext`."""
    if not git_ctx.is_git_repo:
        write(output / "05_indexes" / "git_activity.md",
              "# Git Activity\n\n本项目不是 git 仓库或无法访问 git 历史。\n")
        return

    content = "# Git Activity（近 6 个月）\n\n"

    if git_ctx.domain_activity:
        content += "## 业务域活跃度\n\n"
        content += "近期 commit 涉及文件数越多，说明该域越活跃，BCL 越需要保持更新。\n\n"
        activity_rows = [[domain, str(count)] for domain, count in
                          sorted(git_ctx.domain_activity.items(), key=lambda x: -x[1])]
        content += md_table(["业务域", "变更文件次数"], activity_rows, 20) + "\n\n"

    if git_ctx.hot_files:
        content += "## 热点文件 Top 30\n\n"
        content += "高频改动的文件通常是业务核心，AI 富化时应优先阅读。\n\n"
        hot_rows = [[hf["path"], str(hf["count"])] for hf in git_ctx.hot_files[:30]]
        content += md_table(["文件", "变更次数"], hot_rows, 30) + "\n\n"

    if git_ctx.commit_keywords:
        content += "## Commit 消息业务关键词\n\n"
        content += "从 commit 消息中高频出现的业务词（可补充到 business_terms.md）：\n\n"
        content += ", ".join(f"**{w}**" for w in git_ctx.commit_keywords) + "\n\n"

    if git_ctx.contributors:
        content += "## 活跃贡献者\n\n"
        contrib_rows = [[c["name"], str(c["count"])] for c in git_ctx.contributors[:15]]
        content += md_table(["贡献者", "Commit 数"], contrib_rows, 15) + "\n\n"

    if git_ctx.recent_commits:
        content += "## 近期 Commit 消息（最新 20 条）\n\n"
        for msg in git_ctx.recent_commits[:20]:
            content += f"- {msg}\n"
        content += "\n"

    write(output / "05_indexes" / "git_activity.md", content)
