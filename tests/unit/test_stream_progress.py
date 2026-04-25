"""Unit tests for the stream_progress parser.

The parser is a critical-path component: it provides programmatic
verification that the Write tool was invoked. Tests lock in:
- exit code 0 on Write-on-expected-path
- exit code 2 on no Write at all
- exit code 3 on Write-on-wrong-path
- substring-match guard (was a real bug — /tmp/foo/X.md vs /tmp/foo_old/X.md)
- parse error tolerance (malformed JSON lines don't crash)
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest


# Path to the parser script. Tests run via subprocess so we exercise the
# script as users would invoke it (chmod-x + python3 shebang).
PARSER = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "beril_adversarial"
    / "skill"
    / "tools"
    / "stream_progress.py"
)


def _run_parser(events: list[dict], expected_path: str | None = None,
                quiet: bool = True) -> subprocess.CompletedProcess:
    """Pipe a list of stream-json events to the parser and return the result."""
    stdin_data = "\n".join(json.dumps(e) for e in events) + "\n"
    args = ["python3", str(PARSER)]
    if expected_path is not None:
        args += ["--expected-write-path", expected_path]
    if quiet:
        args.append("--quiet")
    return subprocess.run(
        args,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _tool_use_event(name: str, **kwargs) -> dict:
    return {
        "type": "content_block_start",
        "content_block": {"type": "tool_use", "name": name, "input": kwargs},
    }


def _result_event(input_tokens: int = 100, output_tokens: int = 50) -> dict:
    return {
        "type": "result",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


class TestExitCodes:

    def test_write_on_expected_path_exit_zero(self, tmp_path: Path):
        target = tmp_path / "ADVERSARIAL_REVIEW_1.md"
        target.touch()  # so resolve() works
        events = [
            _tool_use_event("Read", file_path="/some/REPORT.md"),
            _tool_use_event("Write", file_path=str(target)),
            _result_event(),
        ]
        rc = _run_parser(events, expected_path=str(target))
        assert rc.returncode == 0

    def test_no_write_exits_two(self):
        events = [
            _tool_use_event("Read", file_path="/some/REPORT.md"),
            _tool_use_event("WebSearch", query="bacterial fitness"),
            _result_event(),
        ]
        rc = _run_parser(events, expected_path="/expected/path.md")
        assert rc.returncode == 2

    def test_write_on_wrong_path_exits_three(self, tmp_path: Path):
        wrong = tmp_path / "wrong.md"
        wrong.touch()
        events = [
            _tool_use_event("Write", file_path=str(wrong)),
            _result_event(),
        ]
        rc = _run_parser(events, expected_path="/different/expected.md")
        assert rc.returncode == 3


class TestSubstringMatchGuard:
    """Regression test for the substring-match bug:
    /tmp/foo/X.md must NOT be accepted when expected is /tmp/foo_old/X.md."""

    def test_similar_directory_names_rejected(self, tmp_path: Path):
        actual_dir = tmp_path / "foo"
        actual_dir.mkdir()
        actual = actual_dir / "ADVERSARIAL_REVIEW_1.md"
        actual.touch()

        expected_dir = tmp_path / "foo_old"
        expected_dir.mkdir()
        expected = expected_dir / "ADVERSARIAL_REVIEW_1.md"
        # Don't create expected; it would be the target the script wanted

        events = [
            _tool_use_event("Write", file_path=str(actual)),
            _result_event(),
        ]
        rc = _run_parser(events, expected_path=str(expected))
        # The substring match (the original bug) would accept this and exit 0.
        # The fixed code should return 3 (wrong path).
        assert rc.returncode == 3


class TestParseErrorTolerance:
    """Malformed JSON lines should be skipped + counted, not crash."""

    def test_malformed_lines_skipped(self, tmp_path: Path):
        target = tmp_path / "ADVERSARIAL_REVIEW_1.md"
        target.touch()

        # Build raw stdin with one malformed line in the middle
        events = [
            json.dumps(_tool_use_event("Read", file_path="/x.md")),
            "{ this is not valid json at all",
            json.dumps(_tool_use_event("Write", file_path=str(target))),
            json.dumps(_result_event()),
        ]
        stdin_data = "\n".join(events) + "\n"
        rc = subprocess.run(
            ["python3", str(PARSER), "--expected-write-path", str(target), "--quiet"],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Parser should have skipped the bad line and detected the Write
        assert rc.returncode == 0


class TestMetadataOut:
    """Verify --metadata-out writes a JSON sidecar with expected fields."""

    def test_metadata_json_written_on_success(self, tmp_path: Path):
        target = tmp_path / "REVIEW.md"
        target.touch()
        meta_out = tmp_path / "meta.json"
        events = [
            _tool_use_event("Write", file_path=str(target)),
            {
                "type": "result",
                "usage": {
                    "input_tokens": 12345,
                    "output_tokens": 6789,
                    "cache_read_input_tokens": 80000,
                },
            },
        ]
        stdin_data = "\n".join(json.dumps(e) for e in events) + "\n"
        rc = subprocess.run(
            ["python3", str(PARSER),
             "--expected-write-path", str(target),
             "--metadata-out", str(meta_out),
             "--model", "claude-sonnet-4-20250514",
             "--quiet"],
            input=stdin_data, capture_output=True, text=True, timeout=10,
        ).returncode
        assert rc == 0
        assert meta_out.is_file()
        meta = json.loads(meta_out.read_text())
        assert meta["input_tokens"] == 12345
        assert meta["output_tokens"] == 6789
        assert meta["cache_read_tokens"] == 80000
        assert meta["model"] == "claude-sonnet-4-20250514"
        assert "estimated_cost_usd" in meta
        assert meta["estimated_cost_usd"] > 0

    def test_metadata_not_written_on_silent_failure(self, tmp_path: Path):
        # Write was never invoked → exit 2, no metadata file
        meta_out = tmp_path / "meta.json"
        events = [
            _tool_use_event("Read", file_path="/some/REPORT.md"),
            _result_event(),
        ]
        stdin_data = "\n".join(json.dumps(e) for e in events) + "\n"
        rc = subprocess.run(
            ["python3", str(PARSER),
             "--expected-write-path", "/expected.md",
             "--metadata-out", str(meta_out),
             "--quiet"],
            input=stdin_data, capture_output=True, text=True, timeout=10,
        ).returncode
        assert rc == 2
        assert not meta_out.exists()  # not written on failure


class TestAggregator:
    """Test tools/aggregate_metadata.py."""

    AGGREGATOR = (
        Path(__file__).resolve().parents[2]
        / "src" / "beril_adversarial" / "skill" / "tools"
        / "aggregate_metadata.py"
    )

    def test_aggregates_two_calls(self, tmp_path: Path):
        review = tmp_path / "REVIEW.md"
        review.write_text(
            "---\nreviewer: test\n---\n\n# Review\n\nBody.\n",
            encoding="utf-8",
        )
        m1 = tmp_path / "m1.json"
        m1.write_text(json.dumps({
            "elapsed_seconds": 458,
            "input_tokens": 1519325,
            "output_tokens": 9814,
            "estimated_cost_usd": 0.838,
            "model": "claude-sonnet-4-20250514",
        }))
        m2 = tmp_path / "m2.json"
        m2.write_text(json.dumps({
            "elapsed_seconds": 36,
            "input_tokens": 114814,
            "output_tokens": 1633,
            "estimated_cost_usd": 0.111,
            "model": "claude-sonnet-4-20250514",
        }))
        rc = subprocess.run(
            ["python3", str(self.AGGREGATOR),
             "--review-file", str(review),
             "--metadata-files", str(m1), str(m2),
             "--call-labels", "main", "critic"],
            capture_output=True, text=True, timeout=10,
        ).returncode
        assert rc == 0
        text = review.read_text(encoding="utf-8")
        assert "## Run Metadata" in text
        # Sums: 458+36 = 494 sec = 08:14
        assert "08:14" in text
        # Cost: 0.838 + 0.111 = 0.949
        assert "$0.949" in text
        # Pipeline labels
        assert "main + critic" in text
        # Tokens summed
        assert f"{1519325 + 114814:,}" in text  # 1,634,139

    def test_aggregator_handles_missing_metadata(self, tmp_path: Path):
        review = tmp_path / "REVIEW.md"
        review.write_text("# Review\n", encoding="utf-8")
        nonexistent = tmp_path / "nope.json"
        rc = subprocess.run(
            ["python3", str(self.AGGREGATOR),
             "--review-file", str(review),
             "--metadata-files", str(nonexistent)],
            capture_output=True, text=True, timeout=10,
        ).returncode
        # Should succeed (warn but not fail) when no metadata
        assert rc == 0
        text = review.read_text(encoding="utf-8")
        # No Run Metadata section since no metadata to aggregate
        assert "## Run Metadata" not in text


class TestEventShapeFlexibility:
    """The parser handles multiple event shapes (claude versions vary)."""

    def test_assistant_message_shape(self, tmp_path: Path):
        """tool_use embedded in event.message.content[]."""
        target = tmp_path / "out.md"
        target.touch()
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": str(target)},
                        }
                    ]
                },
            },
            _result_event(),
        ]
        rc = _run_parser(events, expected_path=str(target))
        assert rc.returncode == 0

    def test_top_level_tool_use_shape(self, tmp_path: Path):
        """tool_use as top-level event type."""
        target = tmp_path / "out.md"
        target.touch()
        events = [
            {
                "type": "tool_use",
                "name": "Write",
                "input": {"file_path": str(target)},
            },
            _result_event(),
        ]
        rc = _run_parser(events, expected_path=str(target))
        assert rc.returncode == 0
