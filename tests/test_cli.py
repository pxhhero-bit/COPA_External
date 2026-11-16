# -*- coding: utf-8 -*-
"""Small stdlib-only checks for the LLM CLI boundary.

The full engine/Qt acceptance suite is run by the integration worktree.  These
checks stay local to the runtime-free parser and deterministic archive helpers.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_PARENT = os.path.dirname(ROOT)
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from COPA.apps.llm_io import load_payload
from COPA.cli_quote import _failure_reason, _session_dir, main


class LlmIoTests(unittest.TestCase):
    def test_fenced_response_and_trailing_comma(self):
        raw = "说明\n```json\n{\u00a0\"schema_version\": 1,}\n```\n结束"
        self.assertEqual(load_payload(raw), {"schema_version": 1})

    def test_text_with_surrounding_prose(self):
        self.assertEqual(load_payload("before {\"x\": [1, 2]} after"),
                         {"x": [1, 2]})

    def test_invalid_payload_has_error_details(self):
        with self.assertRaises(Exception) as ctx:
            load_payload("```json\n{broken\n```")
        self.assertTrue(getattr(ctx.exception, "errors", None))
        self.assertIn("原文前200字符", str(ctx.exception))


class CliHelpersTests(unittest.TestCase):
    def test_session_root_is_injectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _session_dir("A/B", root=tmp)
            self.assertTrue(path.is_dir())
            self.assertTrue(str(path).startswith(os.path.abspath(tmp)))
            self.assertNotIn("/", path.name)

    def test_failure_reason_prefers_diagnostic(self):
        self.assertEqual(
            _failure_reason({
                "status": "NO_MATCH",
                "platform_diagnostic": {
                    "evidence": {"reason": "台面尺寸不匹配"}
                },
            }),
            "台面尺寸不匹配",
        )

    def test_print_flags_do_not_require_qt(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = main(["--print-schema"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
