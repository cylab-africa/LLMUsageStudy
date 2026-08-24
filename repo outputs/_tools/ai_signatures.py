#!/usr/bin/env python3
"""
Single source of truth for AI-tool signatures used across the AI-Impact pipeline.

Three families of signatures:
  * PATH_SIGS  — config/marker files an AI *coding* agent commits into the repo
  * TEXT_SIGS  — author/committer identity + commit-message trailers a coding
                 agent leaves (how Claude Code, Copilot, Cursor, Aider, ... sign)
  * REVIEW_BOTS — logins of AI *code-review* bots that leave reviews/comments on
                 PRs (distinct from a coding agent that writes commits)

`detect_ai_agents.py`, `collect_review_metrics.py`, and the orchestrator all
import from here so the tables never drift apart.
"""
import re

# ---- Coding-agent file-path signatures (matched against changed paths) --------
PATH_SIGS = {
    "Cursor": [r"(^|/)\.cursorrules$", r"(^|/)\.cursorignore$", r"(^|/)\.cursor/"],
    "Claude Code": [r"(^|/)CLAUDE\.md$", r"(^|/)CLAUDE\.local\.md$",
                    r"(^|/)\.claude/", r"(^|/)\.mcp\.json$"],
    "GitHub Copilot": [r"(^|/)\.github/copilot-instructions\.md$",
                       r"(^|/)\.github/instructions/", r"(^|/)\.github/prompts/"],
    "Windsurf": [r"(^|/)\.windsurfrules$", r"(^|/)\.windsurf/"],
    "Codeium": [r"(^|/)\.codeium/"],
    "Cline": [r"(^|/)\.clinerules"],
    "Roo Code": [r"(^|/)\.roo/", r"(^|/)\.roorules"],
    "Aider": [r"(^|/)\.aider\.conf\.ya?ml$", r"(^|/)\.aiderignore$",
              r"(^|/)CONVENTIONS\.md$"],
    "Continue": [r"(^|/)\.continue/", r"(^|/)\.continuerc"],
    "Sourcegraph Cody": [r"(^|/)\.cody/", r"(^|/)\.sourcegraph/"],
    "Gemini": [r"(^|/)GEMINI\.md$", r"(^|/)\.gemini/", r"(^|/)\.idx/airules\.md$"],
    "OpenAI Codex / AGENTS.md": [r"(^|/)AGENTS\.md$", r"(^|/)\.codex/"],
    "Amazon Q": [r"(^|/)\.amazonq/"],
    "Tabnine": [r"(^|/)\.tabnine"],
    "Junie (JetBrains)": [r"(^|/)\.junie/"],
    "Kilo Code": [r"(^|/)\.kilocode/"],
    "Zed AI": [r"(^|/)\.zed/"],
    "Qodo / Codium": [r"(^|/)\.qodo/"],
}

# ---- Coding-agent identity + commit-message signatures ------------------------
TEXT_SIGS = {
    "Claude Code": [r"co-authored-by:\s*claude", r"noreply@anthropic\.com",
                    r"generated with \[?claude code", r"claude\.ai/code"],
    "GitHub Copilot": [r"co-authored-by:\s*copilot", r"copilot-swe-agent",
                       r"\bcopilot\b.*\[bot\]", r"175728472\+copilot"],
    "Cursor": [r"co-authored-by:\s*cursor", r"\bcursoragent\b",
               r"cursor agent", r"@cursor\.com"],
    "Devin": [r"devin-ai-integration\[bot\]", r"\bdevin\b.*cognition"],
    "Aider": [r"\baider\b\s*\(aider\)", r"^\s*aider:", r"co-authored-by:\s*aider"],
    "OpenAI Codex": [r"co-authored-by:\s*chatgpt", r"\bcodex\b.*openai",
                     r"chatgpt@openai"],
    "Gemini": [r"gemini-code-assist\[bot\]", r"generated with gemini",
               r"google-labs-jules\[bot\]"],
    "Sweep": [r"sweep-ai\[bot\]"],
    "Sourcegraph Cody": [r"\bcody\b.*sourcegraph", r"sourcegraph\.com"],
}

# ---- AI code-review bots (matched against PR reviewer / commenter login) -------
REVIEW_BOTS = {
    "GitHub Copilot review": [r"copilot-pull-request-reviewer\[bot\]",
                              r"copilot-pull-request-reviewer"],
    "CodeRabbit": [r"coderabbitai\[bot\]", r"coderabbitai", r"coderabbit"],
    "Sourcery": [r"sourcery-ai\[bot\]", r"sourcery-ai"],
    "Qodo Merge / PR-Agent": [r"qodo-merge-pro\[bot\]", r"qodo-merge-pro-for-open-source\[bot\]",
                              r"codiumai-pr-agent\[bot\]", r"pr-agent"],
    "Ellipsis": [r"ellipsis-dev\[bot\]", r"ellipsis-dev"],
    "Greptile": [r"greptile-apps\[bot\]", r"greptile"],
    "Bito": [r"bito-code-review\[bot\]", r"bito"],
    "DeepSource": [r"deepsource-autofix\[bot\]", r"deepsource\[bot\]", r"deepsource"],
    "Codacy": [r"codacy-production\[bot\]", r"codacy"],
    "Graphite / Diamond": [r"graphite-app\[bot\]", r"diamond"],
    "Korbit": [r"korbit-ai\[bot\]", r"korbit"],
    "Cursor BugBot": [r"cursor\[bot\]", r"bugbot"],
}

# ---- AI *coding* agents that act as GitHub accounts (open PRs, push, commit) --
# Matched against a GitHub actor/login (author, committer, PR author, merged_by).
CODING_AGENT_LOGINS = {
    "GitHub Copilot": [r"^copilot-swe-agent(\[bot\])?$", r"^copilot(\[bot\])?$",
                       r"175728472\+copilot"],
    "Devin": [r"^devin-ai-integration(\[bot\])?$", r"\bdevin-ai\b"],
    "Cursor": [r"^cursoragent$", r"^cursor(\[bot\])?$"],
    "Claude Code": [r"^claude(\[bot\])?$", r"claude-code", r"anthropic"],
    "OpenAI Codex": [r"^chatgpt-codex-connector(\[bot\])?$", r"^codex(\[bot\])?$"],
    "Gemini": [r"gemini-code-assist(\[bot\])?", r"google-labs-jules(\[bot\])?"],
    "Sweep": [r"sweep-ai(\[bot\])?"],
    "Aider": [r"^aider(\[bot\])?$"],
    "Sourcegraph Cody": [r"sourcegraph-cody", r"^cody(\[bot\])?$"],
}

# Pre-compiled variants (case-insensitive; multiline for text bodies).
PATH_RES = {a: [re.compile(p, re.I) for p in ps] for a, ps in PATH_SIGS.items()}
TEXT_RES = {a: [re.compile(p, re.I | re.M) for p in ps] for a, ps in TEXT_SIGS.items()}
REVIEW_RES = {a: [re.compile(p, re.I) for p in ps] for a, ps in REVIEW_BOTS.items()}
CODING_LOGIN_RES = {a: [re.compile(p, re.I) for p in ps]
                    for a, ps in CODING_AGENT_LOGINS.items()}


def match_review_bot(login):
    """Return the review-bot product name for a reviewer login, or None."""
    if not login:
        return None
    for name, res in REVIEW_RES.items():
        if any(r.search(login) for r in res):
            return name
    return None


def match_login(login):
    """Classify a GitHub actor login into (agent, category).

    category is one of:
      'review'    — a known AI code-review bot (CodeRabbit, Copilot review, ...)
      'coding'    — a known AI coding agent acting as an account (Devin, Copilot
                    SWE agent, Cursor agent, ...)
      'other-bot' — some other automation ([bot] suffix) that is NOT a known AI
                    tool (dependabot, CI, release bots) — recorded for
                    transparency but never counted as AI adoption
    Returns (None, None) for ordinary human logins.
    """
    if not login:
        return None, None
    rev = match_review_bot(login)
    if rev:
        return rev, "review"
    for name, res in CODING_LOGIN_RES.items():
        if any(r.search(login) for r in res):
            return name, "coding"
    if login.endswith("[bot]") or login.endswith("-bot"):
        return login, "other-bot"
    return None, None
