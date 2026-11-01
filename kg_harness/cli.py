import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from .agent import Agent, ChatCompletionsModel, ScriptedDemoModel
from .runtime import Runtime


def initialize(runtime, examples):
    results = []
    for name in ("jedec_A.json", "jedec_B.json"):
        source = examples / name
        target = runtime.workspace.root / "inputs" / name
        if not target.exists():
            shutil.copyfile(source, target)
        elif target.read_bytes() != source.read_bytes():
            raise ValueError(f"Refusing to replace existing input: {target}")
        results.append(runtime.kg.import_file(target))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="File-capable KG harness prototype")
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--executor", choices=("disabled", "docker", "trusted-local"), default="disabled")
    parser.add_argument("--image", default="python:3.12-slim")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Import fictional example versions A/B")
    init.add_argument("--examples", default=str(Path(__file__).resolve().parent.parent / "examples"))
    demo = sub.add_parser("demo", help="Scripted offline test of the same tool loop; not an LLM")
    demo.add_argument("--examples", default=str(Path(__file__).resolve().parent.parent / "examples"))
    imp = sub.add_parser("import", help="Operator-only: import a workspace input")
    imp.add_argument("path")
    sub.add_parser("versions")
    ask = sub.add_parser("ask", help="Offline keyword evidence lookup; use agent for model synthesis")
    ask.add_argument("--version", required=True)
    ask.add_argument("--question", required=True)
    diff = sub.add_parser("compare")
    diff.add_argument("--old", required=True)
    diff.add_argument("--new", required=True)
    diff.add_argument("--output", default=None)
    tool = sub.add_parser("tool", help="Call one registered tool with JSON arguments")
    tool.add_argument("name")
    tool.add_argument("arguments", nargs="?", default="{}")
    for name in ("agent", "deepagent"):
        agent = sub.add_parser(name)
        agent.add_argument("task")
        agent.add_argument("--model", default=os.getenv("LLM_MODEL"))
        agent.add_argument("--max-steps", type=int, default=20)
        if name == "agent":
            agent.add_argument("--base-url", default=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    args = parser.parse_args(argv)
    runtime = Runtime(args.workspace, args.executor, args.image)
    try:
        if args.command == "init":
            result = initialize(runtime, Path(args.examples))
        elif args.command == "demo":
            initialize(runtime, Path(args.examples))
            prefix = "outputs/demo-" + uuid.uuid4().hex[:8]
            result = Agent(runtime, ScriptedDemoModel(prefix)).run("演示文件读写、修改和 A/B 图谱比较")
            result["mode"] = "scripted_offline_demo_not_llm"
        elif args.command == "import":
            result = runtime.kg.import_file(runtime.workspace.resolve(args.path))
        elif args.command == "versions":
            result = runtime.kg.list_versions()
        elif args.command == "ask":
            evidence = runtime.kg.search_kg(args.version, args.question)
            result = {"mode": "offline_extractive_evidence", "question": args.question, **evidence,
                      "answer": "以下仅为关键词命中的证据，不是模型推理答案。" if evidence["hits"]
                      else "未找到匹配证据；这不意味着该标准没有相关规定。"}
        elif args.command == "compare":
            prefix = args.output or "outputs/comparison-" + uuid.uuid4().hex[:8]
            result = runtime.export_comparison(args.old, args.new, prefix)
        elif args.command == "tool":
            result = runtime.call(args.name, json.loads(args.arguments))
        elif args.command == "agent":
            if not args.model:
                raise ValueError("Supply --model or set LLM_MODEL")
            if not 1 <= args.max_steps <= 100:
                raise ValueError("max-steps must be 1..100")
            model = ChatCompletionsModel(args.model, args.base_url)
            result = Agent(runtime, model, max_steps=args.max_steps).run(args.task)
        else:
            from .deepagents_backend import build_deep_agent
            if not args.model:
                raise ValueError("Supply a provider-qualified --model, e.g. openai:<available-model>")
            if not 1 <= args.max_steps <= 100:
                raise ValueError("max-steps must be 1..100")
            graph = build_deep_agent(runtime, args.model)
            output = graph.invoke({"messages": [{"role": "user", "content": args.task}]},
                                  config={"recursion_limit": args.max_steps})
            result = {"backend": "deepagents", "answer": output["messages"][-1].content}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and (result.get("ok") is False or result.get("status") in
                                        ("failed", "step_limit", "context_limit")):
            return 1
        return 0
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
