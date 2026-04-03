"""
orchestrator_v4_acp 端到端测试 - sessions_spawn 调用链路测试

测试范围：
1. spawn 成功场景
2. spawn 失败 + 重试场景  
3. spawn 全部失败场景
4. 并发控制测试
5. MicroScheduler + spawn 叠加测试
"""

import asyncio
import time
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from unittest.mock import AsyncMock, MagicMock

# 添加脚本目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 导入被测模块
from orchestrator_v4_acp import (
    OrchestratorV4ACP, 
    OrchestratorConfig, 
    WorkerMode,
    create_orchestrator
)


# ============ Mock 模块（向后兼容） ============

class MockRestartPolicy:
    NEVER = "never"
    ON_FAILURE = "on_failure"
    ALWAYS = "always"

class MockManagedProcess:
    def __init__(self, task_id: str, session_key: str):
        self.task_id = task_id
        self.session_key = session_key
        self.status = MagicMock()
        self.status.value = "running"
        self.restart_count = 0
        self.created_at = time.time()
        self.last_heartbeat = time.time()

class MockProcessLifecycleManager:
    """模拟生命周期管理器"""
    def __init__(self, default_restart_policy=None, default_max_restarts=3, default_restart_window_sec=60):
        self.default_restart_policy = default_restart_policy
        self.default_max_restarts = default_max_restarts
        self.default_restart_window_sec = default_restart_window_sec
        self._processes: Dict[str, MockManagedProcess] = {}
        self._restart_counts: Dict[str, int] = {}
    
    def register(self, task_id: str, session_key: str):
        self._processes[task_id] = MockManagedProcess(task_id, session_key)
    
    def mark_failed(self, task_id: str, error: str):
        if task_id in self._processes:
            self._processes[task_id].status.value = "failed"
    
    def mark_completed(self, task_id: str, success: bool = True):
        if task_id in self._processes:
            self._processes[task_id].status.value = "completed" if success else "failed"
    
    def should_restart(self, task_id: str) -> bool:
        count = self._restart_counts.get(task_id, 0)
        return count < self.default_max_restarts
    
    def record_restart(self, task_id: str):
        self._restart_counts[task_id] = self._restart_counts.get(task_id, 0) + 1
        if task_id in self._processes:
            self._processes[task_id].restart_count = self._restart_counts[task_id]
    
    def get_restart_delay(self, task_id: str) -> float:
        # 指数退避
        count = self._restart_counts.get(task_id, 0)
        return min(0.1 * (2 ** count), 1.0)  # 测试用短延迟
    
    def get_all(self) -> Dict[str, MockManagedProcess]:
        return self._processes.copy()


class MockAgentStatus:
    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"

class MockMonitoredAgent:
    def __init__(self, task_id: str, session_key: str, timeout: float):
        self.task_id = task_id
        self.session_key = session_key
        self.timeout = timeout
        self.status = MockAgentStatus.HEALTHY
        self.last_heartbeat = time.time()
        self.created_at = time.time()

class MockBackgroundMonitor:
    """模拟后台监控器"""
    def __init__(self, check_interval: float = 5.0):
        self.check_interval = check_interval
        self._monitored: Dict[str, MockMonitoredAgent] = {}
        self._running = False
    
    async def start(self):
        self._running = True
    
    async def stop(self):
        self._running = False
    
    def register(self, task_id: str, session_key: str, timeout: float):
        self._monitored[task_id] = MockMonitoredAgent(task_id, session_key, timeout)
    
    def heartbeat(self, task_id: str):
        if task_id in self._monitored:
            self._monitored[task_id].last_heartbeat = time.time()
    
    def mark_done(self, task_id: str, success: bool = True):
        if task_id in self._monitored:
            self._monitored[task_id].status = MockAgentStatus.HEALTHY if success else MockAgentStatus.ERROR


class MockTaskPriority:
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

class MockTaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class MockTaskResult:
    def __init__(self, task_id: str, content: str = "", success: bool = True, error: str = ""):
        self.task_id = task_id
        self.content = content
        self.success = success
        self.error = error

class MockMicroScheduler:
    """模拟微调度器"""
    def __init__(self, max_concurrent: int = 3, executor=None):
        self.max_concurrent = max_concurrent
        self.executor = executor
        self._tasks: Dict[str, Dict] = {}
        self._results: Dict[str, MockTaskResult] = {}
    
    def submit(self, task_id: str, content: str, priority: int = 2, dependencies: list = None):
        self._tasks[task_id] = {
            "id": task_id,
            "content": content,
            "priority": priority,
            "dependencies": dependencies or [],
            "status": MockTaskStatus.PENDING
        }
    
    async def run(self) -> Dict[str, MockTaskResult]:
        """按优先级和依赖执行所有任务"""
        executed = set()
        pending = set(self._tasks.keys())
        
        while pending:
            # 找到可以执行的任务（依赖已满足）
            ready = []
            for tid in pending:
                task = self._tasks[tid]
                deps_satisfied = all(d in executed for d in task["dependencies"] if d)
                if deps_satisfied:
                    ready.append(task)
            
            if not ready:
                break  # 死锁或完成
            
            # 按优先级排序
            ready.sort(key=lambda t: t["priority"], reverse=True)
            
            # 批量执行（受并发限制）
            batch = ready[:self.max_concurrent]
            batch_ids = [t["id"] for t in batch]
            
            # 执行批次
            for task in batch:
                task["status"] = MockTaskStatus.RUNNING
                try:
                    if self.executor:
                        # 创建 mock task 对象
                        mock_task = MagicMock()
                        mock_task.content = task["content"]
                        result = await self.executor(mock_task)
                        self._results[task["id"]] = MockTaskResult(
                            task_id=task["id"],
                            content=str(result),
                            success=True
                        )
                    else:
                        self._results[task["id"]] = MockTaskResult(
                            task_id=task["id"],
                            content="No executor",
                            success=False,
                            error="No executor"
                        )
                    task["status"] = MockTaskStatus.COMPLETED
                except Exception as e:
                    self._results[task["id"]] = MockTaskResult(
                        task_id=task["id"],
                        content="",
                        success=False,
                        error=str(e)
                    )
                    task["status"] = MockTaskStatus.FAILED
            
            # 更新状态
            for tid in batch_ids:
                pending.discard(tid)
                executed.add(tid)
        
        return self._results


# 注入 mock 模块
import orchestrator_v4_acp as orch_module
orch_module._HAS_LIFECYCLE = True
orch_module._HAS_MONITOR = True
orch_module._HAS_SCHEDULER = True
orch_module.ProcessLifecycleManager = MockProcessLifecycleManager
orch_module.RestartPolicy = MockRestartPolicy
orch_module.ManagedProcess = MockManagedProcess
orch_module.BackgroundMonitor = MockBackgroundMonitor
orch_module.ProcessStatus = MockAgentStatus
orch_module.MicroScheduler = MockMicroScheduler
orch_module.TaskPriority = MockTaskPriority
orch_module.TaskStatus = MockTaskStatus


# ============ 测试用例 ============

class TestResults:
    """测试结果收集器"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.details = []
    
    def add_pass(self, name: str, duration: float):
        self.passed += 1
        self.details.append(("PASS", name, duration))
        print(f"  ✓ PASS: {name} ({duration:.2f}s)")
    
    def add_fail(self, name: str, duration: float, error: str):
        self.failed += 1
        self.details.append(("FAIL", name, duration, error))
        print(f"  ✗ FAIL: {name} ({duration:.2f}s)")
        print(f"    Error: {error}")
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        print(f"测试总结: {self.passed}/{total} 通过")
        print(f"{'='*50}")
        return self.failed == 0


async def test_spawn_success():
    """测试1: spawn 成功场景"""
    print("\n[测试1] spawn 成功场景")
    
    # 记录 spawn 调用
    spawn_calls = []
    
    async def fake_spawn(**kwargs) -> Dict[str, Any]:
        """模拟成功的 spawn"""
        spawn_calls.append(kwargs)
        await asyncio.sleep(0.05)  # 模拟网络延迟
        return {
            "status": "accepted",
            "childSessionKey": "test-session-123"
        }
    
    # 创建编排器
    config = OrchestratorConfig(
        enable_lifecycle_manager=True,
        enable_background_monitor=True,
        max_parallel_subagents=3
    )
    orch = OrchestratorV4ACP(config, spawn_func=fake_spawn)
    await orch.start()
    
    try:
        # 执行 slow 任务
        response = await orch.handle("这是一个需要深入分析的复杂问题", mode=WorkerMode.SLOW)
        
        # 验证 spawn 被调用
        assert len(spawn_calls) == 1, f"期望 spawn 被调用 1 次，实际 {len(spawn_calls)} 次"
        
        # 验证参数正确
        call = spawn_calls[0]
        assert call["runtime"] == "subagent", "runtime 应为 subagent"
        assert call["agentId"] == config.subagent_agent_id, "agentId 不匹配"
        assert "task" in call, "task 字段缺失"
        assert "timeoutSeconds" in call, "timeoutSeconds 字段缺失"
        
        # 验证 lifecycle_manager 注册了进程
        assert orch._lifecycle is not None, "lifecycle_manager 未初始化"
        processes = orch._lifecycle.get_all()
        assert len(processes) >= 1, f"期望至少 1 个进程被注册，实际 {len(processes)}"
        
        # 验证 background_monitor 注册了监控
        assert orch._monitor is not None, "background_monitor 未初始化"
        assert len(orch._monitor._monitored) >= 1, f"期望至少 1 个监控项，实际 {len(orch._monitor._monitored)}"
        
        # 验证响应包含 sessionKey
        assert "test-session-123" in response.content or "spawned" in response.content, \
            f"响应内容不包含期望信息: {response.content}"
        
        return True, "所有断言通过"
        
    except Exception as e:
        return False, str(e)
    finally:
        await orch.stop()


async def test_spawn_retry():
    """测试2: spawn 失败 + 重试场景"""
    print("\n[测试2] spawn 失败 + 重试场景")
    
    call_count = 0
    
    async def fail_then_succeed_spawn(**kwargs) -> Dict[str, Any]:
        """前 2 次失败，第 3 次成功"""
        nonlocal call_count
        call_count += 1
        
        if call_count <= 2:
            raise Exception(f"模拟第 {call_count} 次失败")
        
        return {
            "status": "accepted",
            "childSessionKey": f"retry-session-{call_count}"
        }
    
    # 创建编排器，启用重试
    config = OrchestratorConfig(
        enable_lifecycle_manager=True,
        max_restarts=3,
        restart_policy="on_failure"
    )
    orch = OrchestratorV4ACP(config, spawn_func=fail_then_succeed_spawn)
    await orch.start()
    
    try:
        # 执行 slow 任务
        response = await orch.handle("这是一个需要重试的任务", mode=WorkerMode.SLOW)
        
        # 验证重试了 2 次后成功（总共调用 3 次）
        assert call_count == 3, f"期望调用 3 次（2次失败+1次成功），实际 {call_count} 次"
        
        # 验证 lifecycle_manager 记录了重试
        assert orch._lifecycle is not None, "lifecycle_manager 未初始化"
        processes = orch._lifecycle.get_all()
        
        # 找到对应的进程，验证重试次数
        found_retry = False
        for task_id, proc in processes.items():
            if proc.restart_count > 0:
                found_retry = True
                break
        
        # 验证响应成功
        assert "retry-session-3" in response.content or "spawned" in response.content, \
            f"响应内容不包含成功信息: {response.content}"
        
        return True, f"重试 {call_count-1} 次后成功"
        
    except Exception as e:
        return False, str(e)
    finally:
        await orch.stop()


async def test_spawn_all_fail():
    """测试3: spawn 全部失败场景"""
    print("\n[测试3] spawn 全部失败场景")
    
    call_count = 0
    
    async def always_fail_spawn(**kwargs) -> Dict[str, Any]:
        """永远失败"""
        nonlocal call_count
        call_count += 1
        raise Exception(f"模拟第 {call_count} 次失败（永远失败）")
    
    # 创建编排器，限制重试次数
    max_restarts = 2
    config = OrchestratorConfig(
        enable_lifecycle_manager=True,
        max_restarts=max_restarts,
        restart_policy="on_failure"
    )
    orch = OrchestratorV4ACP(config, spawn_func=always_fail_spawn)
    await orch.start()
    
    try:
        # 执行 slow 任务
        response = await orch.handle("这是一个注定失败的任务", mode=WorkerMode.SLOW)
        
        # 验证调用次数 = 初始 + 重试次数
        expected_calls = max_restarts + 1
        assert call_count == expected_calls, f"期望调用 {expected_calls} 次，实际 {call_count} 次"
        
        # 验证返回错误信息而不是崩溃
        assert "失败" in response.content or "error" in response.content.lower() or "Spawn" in response.content, \
            f"响应应包含错误信息，实际: {response.content}"
        
        return True, f"达到 max_restarts ({max_restarts}) 后返回错误"
        
    except Exception as e:
        return False, f"编排器崩溃: {str(e)}"
    finally:
        await orch.stop()


async def test_concurrency_control():
    """测试4: 并发控制测试"""
    print("\n[测试4] 并发控制测试")
    
    max_parallel = 2
    running_count = 0
    max_running = 0
    lock = asyncio.Lock()
    
    async def slow_spawn(**kwargs) -> Dict[str, Any]:
        """模拟耗时的 spawn"""
        nonlocal running_count, max_running
        
        async with lock:
            running_count += 1
            max_running = max(max_running, running_count)
        
        await asyncio.sleep(0.5)  # 模拟耗时
        
        async with lock:
            running_count -= 1
        
        return {
            "status": "accepted",
            "childSessionKey": f"session-{id(asyncio.current_task())}"
        }
    
    # 创建编排器，限制并发
    config = OrchestratorConfig(
        enable_lifecycle_manager=True,
        max_parallel_subagents=max_parallel
    )
    orch = OrchestratorV4ACP(config, spawn_func=slow_spawn)
    await orch.start()
    
    try:
        # 同时提交 4 个 slow 任务
        tasks = [
            orch.handle(f"并发任务 {i}", mode=WorkerMode.SLOW)
            for i in range(4)
        ]
        
        # 等待所有任务完成
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 验证同时运行的不超过 max_parallel
        assert max_running <= max_parallel, \
            f"期望同时运行不超过 {max_parallel}，实际最大 {max_running}"
        
        # 验证所有任务都完成了
        success_count = sum(1 for r in responses if not isinstance(r, Exception))
        assert success_count == 4, f"期望 4 个任务成功，实际 {success_count}"
        
        return True, f"最大并发 {max_running}/{max_parallel}"
        
    except Exception as e:
        return False, str(e)
    finally:
        await orch.stop()


async def test_micro_scheduler_with_spawn():
    """测试5: MicroScheduler + spawn 叠加测试"""
    print("\n[测试5] MicroScheduler + spawn 叠加测试")
    
    spawn_calls = []
    
    async def fake_spawn(**kwargs) -> Dict[str, Any]:
        """模拟 spawn"""
        spawn_calls.append(kwargs)
        await asyncio.sleep(0.05)
        return {
            "status": "accepted",
            "childSessionKey": f"scheduler-session-{len(spawn_calls)}"
        }
    
    # 创建编排器，启用微调度器
    config = OrchestratorConfig(
        enable_lifecycle_manager=True,
        enable_background_monitor=True,
        enable_micro_scheduler=True,
        scheduler_max_concurrent=2
    )
    orch = OrchestratorV4ACP(config, spawn_func=fake_spawn)
    await orch.start()
    
    try:
        # 提交 code 类型任务（会分解为多步）
        response = await orch.handle(
            "分析需求并编写代码实现一个排序算法",
            request_type="code",
            mode=WorkerMode.SLOW
        )
        
        # 验证调度器和 spawn 都工作了
        # code 类型任务应该分解为多个步骤
        assert len(spawn_calls) >= 1, f"期望至少 1 次 spawn 调用，实际 {len(spawn_calls)}"
        
        # 验证响应非空
        assert response.content, "响应内容为空"
        assert response.task_count >= 1, f"期望至少 1 个任务，实际 {response.task_count}"
        
        # 验证执行时间被记录
        assert response.execution_time_sec > 0, "执行时间应大于 0"
        
        return True, f"调度器执行了 {response.task_count} 个任务，spawn 调用 {len(spawn_calls)} 次"
        
    except Exception as e:
        return False, str(e)
    finally:
        await orch.stop()


async def run_all_tests():
    """运行所有测试"""
    print("="*50)
    print("OrchestratorV4ACP sessions_spawn 端到端测试")
    print("="*50)
    
    results = TestResults()
    
    # 测试列表
    tests = [
        ("spawn 成功场景", test_spawn_success),
        ("spawn 失败 + 重试场景", test_spawn_retry),
        ("spawn 全部失败场景", test_spawn_all_fail),
        ("并发控制测试", test_concurrency_control),
        ("MicroScheduler + spawn 叠加测试", test_micro_scheduler_with_spawn),
    ]
    
    for name, test_func in tests:
        start = time.time()
        try:
            success, msg = await test_func()
            duration = time.time() - start
            if success:
                results.add_pass(name, duration)
            else:
                results.add_fail(name, duration, msg)
        except Exception as e:
            duration = time.time() - start
            results.add_fail(name, duration, str(e))
    
    # 打印总结
    return results.summary()


if __name__ == "__main__":
    # 运行测试
    success = asyncio.run(run_all_tests())
    
    # 退出码
    sys.exit(0 if success else 1)
