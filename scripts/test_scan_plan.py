"""测试真实文件扫描 + 任务预规划"""
import asyncio
from orchestrator_v4_acp import OrchestratorV4ACP, OrchestratorConfig

async def test():
    orch = OrchestratorV4ACP(OrchestratorConfig(resume_from_latest_checkpoint=False))
    
    print("=" * 60)
    print("文件扫描 + 任务预规划测试")
    print("=" * 60)
    
    # 1. 扫描 orchestrator-v4 的 scripts 目录
    scan = orch.scan_task_scope(
        "分析这个项目的代码",
        target_dir=r"C:\Users\eviost\.openclaw\workspace\skills\orchestrator-v4\scripts"
    )
    print(f"\n[扫描结果]")
    print(f"  文件数: {scan['total_files']}")
    print(f"  总行数: {scan['total_lines']}")
    print(f"  总大小: {scan['total_size_kb']}KB")
    print(f"  语言: {scan['languages']}")
    print(f"  建议子任务数: {scan['estimated_subtasks']}")
    print(f"  预计时间: {scan['estimated_time_sec']}s ({scan['estimated_time_sec']//60}min)")
    print(f"  说明: {scan['scan_note']}")
    for f in scan['files'][:5]:
        print(f"    {f['name']:35s} {f['lines']:5d}行  {f['size_kb']:6.1f}KB  {f['language']}")
    if len(scan['files']) > 5:
        print(f"    ... 还有 {len(scan['files'])-5} 个文件")
    
    # 2. 用扫描结果做任务规划
    plan = orch.plan_complex_task(
        "请阅读所有代码文件并写一份详细的技术报告",
        context={"target_dir": r"C:\Users\eviost\.openclaw\workspace\skills\orchestrator-v4\scripts"}
    )
    print(f"\n[规划结果]")
    print(f"  复杂度: {plan['complexity']}")
    print(f"  类型: {plan['request_type']}")
    print(f"  子任务数: {plan['total_subtasks']}")
    print(f"  策略: {plan['strategy']}")
    print(f"  预计时间: {plan['estimated_time_sec']}s")
    for t in plan['subtasks']:
        files_short = [f.split('\\')[-1] if '\\' in f else f.split('/')[-1] for f in t['files_to_read']]
        print(f"    {t['id']}: 读 {files_short}, mode={t['mode']}, deps={t['dependencies']}")
    
    # 3. 简单任务不触发扫描
    plan2 = orch.plan_complex_task("你好")
    print(f"\n[简单任务]")
    print(f"  复杂度: {plan2['complexity']}, 子任务: {plan2['total_subtasks']}, 策略: {plan2['strategy']}")
    
    print(f"\n{'=' * 60}")
    print("测试完成")

asyncio.run(test())
