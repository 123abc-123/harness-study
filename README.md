# KG Harness：先让 Agent 能操作文件

**新增专题：[LPDDR6 JEDEC 正文 diff 方案](lpddr6_text_diff/README.md)**：正文改写与规范变更的区分、章节层次展示、评测指标与数据契约（设计方案与合成样例）。

**公司内部模型版请从 [harness_v2](harness_v2/README.md) 开始。** 最新详细报告见 [JEDEC Agent 技术报告](harness_v2/docs/REPORT.zh-CN.md)，包含文件读写机制、成熟 coding agent 的难点与实际业务建设路线。下面保留第一版的使用说明。

Python 原型：文件读写/修改、程序执行、可观察的工具循环、章节式 JSON KG 查询与版本比较，以及真实 Deep Agents 复用入口。

- 原理与复用方案：[中文报告](docs/REPORT.zh-CN.md)
- 输入约定：[KG 格式](docs/KG_FORMAT.md)
- 验证状态：[VALIDATION.md](docs/VALIDATION.md)

样例是虚构数据，不包含真实 JEDEC 内容。

## 快速开始：无需 API Key

需要 Python 3.11+（含 SQLite FTS5）。在仓库目录执行：

```powershell
python -m kg_harness demo
python -m kg_harness ask --version A --question PARAM_X
python -m kg_harness compare --old A --new B
python -m unittest discover -s tests -v
```

`demo` 自动导入两个样例，通过同一个 Agent 循环完成列目录、查询、写文件、读取、修改和差异导出。它使用 **ScriptedDemoModel 测试替身，不是真实 LLM**。`ask` 是离线关键词证据查询，不进行自由语言推理；真正的模型问答使用下面的 `agent`。

输出在 `workspace/outputs/`；执行记录在 `workspace/.state/sessions/<id>/`。报告前缀使用随机 ID，重跑不覆盖已有报告。`completed` 只表示模型/测试替身结束调用，不是业务语义正确性认证。

本机已创建 `.venv` 时，可将 `python` 替换为 `.\.venv\Scripts\python.exe`。Windows 若系统 `python` 是不可用的商店别名，请用真实解释器路径。

## 接入真实模型

支持具有 Chat Completions 工具调用协议的服务。基础运行无需第三方 SDK。

```powershell
$env:LLM_API_KEY = '<你自己的服务密钥>'
$env:LLM_MODEL = '<账户可用且支持工具调用的模型>'
$env:LLM_BASE_URL = 'https://api.openai.com/v1'
python -m kg_harness agent '读取 A 版本中 PARAM_X 的要求，补查所在章节，把带来源的答案写到 outputs/answer.md'
python -m kg_harness agent '比较 A 和 B 两个版本，检查差异并导出报告'
```

也可以指定本地兼容服务：`--base-url http://localhost:8000/v1 --model <model>`。工具调用能力取决于实际模型/服务；不假定所有兼容接口都行为一致。工具执行错误会返回模型，模型调用异常则保存失败状态，不自动重试可能产生副作用的操作。

## 直接复用 Deep Agents

```powershell
python -m pip install -e '.[deepagents,large]'
$env:OPENAI_API_KEY = '<你自己的服务密钥>'
python -m kg_harness deepagent --model 'openai:<账户可用模型>' '用 kg_ 工具读取 A/B 版本并导出差异到 outputs/deep-comparison'
```

此入口由 `create_deep_agent` 管理循环，复用同一套 Runtime 工具。模型配置与鉴权采用 LangChain 各提供商约定，和基础模式的 `LLM_API_KEY` 不同。其他提供商需要安装对应的 LangChain 集成包。

内置虚拟文件工具用于内部状态；真正的宿主文件访问使用 `kg_read_file`、`kg_write_file` 等工具。这里不把虚拟文件当作已经写到磁盘。没有附加额外宿主 shell 后端。

当前 Deep Agents 接入未配置持久 checkpointer，不能承诺重启后续跑。依赖范围是开发兼容范围，生产部署应基于验证过的组合生成锁文件。

本次通过验证的依赖版本快照已保存在 `requirements-verified.txt`。复现本次环境可以先执行 `python -m pip install -r requirements-verified.txt`，再执行 `python -m pip install -e . --no-deps`。

## 实际文件工具

```powershell
python -m kg_harness tool list_files '{"path":"inputs"}'
python -m kg_harness tool write_file '{"path":"work/note.txt","content":"hello"}'
python -m kg_harness tool read_file '{"path":"work/note.txt"}'
```

新建文件无需 hash；覆盖或 `edit_file` 必须传当前 `sha256`。修改是唯一匹配文本替换，不是完整统一 diff patch 引擎。读取偏移按字节，UTF-8 截断边界可能显示替换字符；需要完整精确文本时读取完整的小文件。

文件工具拒绝越界路径、隐藏状态和符号链接。策略适用于单用户原型，不是恶意并发写入下的原子权限保证。CLI 的 `import` 是操作员入口，agent 不拥有导入/覆盖版本工具。

## 程序执行

默认关闭。两种显式选择：

**Docker（面向不可信生成代码）**：需安装并启动 Docker，预先拉取镜像；默认不自动拉取。

```powershell
docker pull python:3.12-slim
python -m kg_harness --executor docker agent --model '<model>' '在 work/ 中创建 Python 脚本，运行并将结果保存到 outputs/'
```

容器仅挂载 inputs（只读）、work 和 outputs；无网络、只读根文件系统、资源限制。默认容器 UID 为 65534，Linux 部署需为挂载目录配置匹配的写权限。Docker 后端仍需在目标环境实际验证。

**可信本机开发**：继承当前用户的系统权限，不是沙箱。

```powershell
python -m kg_harness --executor trusted-local tool run_command '{"argv":["python","-c","print(1+1)"],"cwd":"work","timeout":10}'
```

本机模式仅清理传给子进程的环境变量、限制输出和超时；程序仍可通过系统访问工作区外文件。不要向不可信任务开放此模式。Windows 尽力用 taskkill 终止进程树，失败时终止直接子进程；后台派生进程不提供强隔离保证。

## 接入真实 KG

1. 将文件复制到 `workspace/inputs/`，按 `KG_FORMAT.md` 调整适配器或输入。
2. 大文件安装 `python -m pip install -e '.[large]'`。
3. 执行 `python -m kg_harness import inputs/your_version.json`。
4. 用 `versions`、`ask` 和 `compare` 检查结果，再接真实模型。

每个工作区当前只适合一个标准系列。不同系列可用不同 `--workspace`。输入不可由 agent 修改，版本内容不能覆盖。数百 MB 导入尚需真实数据性能测试；当前流式处理的内存上界是最大的顶层章节。

已完成约 211 MB 合成 JSON 导入检查（13,107 条记录，本机 4.010 秒），不代表真实 JEDEC 性能。复现命令：`python scripts/benchmark_import.py --mb 200`。

## 代码结构

```text
kg_harness/
  files.py                文件工具与路径策略
  execution.py            Docker/可信本机命令执行
  runtime.py              工具注册、类型检查、差异报告导出
  agent.py                最小循环、模型协议、离线测试替身
  deepagents_backend.py   复用 Deep Agents 循环
  kg.py                   可替换 JSON 适配器、SQLite、版本比较
  cli.py                  命令行入口
examples/                 两个虚构 KG 版本
tests/                    权限、修改、差异、执行与循环测试
```

第一版未实现：生产级恢复/幂等、多租户隔离、语义条款对齐、拆分合并识别、单位归一、领域专家验证、完整图遍历工具及网页界面。具体已测/未测状态见验证记录。
