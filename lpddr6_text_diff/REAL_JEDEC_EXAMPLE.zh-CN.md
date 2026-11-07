# 真实 JEDEC 修订版的局部正文 diff

用户允许用任意两个真实版本检验方法。因此选用可明确核对前后关系的 **JEDEC JESD209-4D（2021）→ JESD209-4E（2024）**，属于 LPDDR4 标准，不是 LPDDR6，也不是 Micron 产品数据手册。出版商目录确认 4E 接替 4D，公开预览均能检索到第 1 节 Scope。[4D 预览](https://store.accuristech.com/aia/products/preview/2505640)、[4E 预览](https://store.accuristech.com/products/preview/2906163)、[修订关系](https://www.intertekinform.com/en-us/standards/jedec-jesd209-4d-2021-1178940_saig_jedec_jedec_3209364/)

下面只使用预览中两条短的密度范围片段；没有取得完整 PDF，因此**不是全标准 diff，也没有整文档的对齐或准确率**。没有复制原始 PDF 到仓库。

| 旧 4D Scope | 新 4E Scope | token diff |
|---|---|---|
| `dual channel device density ranges from 4 Gb through 32 Gb` | `dual channel device density ranges from 2 Gb through 32 Gb` | `4 → 2` |
| `single channel density ranges from 2 Gb through 16 Gb` | `single channel density ranges from 1 Gb through 16 Gb` | `2 → 1` |

在已经知道两段都属于 Scope 的前提下，脚本对每个旧片段同时计算两个新片段的词面匹配分：

| 旧片段 | 新版双通道候选 | 新版单通道候选 | 选中 |
|---|---:|---:|---|
| 旧双通道 | **0.9091** | 0.6667 | 新双通道 |
| 旧单通道 | 0.7619 | **0.9000** | 新单通道 |

这一步仅判断片段对应关系。随后 token diff 找到两个数字替换。以 Scope 的原句含义看，两个范围的**下限下降、上限不变**，即该 Scope 所描述的设备密度范围扩大；这不等于断言某款具体器件已经支持新范围，也不能推断标准其他条款的变化。

运行脚本：[real_jedec_scope.py](experiments/real_jedec_scope.py)。保存的逐候选机器结果：[real_jedec_scope.result.json](experiments/real_jedec_scope.result.json)。

```powershell
python lpddr6_text_diff/experiments/real_jedec_scope.py
```

脚本只使用 Python 标准库，词面分采用双向 `SequenceMatcher` 的平均值；未调用 text encoder 或 LLM。0.9091 和 0.9000 是**对应内容的匹配分，不是“规范相同概率”**。由于只输入两个已知 Scope 片段，不能用结果证明生产系统能从数百 MB 文档自动找出它们。真实完整版本对的下一步应导入两个全文解析结果，运行章节/段落候选生成、拆合与全局移动回查，再让专家检查漏检。
