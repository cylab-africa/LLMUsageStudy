#!/usr/bin/env python3
"""
Single source of truth for AI-tool signatures used across the AI-Impact pipeline.

Families of signatures:
  * PATH_SIGS   — config/marker files an AI *coding* agent commits into the repo
  * TEXT_SIGS   — author/committer identity + commit-message trailers a coding
                  agent leaves (how Claude Code, Copilot, Cursor, Aider, ... sign)
  * REVIEW_BOTS — logins of AI *code-review* bots that leave reviews/comments on
                  PRs (distinct from a coding agent that writes commits)
  * CODING_AGENT_LOGINS    — unambiguous agent account logins / e-mail slugs
  * AMBIGUOUS_AGENT_LOGINS — bare product first names ("claude", "cody", ...)
                  that a *human* may also be called; only accepted together with
                  a bot marker (see `match_login`)
  * AGENT_EMAIL_SIGS — commit e-mail addresses that identify an agent by itself

`detect_ai_agents.py`, `collect_review_metrics.py`, and the orchestrator all
import from here so the tables never drift apart.
"""
import re
from typing import Dict, List, Optional, Pattern, Tuple

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
    # NOTE: bare vendor domains (@cursor.com, sourcegraph.com) are deliberately
    # absent here. TEXT_RES is matched against a blob that includes %ae/%ce, so a
    # domain pattern flags every human employee of that vendor as the agent
    # itself. The precise robot addresses live in AGENT_EMAIL_SIGS below.
    "Cursor": [r"co-authored-by:\s*cursor", r"\bcursoragent\b",
               r"cursor agent"],
    "Devin": [r"devin-ai-integration\[bot\]", r"\bdevin\b.*cognition"],
    "Aider": [r"\baider\b\s*\(aider\)", r"^\s*aider:", r"co-authored-by:\s*aider"],
    "OpenAI Codex": [r"co-authored-by:\s*chatgpt", r"\bcodex\b.*openai",
                     r"chatgpt@openai"],
    "Gemini": [r"gemini-code-assist\[bot\]", r"generated with gemini",
               r"google-labs-jules\[bot\]"],
    "Sweep": [r"sweep-ai\[bot\]"],
    "Sourcegraph Cody": [r"\bcody\b.*sourcegraph"],
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
# Matched against an account LOGIN (GitHub actor / bot account / e-mail slug) —
# never against a git display name (%an/%cn), which is free-form text a human may
# legitimately set to "Claude" or "Cody". Every pattern here is unambiguous on
# its own: a full bot login, a vendor slug, or a vendor account id.
CODING_AGENT_LOGINS = {
    "GitHub Copilot": [r"^copilot-swe-agent(\[bot\])?$", r"^copilot\[bot\]$",
                       r"175728472\+copilot"],
    "Devin": [r"^devin-ai-integration(\[bot\])?$", r"\bdevin-ai\b"],
    "Cursor": [r"^cursoragent$", r"^cursor\[bot\]$"],
    "Claude Code": [r"^claude\[bot\]$", r"claude-code", r"^anthropic(\[bot\])?$"],
    "OpenAI Codex": [r"^chatgpt-codex-connector(\[bot\])?$", r"^codex\[bot\]$"],
    "Gemini": [r"gemini-code-assist(\[bot\])?", r"google-labs-jules(\[bot\])?"],
    "Sweep": [r"sweep-ai(\[bot\])?"],
    "Aider": [r"^aider\[bot\]$"],
    "Sourcegraph Cody": [r"sourcegraph-cody", r"^cody\[bot\]$"],
}

# Bare product first names. These are ALSO ordinary human first names / words, so
# they only classify when an independent bot marker is present (see
# `_has_bot_marker`). Matched against the login with any bot suffix stripped.
AMBIGUOUS_AGENT_LOGINS = {
    "GitHub Copilot": [r"^copilot$"],
    "Devin": [r"^devin$"],
    "Cursor": [r"^cursor$"],
    "Claude Code": [r"^claude$"],
    "OpenAI Codex": [r"^codex$", r"^chatgpt$"],
    "Gemini": [r"^gemini$", r"^jules$"],
    "Sweep": [r"^sweep$"],
    "Aider": [r"^aider$"],
    "Sourcegraph Cody": [r"^cody$"],
}

# ---- Commit e-mail addresses that identify a coding agent on their own ---------
# Anchored on the vendor's *robot* address only; a plain corporate address
# (someone@anthropic.com, someone@sourcegraph.com) is a human employee, not an
# agent, and is deliberately absent.
AGENT_EMAIL_SIGS = {
    "GitHub Copilot": [r"^\d+\+copilot(-swe-agent)?@users\.noreply\.github\.com$",
                       r"^copilot(-swe-agent)?\[bot\]@"],
    "Devin": [r"^devin-ai-integration\[bot\]@"],
    "Cursor": [r"^cursoragent@cursor\.com$", r"^cursor(\[bot\])?@cursor\.com$"],
    "Claude Code": [r"^noreply@anthropic\.com$", r"^claude(\[bot\])?@anthropic\.com$"],
    "OpenAI Codex": [r"^chatgpt-codex-connector\[bot\]@", r"^chatgpt@openai\.com$",
                     r"^codex@openai\.com$"],
    "Gemini": [r"^gemini-code-assist\[bot\]@", r"^google-labs-jules\[bot\]@"],
    "Sweep": [r"^sweep-ai\[bot\]@"],
    "Sourcegraph Cody": [r"^cody@sourcegraph\.com$", r"^sourcegraph-cody@"],
}

# Vendor robot domains: an address here is a bot marker for a bare product name.
BOT_EMAIL_DOMAINS = (
    "anthropic.com", "cursor.com", "cognition.ai", "devin.ai", "sweep.dev",
    "sourcegraph.com", "coderabbit.ai", "codium.ai", "qodo.ai",
)

# Pre-compiled variants (case-insensitive; multiline for text bodies).
PATH_RES = {a: [re.compile(p, re.I) for p in ps] for a, ps in PATH_SIGS.items()}
TEXT_RES = {a: [re.compile(p, re.I | re.M) for p in ps] for a, ps in TEXT_SIGS.items()}
REVIEW_RES = {a: [re.compile(p, re.I) for p in ps] for a, ps in REVIEW_BOTS.items()}
CODING_LOGIN_RES = {a: [re.compile(p, re.I) for p in ps]
                    for a, ps in CODING_AGENT_LOGINS.items()}
AMBIGUOUS_LOGIN_RES = {a: [re.compile(p, re.I) for p in ps]
                       for a, ps in AMBIGUOUS_AGENT_LOGINS.items()}
AGENT_EMAIL_RES = {a: [re.compile(p, re.I) for p in ps]
                   for a, ps in AGENT_EMAIL_SIGS.items()}

_BOT_SUFFIX_RE = re.compile(r"(\[bot\]|[-_]bot)$", re.I)


def _first_match(tables: Dict[str, List[Pattern]], value: str) -> Optional[str]:
    """Return the first table key whose patterns match `value`, else None."""
    for name, res in tables.items():
        if any(r.search(value) for r in res):
            return name
    return None


def _has_bot_marker(login: str, email: str) -> bool:
    """True when the identity carries hard evidence of being a machine account.

    Markers: a `[bot]`/`-bot` suffix on the login, a `[bot]` local part in the
    e-mail (how GitHub App accounts are addressed), or a known vendor robot
    domain. A plain `@users.noreply.github.com` address is NOT a marker — humans
    with private e-mail on GitHub use it too.
    """
    if login and _BOT_SUFFIX_RE.search(login):
        return True
    if not email:
        return False
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    if "[bot]" in local:
        return True
    return any(domain == d or domain.endswith("." + d) for d in BOT_EMAIL_DOMAINS)


def match_review_bot(login: str) -> Optional[str]:
    """Return the review-bot product name for a reviewer login, or None."""
    if not login:
        return None
    return _first_match(REVIEW_RES, login)


def match_agent_email(email: str) -> Optional[str]:
    """Return the coding-agent name owning this commit e-mail, or None."""
    if not email:
        return None
    return _first_match(AGENT_EMAIL_RES, email.strip().lower())


def match_login(login: str, email: str = "",
                is_bot: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Classify a machine-readable identity into (agent, category).

    `login` MUST be an account handle — a GitHub actor/bot login
    (`devin-ai-integration[bot]`, `copilot-swe-agent`) or the local part of a
    commit e-mail (`cursoragent` from `cursoragent@cursor.com`). It must NEVER
    be a git display name (`%an` / `%cn`): those are free text, and a human
    contributor called "Claude" or "Cody" would otherwise be scored as an AI
    agent — which, adoption being the earliest AI action, silently moves a whole
    repo's adoption date.
    `email` is the optional commit e-mail (`%ae` / `%ce`) used both as a
    signature in its own right and to disambiguate bare product names.
    `is_bot` lets a caller that knows the account type (the GitHub API reports
    `type: "Bot"`) accept a bare product name without an e-mail.

    category is one of:
      'review'    — a known AI code-review bot (CodeRabbit, Copilot review, ...)
      'coding'    — a known AI coding agent acting as an account (Devin, Copilot
                    SWE agent, Cursor agent, ...)
      'other-bot' — some other automation ([bot] suffix) that is NOT a known AI
                    tool (dependabot, CI, release bots) — recorded for
                    transparency but never counted as AI adoption
    Returns (None, None) for ordinary human identities.
    """
    login = (login or "").strip()
    email = (email or "").strip()
    if not login and not email:
        return None, None

    by_email = match_agent_email(email)
    if by_email:
        return by_email, "coding"

    if login:
        rev = match_review_bot(login)
        if rev:
            return rev, "review"
        coding = _first_match(CODING_LOGIN_RES, login)
        if coding:
            return coding, "coding"

        marked = is_bot or _has_bot_marker(login, email)
        base = _BOT_SUFFIX_RE.sub("", login)
        ambiguous = _first_match(AMBIGUOUS_LOGIN_RES, base)
        if ambiguous:
            return (ambiguous, "coding") if marked else (None, None)

        if _BOT_SUFFIX_RE.search(login):
            return login, "other-bot"
    return None, None
