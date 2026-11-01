"""Optional REAL harness reuse: Deep Agents owns the model/tool loop."""

from .agent import SYSTEM_PROMPT


def build_deep_agent(runtime, model: str):
    try:
        from deepagents import create_deep_agent
        from langchain_core.tools import StructuredTool
    except ImportError as error:
        raise RuntimeError("Install optional integration: pip install '.[deepagents]'") from error

    wrapped = []
    for spec in runtime.schemas():
        function = spec["function"]

        def bind(tool_name):
            def invoke(**kwargs):
                return runtime.call(tool_name, kwargs)
            return invoke

        wrapped.append(StructuredTool(name="kg_" + function["name"],
                                      description=function["description"],
                                      args_schema=function["parameters"],
                                      func=bind(function["name"])))
    # Keep the default state-backed filesystem for Deep Agents internal context.
    # Real host file operations ONLY use our explicit kg_* workspace tools.
    # Do not also attach an unrestricted FilesystemBackend or LocalShellBackend.
    return create_deep_agent(
        model=model, tools=wrapped,
        system_prompt=SYSTEM_PROMPT + "\n访问真实工作区和 KG 必须使用 kg_ 前缀工具；内置文件工具只管理内部状态。",
    )
