"""Optional real-library integration tests. No network or paid model calls."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from kg_harness.kg import NestedJSONAdapter
from kg_harness.runtime import Runtime


class OptionalIntegrations(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("ijson"), "ijson is not installed")
    def test_streaming_adapter_matches_in_memory_records(self):
        path = Path(__file__).resolve().parent.parent / "examples/jedec_A.json"
        adapter = NestedJSONAdapter()
        metadata, chapters = adapter.read(path)
        expected = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["version"], expected["version"])
        self.assertEqual(list(adapter.records(chapters)), list(adapter.records(expected["sections"])))

    @unittest.skipUnless(importlib.util.find_spec("deepagents"), "Deep Agents is not installed")
    def test_real_deepagents_loop_writes_real_file_with_fake_model(self):
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage, ToolMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from kg_harness.deepagents_backend import build_deep_agent

        class DeterministicModel(BaseChatModel):
            @property
            def _llm_type(self):
                return "offline-integration-test"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                if any(isinstance(message, ToolMessage) for message in messages):
                    message = AIMessage(content="offline integration done")
                else:
                    message = AIMessage(content="", tool_calls=[{
                        "name": "kg_write_file", "args": {"path": "outputs/deepagents-test.txt", "content": "real tool execution"},
                        "id": "integration_1", "type": "tool_call"}])
                return ChatResult(generations=[ChatGeneration(message=message)])

        base = Path(__file__).resolve().parent.parent / ".test-workspace"
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as directory:
            runtime = Runtime(directory)
            agent = build_deep_agent(runtime, DeterministicModel())
            result = agent.invoke({"messages": [{"role": "user", "content": "Write the test file"}]},
                                  config={"recursion_limit": 10})
            self.assertEqual((Path(directory) / "outputs/deepagents-test.txt").read_text(), "real tool execution")
            self.assertEqual(result["messages"][-1].content, "offline integration done")


if __name__ == "__main__":
    unittest.main()
