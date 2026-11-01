# Harness V2：公司内部模型版

详细技术报告：[为什么 coding agent 能操作文件、真正难点与 JEDEC 实施路线](docs/REPORT.zh-CN.md)。

这是独立子项目。只复制本文件夹即可运行，不导入上一级项目，也不依赖 Claude Code、Codex、OpenAI 或 Deep Agents SDK。运行时只使用 Python 标准库，包含文件操作、执行循环、模型适配、KG 检索与版本比较。

本版本复用的是前一版中我们自己实现的文件/KG 工具，并重写模型接入与大文件解析；没有复制商业 agent 的私有源码，也不声称已完整复刻它们的行为。

## 和 V1 的区别

| 项目 | V2 |
| --- | --- |
| 厂商 SDK / Deep Agents | 无，不需要安装 |
| 默认模型服务 | 无；运行 agent 必须提供配置文件 |
| 服务访问 | 精确 scheme/host/port 允许列表，禁止自动重定向，不继承代理变量 |
| 模型协议 | 原生工具调用 `chat_tools` / 纯文本结构化动作 `json_actions` |
| 模型认证 | 仅从配置指定的环境变量读取；不会读取其他产品的凭据 |
| 大 JSON | 标准库流式读取，不依赖 ijson |
| 部署 | Python 3.11+，含 SQLite FTS5；无需 pip 安装即可从源码运行 |

模型能力仍影响结果质量。`json_actions` 可以接入没有原生 tools 字段的聊天模型，但要求模型遵守 JSON 格式；它不会自动让弱模型获得强规划能力。

## 先运行离线演示

进入 `harness_v2` 目录：

```powershell
python -m internal_harness demo
python -m internal_harness ask --version A --question PARAM_X
python -m internal_harness compare --old A --new B
```

本次开发已创建一个不含 pip/第三方包的本地虚拟环境，也可以直接运行：

```powershell
.\.venv\Scripts\python.exe -m internal_harness demo
```

在其他电脑不要复制 `.venv`，使用公司批准的 Python，或自行运行 `python -m venv --without-pip .venv`。

`demo` 是明确标注的确定性测试替身，不调用模型、不发送网络请求。它实际执行查目录、KG 检索、写文件、读取、修改、导出差异。`ask` 不提供配置时，仅返回关键词证据，不能视为自然语言推理回答。

输出在 `workspace/outputs/`；状态和事件在 `workspace/.state/sessions/`。每次演示使用新的文件前缀。

## 连接公司内部模型

复制 `config/company.example.json` 为 `config/company.json`，替换占位地址和模型名。

```json
{
  "endpoint": "https://model.company.internal/v1/chat/completions",
  "allowed_origins": ["https://model.company.internal"],
  "model": "YOUR_INTERNAL_MODEL",
  "protocol": "chat_tools",
  "auth_env": "INTERNAL_MODEL_TOKEN",
  "ca_file": null,
  "allow_http": false,
  "timeout_seconds": 60,
  "max_response_bytes": 2097152
}
```

`endpoint` 是完整请求地址，代码不会自动追加路径或尝试外部服务。`allowed_origins` 必须匹配该地址的协议、域名和端口，不接受通配匹配。

```powershell
$env:INTERNAL_MODEL_TOKEN = '<公司内部服务令牌>'
python -m internal_harness doctor --config config/company.json
python -m internal_harness agent --config config/company.json '读取 A 版 PARAM_X 的要求，补查相关章节，将带来源的答案写入 outputs/answer.md'
python -m internal_harness ask --config config/company.json --version A --question 'PARAM_X 的最小值是多少？'
python -m internal_harness agent --config config/company.json '比较 A 和 B 的变化，核查两侧证据并保存报告'
```

`doctor` 只做本地检查，不请求模型服务，不打印令牌。`auth_env: null` 表示服务不需要 Bearer 认证。内部 CA 可以通过 `ca_file` 指向 PEM 证书，相对路径相对于配置文件目录；不提供关闭 TLS 校验的开关。

非回环明文 HTTP 默认拒绝；公司确实使用内部 HTTP 时需显式配置 `allow_http: true`。允许列表仅限制本客户端访问的目标，不判断域名是否真正私有，也不替代公司防火墙/DNS/出站控制。客户端不继承 HTTP_PROXY 等变量；需要企业代理或自定义认证时，应显式修改 transport，不能依靠隐式转发。

## 两种模型协议

**`chat_tools`：** 服务接收 `model`、`messages`、`tools`、`tool_choice`，返回 `choices[0].message`，其中包含文本或 `tool_calls`。这是兼容的 JSON 消息协议，不等于调用协议最初提供商的服务。

**`json_actions`：** 服务只需接受 `model` 和聊天 `messages`，仍返回 `choices[0].message.content`。系统在提示词里提供工具说明，模型返回下面的一种 JSON：

```json
{"action":"tool","name":"read_file","arguments":{"path":"inputs/jedec_A.json","limit":2000}}
```

```json
{"action":"final","answer":"已完成，结果保存在 outputs/report.md。"}
```

运行器只接受结构化动作、注册工具和正确参数，不把模型返回的文本直接当 shell 或 Python 执行。错误的协议输出最多反馈修正两次，第三次停止并保存失败状态。模型代码执行必须通过操作员已启用的 `run_command`。

如果你们的服务使用 `/generate`、自定义 envelope 或认证头，修改 `internal_harness/model.py` 的 `build_payload` / `parse_response` / transport；不需要修改文件工具、KG 工具或执行循环。模型对象只需提供 `complete(messages, tools)` 方法。

## 文件与程序执行

真实文件工具：`list_files`、`read_file`、`search_files`、`write_file`、`edit_file`。输入只读，`work/` 和 `outputs/` 可写。覆盖文件需要当前 SHA-256；修改要求目标文本唯一匹配。读取按 UTF-8 字节窗口，边界可能产生替换字符；编辑完整小文件可避免这一问题。

执行命令默认关闭。可以在可信开发环境运行完整演示：

```powershell
python -m internal_harness --executor trusted-local demo
```

该模式会额外创建 Python 脚本、执行脚本并读取输出。**trusted-local 使用当前操作系统账户权限，不是沙箱**；路径检查限制的是文件工具，无法限制脚本的所有系统访问。

若要执行不可信生成代码，应使用经公司批准并在本地预加载的 Docker 镜像或公司现有隔离执行平台：

```powershell
python -m internal_harness --executor docker --image '<公司批准并已加载的Python镜像>' agent --config config/company.json '在 work/ 创建并运行分析脚本'
```

Docker 后端不自动拉取镜像，网络关闭，只挂载输入（只读）、工作目录与输出目录，并设置资源限制。默认 UID 65534，需要部署环境提供匹配的目录写权限。当前未完成实际 Docker 环境验证。

文件路径策略不是对恶意并发文件替换的 OS 安全保证；当前面向单用户、串行任务。任务状态可检查，但尚未实现崩溃后的自动续跑、并发锁或 exactly-once 执行。

## KG 格式和大文件

样例 `examples/jedec_A.json` / `jedec_B.json` 完全虚构。根包含 schema_version=1、standard、version、sections；章节含 stable_key、number、title、text、entities、relations、subsections。

stable_key 是跨版本稳定的身份；条款编号可以变化。关系通过 source_id/target_id 指向实体 stable_key，支持跨章节关系；重复 key 或悬空关系导致导入回滚。

```powershell
python -m internal_harness import inputs/my_version.json
python -m internal_harness versions
python -m internal_harness compare --old A --new B --output outputs/review
```

标准库解析器按顶层章节解析，支持元数据出现在 sections 后面。为了不依赖字段顺序，进行两次解析遍历；单个 JSON 值设 3200 万字符上限，峰值内存仍取决于最大章节，不是整个文件大小。若一章包含整个巨大图谱，需要拆分或替换适配器。

当前比较是全量导入记录的精确 stable_key 对齐，识别新增/删除/修改，不支持语义匹配、拆分合并、单位换算。source-only 元数据变化不计作内容修改。图谱差异不等于经原文核实的 JEDEC 变化。

## 验证与目录

```powershell
python -S -m unittest discover -s tests -v
python -S scripts/benchmark_import.py --mb 200
```

`-S` 禁用 site-packages 加载，测试不需要第三方库。HTTP 集成测试仅请求进程内的 127.0.0.1 模拟服务；如公司环境禁用回环网络，这些测试需要在允许该回环连接的测试环境运行。

```text
internal_harness/
  model.py          显式内网配置、HTTP transport、两种消息协议
  agent.py          执行循环、状态、错误反馈、离线演示
  runtime.py        工具注册、参数检查、报告导出
  files.py          文件工具与访问范围
  execution.py      可替换程序执行后端
  json_stream.py    无第三方依赖的分章 JSON 解析
  kg.py             KG 适配、SQLite、证据检索和比较
  cli.py            命令行
config/             公司/本地服务示例配置
examples/           虚构 KG 版本
tests/              核心、协议、HTTP、流式解析测试
docs/               设计与验证记录
```

设计说明见 `docs/DESIGN.zh-CN.md`，实测状态见 `docs/VALIDATION.md`。内部真实模型的质量和真实 JEDEC 数据适配需要后续验证；无需提供密钥给聊天，只需在公司环境自行配置。

## 带到公司环境

执行 `python scripts/package_source.py` 生成 `dist/internal-harness-v2.zip`。压缩包只包含源码、测试、虚构样例、示例配置和文档，不包含虚拟环境、运行记录、工作文件或 `config/company.json`。解压后进入 `harness_v2` 即可使用公司批准的 Python 运行离线演示。
