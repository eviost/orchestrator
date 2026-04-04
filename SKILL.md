---
name: orchestrator-v4
version: 2.1.0
description: |
  智能任务编排系统。自动扫描项目规模、规划子任务、动态派发多个 AI Worker 并行执行，支持大项目按模块拆分、自适应超时、滚动派发、用户随时打断改思路。
  触发条件：用户需要处理复杂任务、多步骤分析、代码生成、调试分析、研究调查或需要智能调度 AI Worker 时。
---

# Orchestrator V4

智能任务编排系统，为主会话提供自动规划和批量派发能力。

## 核心能力

### 规划引擎（纯计算，无外部依赖）

- **scan_task_scope()**：扫描文件系统，统计文件数/行数/体积，识别顶层功能模块
- **plan_complex_task()**：自动拆分子任务，计算超时，生成含文件读取约束的 prompt
- **scan_and_plan.py CLI**：命令行入口，输出 JSON 供主会话读取和派发
- **任务类型自动识别**：analysis > code > debug > research > general 优先级链

### 大项目智能拆分

- **大项目检测**：超过 1000 文件或 10 万行代码时自动切换大项目模式
- **按模块拆分**：按顶层目录识别功能模块，不按文件数机械切片
- **小模块智能合并**：文件数 ≤20 且行数 ≤2000 的模块视为小模块，按负载贪心装箱合并（单批上限 60 文件 / 5000 行），减少子代理数量和批次
- **自适应超时**：小模块（<20 文件）5min、中模块（20-50 文件）8min、大模块（>50 文件）10min
- **文件读取约束注入**：每个子任务 prompt 自动注入"最多读 N 个文件"

### 派发与执行（主会话通过 sessions_spawn 执行）

- **滚动派发**：按 max_parallel 分批，前一批完成后立即派发下一批
- **超时重试**：超时的子任务缩小范围重跑，不原样重试
- **进度追踪**：实时进度表格，每个子代理完成时输出关键发现

### 用户交互控制（主会话原生支持）

- **用户随时打断**：子代理运行期间主会话保持可交互，用户随时可以发消息
- **暂停派发**：用户说"暂停"时，主会话停止派发新的子代理（已派发的继续运行至完成或超时）
- **改思路**：用户说"改方向"时，主会话调整后续子任务的 prompt 或取消剩余派发
- **恢复**：用户说"继续"时，主会话按新的或原有规划继续派发

---

## 标准执行流程

### Step 1：规划

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
第 N 批 M 个子代理已派发：

| # | 模块 | 文件数 | 超时 | Label |
|---|------|--------|------|-------|
| 1 | tools | 184 | 600s | orch-tools |
| 2 | services | 136 | 600s | orch-services |
| 3 | hooks | 104 | 600s | orch-hooks |
```

### Step 4：等待完成

调用 sessions_yield 等待子代理完成推送。不主动轮询。

用户可随时发消息打断：
- "暂停" → 停止派发新的子代理
- "改思路：xxx" → 调整后续子任务 prompt
- "继续" → 恢复派发

### Step 5：进度更新 + 滚动派发

每个子代理完成时：

1. **告知用户关键发现**（一句话概括 + 2-3 个 [重要] 标记）
2. **更新进度**：N/总数 完成
3. **前一批全部完成后，立即派发下一批**（重复 Step 3-4）
4. 小模块可合并派发：一个子代理负责 3-5 个小模块

### Step 6：汇总报告

所有子代理完成后，汇总全部结果写入报告文件。

---

## 关键配置

| 配置 | 默认 | 说明 |
|------|------|------|
| `max_files_per_subtask` | 2 | 每子任务最多读文件数（代码生成类） |
| `analysis_max_files_per_subtask` | 8 | 分析类每子任务最多读文件数 |
| `large_project_file_threshold` | 1000 | 大项目文件数阈值 |
| `large_project_line_threshold` | 100000 | 大项目行数阈值 |
| `analysis_small_module_timeout` | 300 | 小模块超时（秒） |
| `analysis_medium_module_timeout` | 480 | 中模块超时（秒） |
| `analysis_large_module_timeout` | 600 | 大模块超时（秒） |
| `max_parallel_subagents` | 3 | 同时运行的子代理数 |

---

## 与 OpenClaw 原生 subagent 的区别

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
| 用户打断 | 需手动管理 | 随时打断，暂停/改思路/恢复 |

---

## 前端输出规范

### 派发时
```
第 N 批 M 个子代理已派发：

| # | 模块 | 文件数 | 超时 | Label |
|---|------|--------|------|-------|
| 1 | xxx | 184 | 600s | orch-xxx |
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

## 文件说明

| 文件 | 说明 | 状态 |
|------|------|------|
| `scripts/scan_and_plan.py` | 扫描规划 CLI（Step 1 入口） | 已验证 |
| `scripts/orchestrator_v4_acp.py` | 主控（扫描+规划+路由+控制+追踪） | 规划部分已验证 |
| `scripts/openclaw_bridge.py` | OpenClaw 桥接层（plan_only 可用） | 部分验证 |
| `scripts/lifecycle_manager.py` | 进程生命周期（重启策略、指数退避） | 代码就绪 |
| `scripts/background_monitor.py` | 后台监控（心跳、超时、回调） | 代码就绪 |
| `scripts/micro_scheduler.py` | 微调度器（优先级、DAG 依赖） | 代码就绪 |
| `scripts/v3_bridge.py` | 长任务桥接（JSON Line IPC） | 代码就绪 |
| `scripts/v3_worker.py` | 长任务 Worker 子进程 | 代码就绪 |
| `scripts/audit_agent.py` | 审计子代理 | 代码就绪 |
| `scripts/hybrid_worker_acp.py` | 混合 Worker（Fast/Slow 模板） | 代码就绪 |
| `scripts/openclaw_orchestrator_entry.py` | 统一入口 | 代码就绪 |

---

## 注意事项

1. 派子代理时必须输出任务表格
2. 子代理完成时立即通知用户进度和关键发现
3. 执行过程中主会话保持可交互，用户随时可打断
4. 分析类任务的子代理 prompt 必须包含文件读取约束
5. 超时的子任务缩小范围重跑，不原样重试
6. 小模块合并到一个子代理时，prompt 里列出所有模块的目录
7. 用户说"暂停"时停止派发新子代理，说"继续"时恢复

---

## Python API（需注入 spawn_func）

以下功能在 orchestrator_v4_acp.py 中完整实现，当前在标准流程中由主会话的 sessions_spawn 替代。将来 OpenClaw 支持 Python SDK 后可直接启用：

- **handle()**：端到端执行（扫描→规划→派发→收集→汇总）
- **三级 Worker 路由**：Fast（本地秒回）、Slow（子代理）、Long（v3_bridge 子进程+心跳）
- **审计质检**：`enable_audit=True` 时代码任务自动过审计官，REJECT 自动重做
- **pause_all() / redirect() / resume_with_redirect()**：Orchestrator 内部子代理的暂停/改思路控制
- **get_progress_report()**：Orchestrator 内部的任务统计
- **并发限流**：`_spawn_semaphore` 控制最大并行 subagent 数
