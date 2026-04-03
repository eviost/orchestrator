---
name: orchestrator-v4
version: 1.1.0
description: |
  智能任务编排系统。自动扫描项目规模、规划子任务、动态派发多个 AI Worker 并行执行，支持大项目按模块拆分、自适应超时、滚动派发。
  触发条件：用户需要处理复杂任务、多步骤分析、代码生成、调试分析、研究调查或需要智能调度 AI Worker 时。
---

# Orchestrator

智能任务编排系统，让 AI Agent 具备多线程工作能力。

## 与 OpenClaw 原生 subagent 的区别

OpenClaw 提供了 `sessions_spawn` 作为派发子代理的基础能力，Orchestrator 在此基础上提供智能调度层：

| 能力 | OpenClaw 原生 | Orchestrator |
|------|--------------|--------------|
| 派发方式 | 手动调用 `sessions_spawn`，逐个派发 | 自动扫描 → 规划 → 批量派发 |
| 任务拆分 | 手动编写 prompt 拆分 | 自动按模块/功能域拆分 |
| 超时控制 | 固定超时（手动传参） | 自适应超时（小模块 5min、大模块 10min） |
| 文件读取约束 | 无约束 | 自动注入"最多读 N 个文件"限制 |
| 并发控制 | 无限制 | max_parallel 限流，超出排队 |
| 失败重试 | 无 | 缩小范围重跑 |
| 进度追踪 | 手动记录 session_key | 实时进度表格 |
| 滚动派发 | 无 | 前一批完成后自动派发下一批 |

## 核心能力（已验证）

以下功能全部经过端到端验证（2026-04-04 Claude Code 52 万行源码分析，13 个子代理零超时）：

1. **扫描 - 规划 - 派发**：scan_and_plan.py 扫描文件系统，自动规划子任务，输出 JSON 供主会话派发
2. **大项目按模块拆分**：超过 1000 文件或 10 万行代码时，自动按顶层目录识别功能模块
3. **自适应超时**：小模块（<20 文件）5 分钟、中模块（20-50 文件）8 分钟、大模块（>50 文件）10 分钟
4. **子代理文件读取约束**：自动在 prompt 中注入文件读取上限，防止子代理贪心读文件导致超时
5. **滚动派发**：按 max_parallel 分批派发，前一批完成后立即派发下一批
6. **小模块合并派发**：多个小模块合并到一个子代理，减少 spawn 开销
7. **超时重试**：超时的子任务缩小范围重跑，不原样重试
8. **任务类型自动识别**：analysis > code > debug > research > general 优先级链

## 扩展能力（代码已实现，需注入 spawn_func 才能独立运行）

以下功能在 orchestrator_v4_acp.py 中完整实现，但依赖 `spawn_func` 注入。在标准流程（Step 1-6）中由主会话的 sessions_spawn 替代：

- **三级 Worker 路由**：Fast（本地秒回）、Slow（子代理）、Long（v3_bridge 子进程+心跳）
- **审计质检**：`enable_audit=True` 时代码任务自动过审计官，REJECT 自动重做
- **暂停/恢复/改思路**：`pause_all()` / `redirect("新方向")` / `resume_with_redirect()`
- **进度追踪**：`get_progress_report()` 返回运行中/完成/失败的子任务统计
- **并发限流**：`_spawn_semaphore` 控制最大并行 subagent 数

这些功能在将来 OpenClaw 支持 spawn_func 注入后可直接启用，无需改代码。

---

## 标准执行流程（严格遵守）

当用户给出复杂任务时，主会话必须严格按以下 6 步执行：

### Step 1：规划

使用 exec 调用 scan_and_plan.py 生成规划 JSON：

```bash
cd <skill_dir>/scripts
python scan_and_plan.py \
  --task "用户的任务描述" \
  --target-dir "/path/to/project" \
  --output plan.json \
  --max-parallel 5
```

输出摘要后告知用户规划结果。

### Step 2：读取规划结果

用 read 工具读取 plan.json，提取 subtasks 列表。每个 subtask 包含：
- `description`：子任务 prompt（已含文件读取约束）
- `estimated_time_sec`：超时时间
- `module_key`：模块名
- `module_file_count`：模块文件数
- `file_read_cap`：文件读取上限

### Step 3：批量派发

按 max_parallel（默认 5）取前 N 个 subtasks，逐个调用 sessions_spawn：

```
sessions_spawn(
  agentId: "main",
  label: "orch-{module_key}",
  mode: "run",
  task: subtask.description,
  timeoutSeconds: subtask.estimated_time_sec,
  runTimeoutSeconds: subtask.estimated_time_sec,
)
```

**派发时必须输出任务表格：**

```
| # | 模块 | 文件数 | 超时 | Label | 状态 |
|---|------|--------|------|-------|------|
| 1 | tools | 184 | 600s | orch-tools | 已派发 |
| 2 | services | 136 | 600s | orch-services | 已派发 |
| 3 | hooks | 104 | 600s | orch-hooks | 已派发 |
```

### Step 4：等待完成

调用 sessions_yield 等待子代理完成推送。不主动轮询。

### Step 5：进度更新 + 滚动派发

每个子代理完成时：

1. **告知用户关键发现**（一句话概括 + 2-3 个 [重要] 标记）
2. **更新进度表格**：

```
| # | 模块 | 状态 |
|---|------|------|
| 1 | utils | 已完成 |
| 2 | components | 已完成 |
| 3 | hooks | 已完成 |
| 4 | commands | 运行中 |
| 5 | services | 运行中 |
```

3. **前一批全部完成后，立即派发下一批**（重复 Step 3-4）
4. 小模块可合并派发：一个子代理负责 3-5 个小模块

### Step 6：汇总报告

所有子代理完成后，汇总全部结果写入报告文件，内容包括：
- 项目概览（规模、架构）
- 每个模块的分析结果和关键发现
- 重大发现汇总
- 执行统计（子代理数、耗时、超时数）

---

## 前端输出规范

### 派发时
```
第 N 批 M 个子代理已全部派发：

| # | 模块 | 文件数 | 超时 | Label | 状态 |
|---|------|--------|------|-------|------|
| 1 | xxx | 184 | 600s | orch-xxx | 已派发 |
...
```

### 子代理完成时
```
{模块名} 完成（N/总数）。

**{模块名} 模块关键发现：**
- [重要] 发现 1
- [重要] 发现 2
- [重要] 发现 3

进度：N/总数 完成。
```

### 全部完成时
```
全部 N 个模块分析完成。M 个子代理，零超时。

报告已写入 reports/xxx.md
```

---

## 只规划不派发（预览模式）

```bash
python scan_and_plan.py --task "分析这个项目" --target-dir "/path" --output plan.json
```

然后 read plan.json 查看规划结果，不执行 Step 3-6。

---

## 文件说明

| 文件 | 说明 | 状态 |
|------|------|------|
| `scripts/scan_and_plan.py` | 扫描规划 CLI（Step 1 入口） | 已验证 |
| `scripts/orchestrator_v4_acp.py` | 主控（扫描+规划+路由+控制+追踪） | 已验证（规划部分） |
| `scripts/openclaw_bridge.py` | OpenClaw 桥接层（plan_only 可用） | 部分验证 |
| `scripts/lifecycle_manager.py` | 进程生命周期（重启策略、指数退避） | 代码就绪 |
| `scripts/background_monitor.py` | 后台监控（心跳、超时、回调） | 代码就绪 |
| `scripts/micro_scheduler.py` | 微调度器（优先级、DAG 依赖） | 代码就绪 |
| `scripts/v3_bridge.py` | 长任务桥接（JSON Line IPC） | 代码就绪 |
| `scripts/v3_worker.py` | 长任务 Worker 子进程 | 代码就绪 |
| `scripts/audit_agent.py` | 审计子代理 | 代码就绪 |
| `scripts/hybrid_worker_acp.py` | 混合 Worker（Fast/Slow 模板） | 代码就绪 |
| `scripts/openclaw_orchestrator_entry.py` | 统一入口 | 代码就绪 |

## 关键配置

| 配置 | 默认 | 说明 | 状态 |
|------|------|------|------|
| `max_files_per_subtask` | 2 | 每子任务最多读文件数（代码生成类） | 已验证 |
| `analysis_max_files_per_subtask` | 8 | 分析类每子任务最多读文件数 | 已验证 |
| `large_project_file_threshold` | 1000 | 大项目文件数阈值 | 已验证 |
| `large_project_line_threshold` | 100000 | 大项目行数阈值 | 已验证 |
| `analysis_small_module_timeout` | 300 | 小模块超时（秒） | 已验证 |
| `analysis_medium_module_timeout` | 480 | 中模块超时（秒） | 已验证 |
| `analysis_large_module_timeout` | 600 | 大模块超时（秒） | 已验证 |
| `max_parallel_subagents` | 3 | 同时运行的子代理数 | 已验证 |
| `enable_audit` | False | 启用审计质检 | 需 spawn_func |
| `enable_micro_scheduler` | False | 启用并发调度 | 需 spawn_func |
| `enable_task_planning` | True | 启用任务预规划 | 已验证 |

## 大项目分析策略

当目标项目超过 1000 个文件或 10 万行代码时，自动切换为大项目分析模式：

1. **模块识别**：按顶层目录识别功能模块，不按文件数机械切片
2. **小模块合并**：文件数少于 5 的模块合并为一组
3. **Prompt 约束注入**：每个子任务 prompt 自动注入文件读取上限
4. **自适应超时**：小于 20 文件 5 分钟，20-50 文件 8 分钟，超过 50 文件 10 分钟
5. **超时重试**：超时的子任务缩小范围重跑，不原样重试
6. **滚动派发**：按 max_parallel 分批，前一批完成后立即派发下一批
7. **小模块合并派发**：多个小模块合并到一个子代理，减少 spawn 开销

## 注意事项

1. 派子代理时必须输出任务表格
2. 子代理完成时立即通知用户进度和关键发现
3. 执行过程中主会话保持可交互，不挂起
4. 分析类任务的子代理 prompt 必须包含文件读取约束
5. 超时的子任务缩小范围重跑，不原样重试
6. 小模块合并到一个子代理时，prompt 里列出所有模块的目录
