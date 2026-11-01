# 验证记录

日期：2026-11-01。环境：Windows，Python 3.12；项目本地 `.venv`。

## 已执行

| 检查 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 20 项：19 通过、1 跳过，0 失败；本次耗时 4.103 秒 |
| 文件新建、读取、精确修改、冲突拒绝 | 通过；实际检查磁盘内容 |
| 路径穿越、隐藏状态、只读输入、参数类型、禁用工具 | 通过 |
| 符号链接越界测试 | 跳过：当前 Windows 环境不允许无特权创建符号链接 |
| 本机程序执行、输出截断、超时终止 | 通过；执行生成文件的 Python 程序及 sleep 超时用例 |
| 版本隔离、差异值、章节重编号、来源-only 变化 | 通过 |
| 重复导入幂等、重复 key 和悬空边回滚 | 通过 |
| 真实 JSON/Markdown 差异文件输出及拒绝覆盖 | 通过 |
| Agent 循环、错误回传、步数/上下文上限、状态日志 | 通过；使用确定性测试模型 |
| Chat Completions 请求构造 | 本地 mock 通过；未调用外部模型 |
| Deep Agents 实际集成 | `deepagents==0.7.32` 的真实循环调用自定义工具并写入磁盘；模型为确定性测试替身 |
| ijson 适配器 | 流式解析与小文件内存解析结果一致 |
| CLI demo / ask / compare / tool | 已执行，产出真实文件及可追溯查询结果 |
| `pip check` | No broken requirements found |
| Python 编译检查 | 通过 |

## 大文件导入检查

使用 `scripts/benchmark_import.py` 生成合成章节式 JSON。最终记录见 `benchmark-result.json`。

- 输入：210,845,309 字节（约 211 MB / 201 MiB）。
- 顶层章节/规范化记录：13,107。
- 导入耗时：4.010 秒，包含解析、源文件哈希、SQLite 写入与 FTS5 索引；不含测试文件生成。
- 导入后查询成功，返回限制为 8 条的命中结果。

该结果只说明当前机器上此合成形状的导入链路可工作。输入是重复文本、许多较小的顶层章节，没有模拟真实 JEDEC 表格、密集关系或单个超大章节；未测峰值内存，不能外推为真实业务吞吐承诺。

复现：

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_import.py --mb 200
```

## 当前未验证

- 未提供模型服务配置/密钥，因此没有进行真实 LLM 端到端任务质量测试；没有偷偷复用当前聊天的模型凭据。
- 当前环境没有 Docker 命令，Docker 后端的参数已实现但未进行实际容器运行或隔离验证。
- 没有真实 JEDEC 文件，未验证原始文档溯源、实际格式适配、跨版本身份对齐和业务正确性。
- 没有并发写入、恶意进程、多租户或恢复后的幂等保障验证。trusted-local 不是沙箱。

## 依赖复现

已安装的可选依赖包括 `ijson==3.6.0`、`deepagents==0.7.32`、`langchain-core==1.7.3`、`langchain-openai==1.7.3`。完整版本快照在 `requirements-verified.txt`，用于复现本次 Windows/Python 3.12 开发环境，不是跨平台带哈希的供应链锁文件。
