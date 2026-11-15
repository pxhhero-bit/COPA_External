"""Delivery-layer regression: generated prompt/schema, CLI normalization, archive.

Zero network and zero Qt: the CLI path is exercised through ``run_payload``.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from COPA import cli_quote
from COPA.apps import contract
from COPA.apps.llm_chat import demo_payload


def must(value):
    """断言「这次运行一定有归档目录」并把 Optional 收窄。"""

    assert value is not None
    return value


class GeneratedArtifactTests(unittest.TestCase):
    # llm/generated 是开发期生成物，不随对外版分发；现场可用
    # cli_quote.export_generated 重新导出后再跑这条比对。
    @unittest.skipUnless(
        (ROOT / "llm" / "generated" / "prompt.txt").is_file(),
        "未随包分发 llm/generated 生成物")
    def test_runtime_prompt_and_schema_match_generated_files(self):
        self.assertEqual(
            (ROOT / "llm" / "generated" / "prompt.txt").read_text(encoding="utf-8"),
            contract.print_prompt(),
        )
        self.assertEqual(
            json.loads((ROOT / "llm" / "generated" / "schema.json").read_text(encoding="utf-8")),
            contract.print_schema(),
        )

    def test_export_writes_both_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = cli_quote.export_generated(directory)
            self.assertEqual({path.name for path in paths}, {"prompt.txt", "schema.json"})
            prompt = (Path(directory) / "prompt.txt").read_text(encoding="utf-8")
            schema = json.loads(
                (Path(directory) / "schema.json").read_text(encoding="utf-8")
            )
            self.assertEqual(prompt, contract.print_prompt())
            self.assertEqual(schema, contract.print_schema())
            # 对话协议必须在最前，schema 只是其后的契约真源。
            self.assertTrue(prompt.startswith("你在 COPA 内把用户的需求原文翻译成结构化 JSON"))
            self.assertIn("【程序归一】", prompt)

    def test_missing_rules_fails_loudly_instead_of_schema_only(self):
        original = contract._rules_dir
        with tempfile.TemporaryDirectory() as directory:
            contract._rules_dir = lambda: Path(directory)
            try:
                with self.assertRaises(RuntimeError) as ctx:
                    contract.print_prompt()
            finally:
                contract._rules_dir = original
        self.assertIn("00-*.md", str(ctx.exception))


class RunPayloadNormalizationTests(unittest.TestCase):
    @staticmethod
    def total_weight_payload():
        payload = demo_payload()
        payload["quote"]["confirmed_by_user"] = True
        item = payload["items"][0]
        item["fields"].pop("W1", None)
        item["provenance"].pop("W1", None)
        item["fields"]["W_total"] = "5t"
        return payload

    def test_cli_path_normalizes_total_weight_before_engine(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run = cli_quote.run_payload(self.total_weight_payload(), session_root=directory)
        self.assertEqual(run.exit_code, cli_quote.EXIT_OK)
        item = run.payload["items"][0]
        self.assertEqual(item["fields"]["W1"], 5000)
        self.assertEqual(item["fields"]["W2"], 0)
        self.assertEqual(item["provenance"]["W1"]["source"], "total_weight")
        self.assertNotIn("W_total", item["fields"])

    def test_manifest_lists_the_archive_products(self):
        payload = demo_payload()
        payload["quote"]["confirmed_by_user"] = True
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run = cli_quote.run_payload(payload, session_root=directory)
            manifest = json.loads(
                (must(run.session_dir) / "manifest.json").read_text(encoding="utf-8")
            )
        names = {entry["name"] for entry in manifest["files"]}
        self.assertIn("quote.json", names)
        self.assertIn("results.json", names)
        self.assertIn("run.log", names)
        self.assertGreater(len(manifest["files"]), 2)

    def test_run_log_records_llm_events(self):
        events = [{"round": 1, "intent": "continue", "missing": [], "elapsed_ms": 12}]
        payload = demo_payload()
        payload["quote"]["confirmed_by_user"] = True
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run = cli_quote.run_payload(
                payload, session_root=directory, llm_events=events
            )
            log = (must(run.session_dir) / "run.log").read_text(encoding="utf-8")
        self.assertIn("llm_events:", log)
        self.assertIn('"round": 1', log)
        self.assertIn('"intent": "continue"', log)


class SpecPackagingTests(unittest.TestCase):
    """providers.json 按内部分发需要随包走，但必须保持 exe 同目录可覆盖。"""

    @staticmethod
    def _llm_datas(project_dir: Path) -> list:
        """只执行 COPA.spec 的头部，取出真实的 datas 列表。"""

        source = (ROOT / "COPA.spec").read_text(encoding="utf-8")
        head = source.split("a = Analysis(")[0]
        namespace: dict[str, object] = {"SPECPATH": str(project_dir)}
        exec(compile(head, "COPA.spec", "exec"), namespace)
        datas = namespace["LLM_DATAS"]
        assert isinstance(datas, list)
        return datas

    def test_providers_json_is_shipped_with_the_bundle(self):
        datas = self._llm_datas(ROOT)
        self.assertIn((str(ROOT / "llm" / "providers.json"), "llm"), datas)
        self.assertIn((str(ROOT / "llm" / "rules"), "llm/rules"), datas)

    def test_missing_providers_json_does_not_break_the_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "llm" / "rules").mkdir(parents=True)
            datas = self._llm_datas(root)
        self.assertEqual([dest for _, dest in datas], ["llm/rules"])


class FrozenProviderLookupTests(unittest.TestCase):
    def setUp(self):
        from COPA.apps import llm_chat

        self.llm_chat = llm_chat
        self._saved = (
            getattr(sys, "frozen", None),
            sys.executable,
            getattr(sys, "_MEIPASS", None),
            llm_chat.__file__,
        )

    def tearDown(self):
        frozen, executable, meipass, module_file = self._saved
        if frozen is None:
            sys.__dict__.pop("frozen", None)
        else:
            setattr(sys, "frozen", frozen)
        sys.executable = executable
        if meipass is None:
            sys.__dict__.pop("_MEIPASS", None)
        else:
            setattr(sys, "_MEIPASS", meipass)
        self.llm_chat.__file__ = module_file

    def _freeze(self, root: Path) -> tuple[Path, Path]:
        exe_dir = root / "app"
        internal = root / "internal"
        (internal / "llm").mkdir(parents=True)
        exe_dir.mkdir()
        setattr(sys, "frozen", True)
        sys.executable = str(exe_dir / "COPA.exe")
        setattr(sys, "_MEIPASS", str(internal))
        self.llm_chat.__file__ = str(root / "src" / "apps" / "llm_chat.py")
        return exe_dir, internal

    def test_bundled_copy_is_used_when_exe_side_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            exe_dir, internal = self._freeze(Path(directory))
            bundled = internal / "llm" / "providers.json"
            bundled.write_text("{}", encoding="utf-8")
            self.assertEqual(self.llm_chat._default_providers_path(), bundled)
            self.assertFalse((exe_dir / "llm" / "providers.json").exists())

    def test_exe_side_override_wins_over_the_bundled_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            exe_dir, internal = self._freeze(Path(directory))
            (internal / "llm" / "providers.json").write_text("{}", encoding="utf-8")
            (exe_dir / "llm").mkdir()
            override = exe_dir / "llm" / "providers.json"
            override.write_text("{}", encoding="utf-8")
            self.assertEqual(self.llm_chat._default_providers_path(), override)


if __name__ == "__main__":
    unittest.main()
