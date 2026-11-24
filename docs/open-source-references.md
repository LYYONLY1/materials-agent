# 开源代码参考

按 2026 年 11 月 24 日检索时可见的 GitHub Star 约数记录关注度。Star 表示仓库受关注程度。

## Agent 状态和恢复

LangGraph（约 4.45 万 Star，MIT）的 SQLite 检查点实现按线程和检查点组织运行状态。本项目直接使用 `SqliteSaver`，在 `materials_agent/workflow.py` 持久化等待审批的状态。后台任务另存到 SQLite，重复提交时按运行 ID 找回已有任务。

[GitHub 仓库](https://github.com/langchain-ai/langgraph) · [SQLite 实现](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py) · [MIT 许可证](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint/LICENSE)

## MCP 工具接口

MCP Python SDK（约 2.49 万 Star，MIT）的示例展示如何声明工具的结构化结果，以及如何通过 stdio 暴露工具。本项目在 `materials_agent/mcp_server.py` 使用 SDK，只暴露资料检索和任务查询，测试直接启动 stdio 子进程调用。

[GitHub 仓库及许可证](https://github.com/modelcontextprotocol/python-sdk) · [结构化输出示例](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/lowlevel/structured_output.py)

## 检索与排序

Sentence Transformers（约 1.93 万 Star，Apache-2.0）的检索示例先从语料召回候选，再对候选重排。本项目在 `materials_agent/retrieval.py` 使用同样的阶段划分，具体实现是 BM25 和字符 n-gram 召回，加领域短语重排。

[GitHub 仓库及许可证](https://github.com/huggingface/sentence-transformers) · [检索和重排示例](https://github.com/huggingface/sentence-transformers/blob/main/examples/sentence_transformer/applications/retrieve_rerank/README.md)

## 轨迹和评测

Coze Loop（约 5.8 千 Star，Apache-2.0）将调用轨迹和离线评测分别建模。本项目在 `materials_agent/workflow.py` 记录路由、检索、审批和任务提交，在 `materials_agent/evaluation.py` 用固定查询集对比检索策略。

[GitHub 仓库及许可证](https://github.com/coze-dev/coze-loop) · [架构](https://github.com/coze-dev/coze-loop/wiki/3.-Architecture)

## 事件流

Starlette 的 `StreamingResponse` 将异步迭代器产出的内容发送给客户端。本项目在 `materials_agent/api.py` 使用该接口发送 SSE，并在应用侧实现持久游标、分页补读和心跳。SQLite 事件表带有 `(task_id, id)` 复合索引。

[GitHub 仓库](https://github.com/Kludex/starlette) · [StreamingResponse 源码](https://github.com/Kludex/starlette/blob/main/starlette/responses.py)

## 计算工具

Atomic Simulation Environment（ASE，LGPL）在 `materials_agent/calculator.py` 作为直接依赖使用。调用它的公开接口构造周期铝晶胞、计算 EMT 势能和受力、运行 BFGS 并导出结构。ASE 的官方源码托管在 GitLab。

[ASE 官方文档与许可证信息](https://ase.gitlab.io/ase/index.html) · [EMT 源码](https://gitlab.com/ase/ase/-/blob/master/ase/calculators/emt.py) · [BFGS 文档](https://ase.gitlab.io/ase/ase/optimize.html)

## 三维晶体查看

3Dmol.js（约 1 千 Star，BSD-3-Clause）负责 WebGL 原子渲染、拖动旋转和缩放。仓库内直接保留上游 npm 2.5.3 的 `build/3Dmol-min.js` 与两份许可文件，离线启动即可加载。`materials_agent/web/lab.js` 通过公共 API 创建查看器、加载 XYZ 数据并切换初始与最终结构。

[GitHub 仓库](https://github.com/3dmol/3Dmol.js) · [2.5.3 发行包](https://registry.npmjs.org/3dmol/-/3dmol-2.5.3.tgz) · [论文](https://doi.org/10.1093/bioinformatics/btu829)

第三方构建产物和许可文件位于 `materials_agent/web/vendor/`。构建产物 SHA-256 为 `bcf422137a34b4e206413a8a83a67c24a1ace84e282bf3b164f6bda6aeb42a20`。Python 依赖版本记录在 `pyproject.toml` 和 `uv.lock`。
