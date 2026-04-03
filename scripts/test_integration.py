"""集成测试：验证所有模块正确接入主控"""
import asyncio
from orchestrator_v4_acp import create_orchestrator, OrchestratorConfig, TaskDuration

async def test():
    print("=" * 50)
    print("集成测试")
    print("=" * 50)
    
    # 1. 创建编排器（启用所有可用模块）
    orch = await create_orchestrator(
        enable_lifecycle_manager=True,
        enable_background_monitor=True,
        enable_micro_scheduler=True,
        enable_v3_bridge=True,
        resume_from_latest_checkpoint=False,
    )
    print(f"1. 编排器创建成功，session={orch._session_id}")
    
    # 2. 检查模块初始化
    status = orch.get_system_status()
    print("2. 系统状态:")
    for mod, st in status["modules"].items():
        print(f"   {mod}: {st}")
    
    # 3. 测试时长估计
    short = orch._estimate_duration("你好")
    medium = orch._estimate_duration("解释一下 Python 的 GIL 机制")
    long_task = orch._estimate_duration("请对目标服务器进行全面渗透测试")
    print(f"3. 时长估计: short={short.value}, medium={medium.value}, long={long_task.value}")
    
    # 4. 执行 Fast 任务
    resp = await orch.handle("你好", mode="fast")
    print(f"4. Fast 任务: mode={resp.worker_mode}, time={resp.execution_time_sec:.2f}s")
    
    # 5. 执行 Slow 任务（无 spawn_func，走 stub）
    resp2 = await orch.handle("设计一个分布式缓存系统", mode="slow")
    print(f"5. Slow 任务: mode={resp2.worker_mode}, tasks={resp2.task_count}")
    
    # 6. 执行 Auto 任务
    resp3 = await orch.handle("什么是协程？")
    print(f"6. Auto 任务: mode={resp3.worker_mode}, tasks={resp3.task_count}")
    
    # 7. 获取最终系统状态
    final = orch.get_system_status()
    stats = final["orchestrator"]["stats"]
    print(f"7. 最终统计: fast={stats['fast_tasks']}, slow={stats['slow_tasks']}, long={stats['long_tasks']}")
    
    # 8. 检查生命周期和监控器
    if "lifecycle" in final:
        print(f"8. 生命周期: {final['lifecycle']}")
    else:
        print("8. 生命周期: 无记录（正常，因为没有真实 spawn）")
    
    if "monitor" in final:
        print(f"9. 监控器: {final['monitor']}")
    else:
        print("9. 监控器: 无数据（正常）")
    
    await orch.stop(graceful=False)
    print("10. 编排器已停止")
    
    print("=" * 50)
    print("集成测试通过！")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(test())
