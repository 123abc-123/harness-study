import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from internal_harness.agent import Agent, ScriptedDemoModel
from internal_harness.cli import initialize
from internal_harness.execution import Executor
from internal_harness.runtime import Runtime

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class HarnessTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parent.parent / ".test-workspace"
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.root = Path(self.temp.name) / "workspace"
        self.runtime = Runtime(self.root)
        initialize(self.runtime, EXAMPLES)

    def tearDown(self):
        assert Path(self.temp.name).resolve().is_relative_to(Path(__file__).resolve().parent.parent / ".test-workspace")
        self.temp.cleanup()

    def test_read_write_edit_and_stale_conflict(self):
        files = self.runtime.workspace
        created = files.write_file("work/note.txt", "hello 世界")
        files.edit_file("work/note.txt", "hello", "你好", created["sha256"])
        self.assertEqual(files.read_file("work/note.txt")["content"], "你好 世界")
        with self.assertRaises(ValueError):
            files.write_file("work/note.txt", "stale", created["sha256"])
        self.assertEqual(files.read_file("work/note.txt")["content"], "你好 世界")

    def test_paths_and_readonly_inputs(self):
        for path in ("../escape", "C:/escape", ".state/kg.sqlite3", "work/../../escape", "work/a:stream"):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                self.runtime.workspace.read_file(path)
        result = self.runtime.call("write_file", {"path": "inputs/jedec_A.json", "content": "broken"})
        self.assertFalse(result["ok"])
        self.assertTrue(json.loads((self.root / "inputs/jedec_A.json").read_text(encoding="utf-8")))

    def test_symlink_escape_rejected(self):
        link = self.root / "work" / "link"
        try:
            link.symlink_to(Path(self.temp.name), target_is_directory=True)
        except OSError:
            self.skipTest("OS does not allow unprivileged symlinks")
        with self.assertRaises(PermissionError):
            self.runtime.workspace.write_file("work/link/escape.txt", "no")

    def test_ambiguous_edit_does_not_mutate(self):
        files = self.runtime.workspace
        created = files.write_file("work/repeat.txt", "a a")
        with self.assertRaises(ValueError):
            files.edit_file("work/repeat.txt", "a", "b", created["sha256"])
        self.assertEqual(files.read_file("work/repeat.txt")["content"], "a a")

    def test_bounded_read_and_search(self):
        self.runtime.workspace.write_file("work/test.txt", "x" * 1000 + "needle")
        part = self.runtime.workspace.read_file("work/test.txt", limit=100)
        self.assertTrue(part["truncated"])
        self.assertEqual(part["next_offset"], 100)
        self.assertEqual(len(self.runtime.workspace.search_files("needle", "work")["hits"]), 1)

    def test_tool_validation_and_disabled_execution(self):
        self.assertFalse(self.runtime.call("read_file", {"path": "inputs/jedec_A.json", "limit": True})["ok"])
        self.assertFalse(self.runtime.call("run_command", {"argv": ["python"]})["ok"])
        self.assertFalse(self.runtime.call("__dict__", {})["ok"])
        self.assertFalse(self.runtime.call("list_files", {"unknown": 1})["ok"])
        self.assertNotIn("run_command", [s["function"]["name"] for s in self.runtime.schemas()])

    def test_version_scoped_search_and_source(self):
        hits = self.runtime.kg.search_kg("A", "PARAM_X")["hits"]
        self.assertTrue(hits)
        self.assertTrue(all(hit["version"] == "A" for hit in hits))
        self.assertTrue(any("10" in hit["excerpt"] for hit in hits))
        self.assertTrue(all(hit["pointer"].startswith("/sections/") for hit in hits))
        with self.assertRaises(ValueError):
            self.runtime.kg.search_kg("missing", "PARAM_X")

    def test_diff_field_values_renumber_and_unchanged_provenance(self):
        changes = list(self.runtime.kg.differences("A", "B"))
        by_key = {item["key"]: item for item in changes}
        self.assertEqual(len(changes), 4)
        self.assertEqual(by_key["param_x"]["before"]["body"]["min"], 10)
        self.assertEqual(by_key["param_x"]["after"]["body"]["min"], 12)
        self.assertIn("number", by_key["timing.param_x"]["changed_fields"])
        self.assertEqual(by_key["timing.param_x"]["change"], "modified")
        self.assertEqual(by_key["legacy"]["change"], "removed")
        self.assertEqual(by_key["new_requirement"]["change"], "added")
        self.assertNotIn("timing", by_key)  # source document changed, content did not
        self.assertEqual(list(self.runtime.kg.differences("A", "A")), [])

    def test_import_atomic_duplicate_keys_and_idempotence(self):
        result = self.runtime.kg.import_file(self.root / "inputs/jedec_A.json")
        self.assertTrue(result["already_imported"])
        data = json.loads((EXAMPLES / "jedec_A.json").read_text(encoding="utf-8"))
        data["version"] = "broken"
        data["sections"].append(data["sections"][0])
        path = self.root / "work/broken.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(Exception):
            self.runtime.kg.import_file(path)
        versions = self.runtime.kg.list_versions()["versions"]
        self.assertEqual({v["version"] for v in versions}, {"A", "B"})

    def test_dangling_edge_rolls_back(self):
        data = json.loads((EXAMPLES / "jedec_A.json").read_text(encoding="utf-8"))
        data["version"] = "bad_edge"
        data["sections"][0]["subsections"][0]["relations"][0]["target_id"] = "missing"
        path = self.root / "work/bad.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.runtime.kg.import_file(path)
        self.assertEqual(len(self.runtime.kg.list_versions()["versions"]), 2)

    def test_comparison_export_is_real_and_no_overwrite(self):
        result = self.runtime.export_comparison("A", "B")
        data = json.loads((self.root / result["files"][0]).read_text(encoding="utf-8"))
        self.assertEqual(len(data["changes"]), 4)
        self.assertIn("12", (self.root / result["files"][1]).read_text(encoding="utf-8"))
        with self.assertRaises(FileExistsError):
            self.runtime.export_comparison("A", "B")

    def test_loop_demo_persists_evidence_and_files(self):
        result = Agent(self.runtime, ScriptedDemoModel("outputs/test")).run("offline test")
        self.assertEqual(result["status"], "completed")
        self.assertIn("已检查", (self.root / "outputs/test-note.md").read_text(encoding="utf-8"))
        session = self.root / ".state/sessions" / result["session_id"]
        events = [json.loads(line) for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len([e for e in events if e["type"] == "tool_end"]), 7)
        self.assertTrue(all(e["result"]["ok"] for e in events if e["type"] == "tool_end"))

    def test_step_and_context_limits(self):
        result = Agent(self.runtime, ScriptedDemoModel("outputs/test"), max_steps=1).run("test")
        self.assertEqual(result["status"], "step_limit")
        result = Agent(self.runtime, ScriptedDemoModel("outputs/test"), max_context_chars=1).run("test")
        self.assertEqual(result["status"], "context_limit")

    def test_malformed_tool_error_returns_to_model(self):
        class Model:
            def complete(self, messages, tools):
                if messages[-1]["role"] == "tool":
                    assert not json.loads(messages[-1]["content"])["ok"]
                    return {"role": "assistant", "content": "Handled invalid arguments"}
                return {"role": "assistant", "tool_calls": [{"id": "1", "type": "function",
                        "function": {"name": "write_file", "arguments": "{bad json"}}]}
        result = Agent(self.runtime, Model()).run("test")
        self.assertEqual(result["status"], "completed")
        self.assertIn("Handled", result["answer"])

    def test_trusted_command_execution_and_timeout(self):
        executor = Executor(self.runtime.workspace, "trusted-local")
        result = executor.run_command([sys.executable, "-c", "from pathlib import Path; Path('made.txt').write_text('ok'); print('done')"])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual((self.root / "work/made.txt").read_text(), "ok")
        result = executor.run_command([sys.executable, "-c", "import time; time.sleep(10)"], timeout=1)
        self.assertTrue(result["timed_out"])

    def test_execution_output_is_bounded(self):
        executor = Executor(self.runtime.workspace, "trusted-local")
        result = executor.run_command([sys.executable, "-c", "print('x' * 100000)"])
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["output"]), 32000)



if __name__ == "__main__":
    unittest.main()
