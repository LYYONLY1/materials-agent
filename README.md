# 材料计算 Agent

输入材料问题或计算请求。Agent 可以检索样例资料、询问缺失的参数，或把计算交给后台。工作台展示运行节点、任务状态、耗时和失败原因。

## 运行

需要 Python 3.11 及以上和 uv。以下命令在仓库根目录执行。

```sh
uv sync --locked
uv run --locked uvicorn materials_agent.api:app --host 127.0.0.1 --port 8000
```

打开 [工作台](http://127.0.0.1:8000/) 或 [API 文档](http://127.0.0.1:8000/docs)。默认使用确定性的离线路由和模拟计算，无需模型密钥。模拟评分只用来验证任务系统。材料条目是人工整理的小型资料集。

## 演示

| 输入 | 操作与预期 |
| --- | --- |
| 查一下硅的资料 | 查看引用的 PubChem 链接和检索步骤 |
| 提交硅的能量计算 | 看到任务入队、执行一次、生成模拟结果 |
| 提交能量计算 | 等待补充材料。重启服务后打开原运行地址，选择材料并继续 |
| 提交铝的能量计算 | 选择「第一次超时，重试成功」。轨迹显示首轮超时、第二次成功 |
| 模拟硅的几何优化 | 选择「两次超时」。用完两次尝试后进入失败状态 |

```sh
uv run --locked pytest -v
```

在当前 Windows 工作区，如系统临时目录不可访问，可以使用 `uv run --locked pytest -v --basetemp var/pytest-run`。该路径由 pytest 管理，使用专用目录。

运行截图：[正常任务](docs/media/normal_task.png) · [超时重试](docs/media/timeout_retry.png) · [回归测试](docs/media/regression_results.png)

## 关键代码

| 知识点 | 实现 |
| --- | --- |
| Prompt、工具参数与结构化输出 | `planner.py` 定义路由工具，通过 Pydantic 验证选择和参数。真实模型用 function calling，离线模式用确定性规则 |
| 检索、引用和上下文 | `catalog.py` 提供固定材料资料卡。查询节点选中条目后，离线模式直接返回摘要，真实模型模式根据资料卡生成回答并保留独立来源 |
| Agent 与工作流 | 模型只决定查资料还是计算，并提取参数。`workflow.py` 负责强制校验、暂停、恢复和提交 |
| 短期状态与任务状态 | LangGraph 的检查点保留当前运行参数。SQLite 的任务表保存后台状态、结果和执行事件 |
| 异步、去重和故障恢复 | `POST /api/runs` 可传 `Idempotency-Key`。任务表每个运行 ID 仅有一条任务，保证检查点重放时复用原任务 |
| 可靠性与评测 | `tests/test_agent.py` 验证节点轨迹、来源、并发重复请求、上下文恢复、超时上限、过期租约和模拟模型接口 |

前端轮询任务 API。运行 ID 和任务 ID 分开：工作流完成代表本轮已经回答或入队，后台任务还可能正在执行。

Worker 领取任务时写入租约和令牌。进程退出后，新的 worker 可以在租约过期时重新领取，旧令牌无法覆盖新结果。第一次超时或租约过期可以再试一次。跨进程重试可能重新执行纯计算，数据库只接受有效领取者提交的一份结果。若接入有外部副作用的工具，工具本身也需要支持幂等请求。

这是单机、单服务进程的项目。面试时可以用测试讨论如何将任务表升级到支持多工作节点的实现。微调、GPU 推理和分布式调度属于可继续研究的方向。

## 面试演示

先提交一个正常任务，再选择首次超时场景，展示失败节点和两次执行记录。接着打开 `test_replay_after_task_commit_does_not_enqueue_twice`。这个测试主动模拟任务已经写入 SQLite、工作流尚未保存结果时的中断。用相同的请求键重新提交后，工作流续跑，仍返回原任务 ID。

可以顺着演示解释三个区别：任务的运行状态和 Agent 的执行状态各存在哪里，API 请求去重和 Worker 重试解决了什么问题，哪些测试使用离线路由、哪些使用模拟模型接口。

## 可选真实模型

在启动服务的终端中设置 `MATERIALS_MODEL_BASE_URL`、`MATERIALS_MODEL_NAME` 和 `MATERIALS_MODEL_API_KEY`。API 地址填用户选定服务的 Chat Completions 基础 URL，适配器会添加 `/chat/completions`。模型需要支持 function calling。真实模型模式会将问题与相应资料摘要发送给配置的服务。

## Git 分支

`main` 汇总已合入的功能。打开 `git log --graph --oneline --all` 可以看到三条功能线：

- `feat/agent-workflow`：检索、路由和工作流
- `feat/durable-tasks`：持久任务、租约、重试
- `feat/evaluation-demo`：回归测试、工作台和 CI

试做一个小改动时，可以从 `main` 开 `feat/add-material`，先补资料和测试，再提交。推到 GitHub 后就可以用 PR 查看差异和 CI。合并前先确认同一个测试在本地复现。

## 设计参考

- [LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Coze Loop](https://github.com/coze-dev/coze-loop)
- [Huey](https://github.com/coleifer/huey)
- [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)
