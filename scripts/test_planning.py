"""测试任务预规划能力"""
import asyncio
from orchestrator_v4_acp import OrchestratorV4ACP, OrchestratorConfig

async def test():
    orch = OrchestratorV4ACP(OrchestratorConfig(resume_from_latest_checkpoint=False))
    
    print("=" * 60)
    print("任务预规划测试")
    print("=" * 60)
    
    # 1. 简单任务
    plan = orch.plan_complex_task("什么是 GIL？")
    print(f"\n[简单] '什么是 GIL？'")
    print(f"  复杂度={plan['complexity']}, 子任务={plan['total_subtasks']}, 策略={plan['strategy']}")
    
    # 2. 中等任务
    plan = orch.plan_complex_task("帮我写一个 REST API 用户管理模块")
    print(f"\n[代码] '写 REST API 用户管理模块'")
    print(f"  复杂度={plan['complexity']}, 类型={plan['request_type']}, 子任务={plan['total_subtasks']}, 策略={plan['strategy']}")
    for t in plan['subtasks']:
        print(f"    {t['id']}: {t['description'][:50]}... (deps={t['dependencies']})")
    
    # 3. 复杂任务（带文件引用）
    task = """请阅读以下文件并写技术报告：
    C:\\Users\\eviost\\scripts\\orchestrator_v4_acp.py
    C:\\Users\\eviost\\scripts\\lifecycle_manager.py
    C:\\Users\\eviost\\scripts\\background_monitor.py
    C:\\Users\\eviost\\scripts\\micro_scheduler.py
    C:\\Users\\eviost\\scripts\\v3_bridge.py
    C:\\Users\\eviost\\scripts\\v3_worker.py
    C:\\Users\\eviost\\scripts\\audit_agent.py
    要求极其详细的技术文档"""
    plan = orch.plan_complex_task(task)
    print(f"\n[复杂] '读 7 个文件写技术报告'")
    print(f"  复杂度={plan['complexity']}, 子任务={plan['total_subtasks']}, 策略={plan['strategy']}")
    print(f"  预计总时间={plan['estimated_time_sec']}s")
    for t in plan['subtasks']:
        files = [f.split('\\')[-1] for f in t['files_to_read']]
        print(f"    {t['id']}: 读 {files}, deps={t['dependencies']}")
    
    # 4. 研究任务
    plan = orch.plan_complex_task("调研目前主流的消息队列方案，对比 Kafka、RabbitMQ、Pulsar 的优劣势")
    print(f"\n[研究] '调研消息队列'")
    print(f"  复杂度={plan['complexity']}, 类型={plan['request_type']}, 子任务={plan['total_subtasks']}, 策略={plan['strategy']}")
    for t in plan['subtasks']:
        print(f"    {t['id']}: {t['description'][:50]}... (deps={t['dependencies']})")
    
    print(f"\n{'=' * 60}")
    print("测试完成")

asyncio.run(test())
