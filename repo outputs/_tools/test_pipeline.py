#!/usr/bin/env python3
"""End-to-end regression tests for the AI-Impact pipeline.

Builds a synthetic git repository carrying known AI markers, runs the git-only
half of the pipeline over it, and asserts on the result. Plain unittest, no
pytest, no network, no Docker — safe to run anywhere:

    python3 "repo outputs/_tools/test_pipeline.py"

Each test pins a defect that was found in a real run and has since been fixed,
so a regression fails here rather than silently corrupting a dataset.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from ai_signatures import match_login  # noqa: E402

PY = sys.executable
ENV = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, env=ENV)
    if proc.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), proc.stderr))
    return proc.stdout


def commit(repo: Path, path: str, body: str, msg: str,
           an: str, ae: str, when: str) -> None:
    """Create one commit with a fully controlled identity and timestamp."""
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    git(repo, "add", "-A")
    env = dict(ENV, GIT_AUTHOR_NAME=an, GIT_AUTHOR_EMAIL=ae,
               GIT_COMMITTER_NAME=an, GIT_COMMITTER_EMAIL=ae,
               GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    proc = subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", msg],
                          capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError("commit failed: %s%s" % (proc.stdout, proc.stderr))


def build_repo(root: Path) -> Path:
    repo = root / "synthetic"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")

    # An ordinary human contributor.
    commit(repo, "src/app.py", "print('hi')\n", "initial commit",
           "Asha Rao", "asha@example.org", "2025-01-10T09:00:00+05:30")

    # A human whose display name collides with an agent product name. This is
    # the false positive that used to set a whole repo's adoption date, because
    # match_login() was being handed %an (a free-text display name).
    commit(repo, "src/util.py", "def u(): pass\n", "add util",
           "Claude", "claude.mbeki@example.org", "2025-02-10T09:00:00+05:30")

    # A human employed by an agent vendor. A bare-domain TEXT_SIG used to flag
    # every such person as the agent itself.
    commit(repo, "src/net.py", "def n(): pass\n", "add net",
           "Jane Doe", "jane@cursor.com", "2025-03-10T09:00:00+05:30")

    # Genuine agent signals, in ascending date order. The first one sits in the
    # first hours of a month in IST, so its LOCAL month (2025-06) and its UTC
    # month (2025-05-31T20:30Z) differ. That gap is what makes
    # test_adoption_month_matches_earliest_operation discriminating: a build that
    # picks the row by UTC but writes the raw local string reports 2025-06 while
    # the ops table says 2025-05, quietly filing a month of real AI activity as
    # pre-adoption. MOSIP is IST-heavy, so this is not a hypothetical.
    commit(repo, "CLAUDE.md", "# guidance\n", "add CLAUDE.md",
           "Asha Rao", "asha@example.org", "2025-06-01T02:00:00+05:30")
    commit(repo, "src/gen.py", "def g(): pass\n",
           "add generated helper\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
           "Asha Rao", "asha@example.org", "2025-07-10T09:00:00+05:30")
    commit(repo, ".cursor/rules/x.mdc", "rule\n", "add cursor rules",
           "Asha Rao", "asha@example.org", "2025-08-10T09:00:00+05:30")
    return repo


def run_tool(script: str, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run([PY, str(TOOLS / script), *[str(a) for a in args]],
                          capture_output=True, text=True, env=ENV)
    if proc.returncode != 0:
        raise AssertionError("%s failed (rc=%d)\nSTDOUT:%s\nSTDERR:%s"
                             % (script, proc.returncode, proc.stdout, proc.stderr))
    return proc


def read_csv(p: Path) -> list:
    if not p.exists():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="aiimpact-test-"))
        cls.repo = build_repo(cls.tmp)
        cls.out = cls.tmp / "report"
        cls.out.mkdir()
        run_tool("detect_ai_agents.py", cls.repo, "owner/name", cls.out)
        run_tool("build_ai_operations.py", cls.out)
        cls.commits = read_csv(cls.out / "ai_agent_commits.csv")
        cls.ops = read_csv(cls.out / "ai_operations.csv")
        cls.adoption = read_csv(cls.out / "ai_adoption.csv")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_real_agents_are_detected(self) -> None:
        agents = {r["agent"] for r in self.commits}
        self.assertIn("Claude Code", agents)
        self.assertIn("Cursor", agents)

    def test_human_named_claude_is_not_an_agent(self) -> None:
        """A contributor whose display name is a product name must not count."""
        for r in self.commits:
            self.assertNotEqual(
                r["author"], "Claude",
                "human display name 'Claude' was attributed to %s via %s"
                % (r["agent"], r["signals"]))

    def test_vendor_employee_is_not_an_agent(self) -> None:
        """jane@cursor.com is a human employee, not the Cursor agent."""
        for r in self.commits:
            self.assertNotEqual(
                r["author"], "Jane Doe",
                "human at a vendor domain was attributed to %s via %s"
                % (r["agent"], r["signals"]))

    def test_bare_product_login_needs_bot_confirmation(self) -> None:
        self.assertEqual(match_login("Claude"), (None, None))
        self.assertEqual(match_login("Cody"), (None, None))
        # ...but a caller that knows the account type gets the detection.
        agent, cat = match_login("Copilot", is_bot=True)
        self.assertEqual(cat, "coding")
        self.assertEqual(agent, "GitHub Copilot")
        # Unambiguous bot logins never needed the hint.
        self.assertEqual(match_login("devin-ai-integration[bot]")[1], "coding")

    def test_adoption_month_matches_earliest_operation(self) -> None:
        """The split point must agree with the ops table it is derived from.

        first_action_date is chosen by true UTC, so writing a raw offset-bearing
        string there yields a month that is neither min(raw) nor min(UTC) and can
        silently file real AI activity as pre-adoption.
        """
        self.assertTrue(self.ops, "no AI operations detected")
        overall = [r for r in self.adoption if r["agent"] == "__OVERALL__"]
        self.assertEqual(len(overall), 1)
        earliest_op = min(r["date_utc"] for r in self.ops
                          if r["category"] in ("coding", "review"))
        self.assertEqual(overall[0]["first_action_date"][:7], earliest_op[:7])
        self.assertEqual(overall[0]["first_action_date"],
                         overall[0]["first_action_date_utc"])

    def test_operations_are_ordered_by_utc(self) -> None:
        dts = [r["date_utc"] for r in self.ops]
        self.assertEqual(dts, sorted(dts), "ai_operations.csv is not UTC-ordered")

    def test_summary_renders(self) -> None:
        run_tool("analyze_single_repo.py", self.out)
        summary = (self.out / "SUMMARY.md").read_text()
        self.assertIn("AI-adoption month", summary)
        self.assertTrue(summary.endswith("\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
