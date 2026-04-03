---
name: orchestrator-v4
version: 1.0.0
description: |
  智能任务编排系统。自动扫描项目规模、规划子任务、动态派发多个 AI Worker 并行执行，支持大项目按模块拆分、自适应超时、审计质检、暂停/恢复/改思路。
  触发条件：用户需要处理复杂任务、多步骤分析、代码生成、调试分析、研究调查或需要智能调度 AI Worker 时。
---

# Orchestrator

智能任务编排系统，让 AI Agent 具备多线程工作能力。

## 核心能力

1. **扫描 - 规划 - 派发**：扫描文件系统（文件数、行数、体积），规划子任务数量和拆分策略，动态派发
2. **三级 Worker 路由**：简单任务 Fast（秒回）、中等任务 Slow（子代理）、重量级任务 Long（子进程+心跳）
3. **大项目按模块拆分**：超过 1000 文件或 10 万行代码时，自动按顶层目录识别功能模块，按模块分配子任务
4. **自适应超时**：根据模块规模动态计算超时时间，小模块 5 分钟、中模块 8 分钟、大模块 10 分钟
5. **子代理文件读取约束**：自动在 prompt 中注入文件读取上限，防止子代理贪心读文件导致超时
6. **并发限流**：`max_parallel_subagents` 控制同时运行数，超出的排队等候，滚动补位
7. **失败自动重试**：指数退避（1s - 2s - 4s），超时的子任务自动缩小范围重跑
8. **审计质检**：代码任务可选过审计官，REJECT 自动重做
9. **暂停/恢复/改思路**：`pause_all()` 冻结、`redirect("新方向")` 改思路、`resume_with_redirect()` 按新方向继续
10. **进度追踪**：`get_progress_report()` 实时查看子代理状态
11. **OpenClaw Bridge**：桥接层提供一键规划+派发入口，与 OpenClaw 主会话的 sessions_spawn 能力无缝对接

## 使用方法

### 方式一：OpenClaw Bridge 一键调用（推荐）

```python
from openclaw_bridge import run_orchestrated_task

result = await run_orchestrated_task(
    task="分析这个项目的架构",
    target_dir="/path/to/project",
    sessions_spawn_func=sessions_spawn,
    max_parallel=5,
)

print(result["summary"])
# 大项目检测：1936 个文件，528454 行代码，按 25 个模块拆分，已派发 5 个子任务

sessions_yield("等待子任务完成...")
```

### 方式二：只规划不派发

```python
from openclaw_bridge import plan_only

result = await plan_only(
    task="分析这个项目",
    target_dir="/path/to/project",
)

print(f"子任务数: {result['plan']['total_subtasks']}")
print(f"策略: {result['plan']['strategy']}")
for st in result['plan']['subtasks'][:5]:
    print(f"  {st['id']}: {st.get('module_key', 'N/A')}")
```

### 方式三：手动控制（高级）

```python
from openclaw_bridge import OpenClawBridge

bridge = OpenClawBridge(sessions_spawn_func=sessions_spawn)

# 规划但不派发
result = await bridge.plan_and_spawn(
    task="分析项目",
    target_dir="/path",
    auto_spawn=False,
)

# 手动派发前 3 个
spawned = await bridge.spawn_next_batch(result["plan"], already_spawned=0, batch_size=3)

# 第一批完成后派发下一批
spawned2 = await bridge.spawn_next_batch(result["plan"], already_spawned=3, batch_size=3)
```

### 直接使用 Orchestrator 核心

```python
from orchestrator_v4_acp import OrchestratorV4ACP, OrchestratorConfig

orch = OrchestratorV4ACP(OrchestratorConfig())

# 扫描
scan = orch.scan_task_scope("分析项目代码", target_dir="/path/to/project")

# 规划
plan = orch.plan_complex_task("写技术报告", context={"target_dir": "/path/to/project"})

# 执行
response = await orch.handle("写技术报告")
```

### 运行时控制

```python
orch.pause_all()                           # 暂停
orch.redirect("改成用 Go 实现")              # 改思路
new_task = orch.resume_with_redirect()      # 恢复
orch.stop_all()                             # 终止

progress = orch.get_progress_report()       # 查进度
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `scripts/openclaw_bridge.py` | OpenClaw 主会话桥接层（规划+派发一键入口） |
| `scripts/orchestrator_v4_acp.py` | 主控（扫描+规划+路由+spawn+审计+控制+追踪） |
| `scripts/lifecycle_manager.py` | 进程生命周期（重启策略、指数退避） |
| `scripts/background_monitor.py` | 后台监控（心跳、超时、回调） |
| `scripts/micro_scheduler.py` | 微调度器（优先级、DAG 依赖、并发限制） |
| `scripts/v3_bridge.py` | 长任务桥接（JSON Line IPC） |
| `scripts/v3_worker.py` | 长任务 Worker 子进程 |
| `scripts/audit_agent.py` | 审计子代理 |
| `scripts/hybrid_worker_acp.py` | 混合 Worker（Fast/Slow 模板） |
| `scripts/openclaw_orchestrator_entry.py` | 统一入口 |

## 关键配置

| 配置 | 默认 | 说明 |
|------|------|------|
| `max_parallel_subagents` | 3 | 同时运行的子代理数 |
| `max_files_per_subtask` | 2 | 每个子任务最多读的文件数（代码生成类） |
| `analysis_max_files_per_subtask` | 8 | 分析类任务每个子任务最多读的文件数 |
| `large_project_file_threshold` | 1000 | 大项目文件数阈值 |
| `large_project_line_threshold` | 100000 | 大项目行数阈值 |
| `analysis_small_module_timeout` | 300 | 小模块超时（秒） |
| `analysis_medium_module_timeout` | 480 | 中模块超时（秒） |
| `analysis_large_module_timeout` | 600 | 大模块超时（秒） |
| `enable_audit` | False | 启用审计质检 |
| `enable_micro_scheduler` | False | 启用并发调度 |
| `enable_task_planning` | True | 启用任务预规划 |

## 大项目分析策略

当目标项目超过 1000 个文件或 10 万行代码时，自动切换为大项目分析模式：

1. **模块识别**：按顶层目录识别功能模块（如 src/tools、src/services），不按文件数机械切片
2. **小模块合并**：文件数少于 5 的模块合并为一组，减少碎片
3. **Prompt 约束注入**：每个子任务 prompt 自动注入文件读取上限（优先读 index.ts / 主文件 / types.ts，每个子目录只读 1-2 个核心文件）
4. **自适应超时**：根据模块文件数动态计算（小于 20 文件 5 分钟，20-50 文件 8 分钟，超过 50 文件 10 分钟）
5. **超时重试**：超时的子任务缩小范围重跑，不原样重试
6. **滚动派发**：前 N 个完成后立即派发下一批

### 子代理 Prompt 模板

```
分析 [模块名] 的实现。

目标目录：[path]
重点分析：[具体问题列表]

文件读取约束：
- 优先读 index.ts / 主文件 / types.ts 了解结构
- 每个子目录只读 1-2 个核心文件
- 总共最多读 [N] 个文件
- 时间不够优先输出已分析内容

输出要求：用中文写分析报告，重点发现标记。
```

## 注意事项

1. 派子代理时输出任务表格（序号、任务、Label、状态）
2. 审计结果内部消化，用户不可见
3. 子代理完成时立即通知用户进度
4. 执行过程中主会话保持可交互，不挂起
5. 分析类任务的子代理 prompt 必须包含文件读取约束
6. 超时的子任务缩小范围重跑，不原样重试
