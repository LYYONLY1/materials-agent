# 材料计算 Agent

输入材料问题或计算请求。Agent 可以检索样例资料、询问缺失的参数，或把计算交给后台。工作台展示运行节点、任务状态、耗时和失败原因。

## 运行

需要 Python 3.11 及以上和 uv。以下命令在仓库根目录执行。

```sh
uv sync --locked
uv run --locked uvicorn materials_agent.api:app --host 127.0.0.1 --port 8000
```

打开 [结构实验室](http://127.0.0.1:8000/)、[研究 Agent](http://127.0.0.1:8000/agent) 或 [API 文档](http://127.0.0.1:8000/docs)。无需模型密钥即可运行结构实验。研究 Agent 默认使用离线路由，模拟评分用于验证任务系统。材料条目是人工整理的小型资料集。

## 结构实验室

1. 选择铜、铝、镍样例，或导入自己的单帧 XYZ。XYZ 首行填写原子数，第二行是注释，每行写一个元素符号及三个笛卡尔坐标，单位为 Å。晶胞边长单独填写。
2. 在 3Dmol.js 视图里拖动、缩放，确认结构后选择单点能量或几何优化并提交。实际计算由 ASE EMT 和 BFGS 执行。
3. 对照初始与最终结构及最大原子受力。可下载两个阶段的 extxyz 和每一步的 CSV，通过实验历史重新打开运行。

结构实验当前接受 1–128 个原子，支持 Al、Ni、Cu、Pd、Ag、Pt、Au，使用固定立方周期晶胞和 EMT 经验势。结构实验与研究 Agent 共享任务队列、幂等和 SSE 事件流。研究 Agent 新生成的 ASE 结果也可以跳转到实验室做三维对照。[实验室截图](docs/media/structure_lab.png)

## 研究 Agent 演示

| 输入 | 操作与预期 |
| --- | --- |
| 查一下硅的资料 | 查看引用的 PubChem 链接和检索步骤 |
| 硅的晶体结构是什么？ | 查看检索、排序、回答和引用的独立轨迹 |
| 先查硅的资料，再提交能量计算 | 检索完成后先看证据和审批参数，批准后入队，拒绝则结束本轮 |
| 铝结构优化 | 点击同名预设，检查引用和参数，批准后查看收敛、能量和最大力，下载 extxyz |
| 提交硅的能量计算 | 看到任务入队、执行一次、生成模拟结果 |
| 提交能量计算 | 等待补充材料。重启服务后打开原运行地址，选择材料并继续 |
| 提交铝的能量计算 | 选择「第一次超时，重试成功」。轨迹显示首轮超时、第二次成功 |
| 模拟硅的几何优化 | 选择「两次超时」。用完两次尝试后进入失败状态 |

```sh
uv run --locked pytest -v
```

在当前 Windows 工作区，如系统临时目录不可访问，可以使用 `uv run --locked pytest -v --basetemp var/pytest-run`。该路径由 pytest 管理，使用专用目录。

运行截图：[铝结构优化与产物](docs/media/aluminum_relaxation.png) · [移动端深色模式](docs/media/mobile_dark.png)

## 关键代码

| 知识点 | 实现 |
| --- | --- |
| Prompt、工具参数与结构化输出 | `planner.py` 定义路由工具，通过 Pydantic 验证选择和参数。真实模型用 function calling，离线模式用确定性规则 |
| 检索、引用和上下文 | `retrieval.py` 提供混合召回和 Markdown 切片。离线模式返回最高分证据，真实模型模式根据候选生成回答并提交引用 ID |
| Agent 与工作流 | 模型选择动作并提取参数。`workflow.py` 负责校验、检索、审批、恢复和提交 |
| 短期状态与任务状态 | LangGraph 的检查点保留当前运行参数。SQLite 的任务表保存后台状态、结果和执行事件 |
| 异步、去重和故障恢复 | `POST /api/runs` 可传 `Idempotency-Key`。任务表每个运行 ID 仅有一条任务，保证检查点重放时复用原任务 |
| 可靠性与评测 | `tests/test_agent.py` 验证节点轨迹、来源、并发重复请求、上下文恢复、超时上限、过期租约和模拟模型接口 |

前端用 SSE 订阅持久化的后台事件。服务端按事件 ID 分页读取，使用心跳维持空闲连接。客户端初次订阅使用快照游标，断线可用 `Last-Event-ID` 补读，多次断线后改用轮询。Agent 的运行和后台任务各有自己的 ID，审批入队后后台任务可能仍在执行。

Worker 领取任务时写入租约和令牌。进程退出后，新的 worker 可以在租约过期时重新领取，旧令牌无法覆盖新结果。第一次超时或租约过期可以再试一次。跨进程重试可能重新执行纯计算，数据库只接受有效领取者提交的一份结果。若接入有外部副作用的工具，工具本身也需要支持幂等请求。

这是单机、单服务进程的项目。面试时可以用测试讨论如何将任务表升级到支持多工作节点的实现。微调、GPU 推理和分布式调度属于可继续研究的方向。

## 本地材料计算

选择「ASE / EMT」可计算铝的单点势能，或用 BFGS 在固定晶胞下优化原子坐标。样例从一个有初始扰动的四原子周期晶胞开始。结果记录势能（eV）、最大原子受力（eV/Å）、收敛状态和步数，完成后可下载 extxyz。EMT 是经验势，当前只接入铝样例。

真实材料计算始终经过审批，在有超时限制的独立子进程运行。默认的模拟后端保留超时与重试演练；两种计算后端均可搭配离线路由。

## 检索、MCP 与评测

- 用 `MATERIALS_KNOWLEDGE_DIR` 指定本机 UTF-8 Markdown 资料目录，重启后建立索引。按标题分段，长段按 450 字符窗口、60 字符重叠切片，保留文件名和标题作为引用。默认语料是随项目提供的资料卡。配置了真实模型时，命中的资料片段会随问题发给模型服务。
- 检索融合 BM25 与字符 n-gram 余弦排序，再按领域短语重排。生成路径受候选上限约束，模型只能引用检索结果中的 ID。引用合法性与回答事实一致性是两类验证。
- 运行 `uv run --locked python -m materials_agent.mcp_server` 启动本地 stdio MCP 服务。MCP 客户端设置项目目录为工作目录，或显式设置与 API 相同的 `MATERIALS_DATA_DIR`。工具仅能检索资料、查询任务。计算提交留在应用的审批工作流。

```sh
uv run --locked python -m materials_agent.evaluation --out var/retrieval-report.json
uv run --locked python -m materials_agent.benchmark --port 8000 --requests 40 --concurrency 4
```

检索报告包括逐题结果、Recall@3、MRR 和无关题拒答率。压测只访问本机检索接口，输出成功数、P50/P95、完成吞吐和 SLO 内吞吐。实现、边界和追问见 [面试对照笔记](docs/interview-notes.md)。

## 面试演示

先提交一个正常任务，再选择首次超时场景，展示失败节点和两次执行记录。接着打开 `test_replay_after_task_commit_does_not_enqueue_twice`。这个测试主动模拟任务已经写入 SQLite、工作流尚未保存结果时的中断。用相同的请求键重新提交后，工作流续跑，仍返回原任务 ID。

可以顺着演示解释三个区别：任务的运行状态和 Agent 的执行状态各存在哪里，API 请求去重和 Worker 重试解决了什么问题，哪些测试使用离线路由、哪些使用模拟模型接口。

## 可选真实模型

在启动服务的终端中设置 `MATERIALS_MODEL_BASE_URL`、`MATERIALS_MODEL_NAME` 和 `MATERIALS_MODEL_API_KEY`。API 地址填用户选定服务的 Chat Completions 基础 URL，适配器会添加 `/chat/completions`。模型需要支持 function calling。真实模型模式会将问题与相应资料摘要发送给配置的服务。

## Git 分支

`main` 汇总已合入的功能。打开 `git log --graph --oneline --all` 可以看到以下功能分支：

- `feat/agent-workflow`：检索、路由和工作流
- `feat/durable-tasks`：持久任务、租约、重试
- `feat/evaluation-demo`：回归测试、工作台和 CI
- `feat/interview-engineering`：检索评测、复合任务审批、SSE 和 MCP
- `feat/complete-workbench`：ASE 计算与结构产物、事件分页和断线补读
- `feat/structure-lab`：上游三维查看器、自定义结构实验、轨迹和历史

试做一个小改动时，可以从 `main` 开 `feat/add-material`，先补资料和测试，再提交。推到 GitHub 后就可以用 PR 查看差异和 CI。合并前先确认同一个测试在本地复现。

## 设计参考

- [开源代码对照、许可证与引用](docs/open-source-references.md)
- 工作台的悬浮导航、系统外观适配和交互动效参考了 iOS 27 的 Liquid Glass 设计指南。[材质](https://developer.apple.com/design/human-interface-guidelines/materials) · [动效](https://developer.apple.com/design/human-interface-guidelines/motion)
- [LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Coze Loop](https://github.com/coze-dev/coze-loop)
- [Huey](https://github.com/coleifer/huey)
- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)
