"""
scan_and_plan.py - Orchestrator V4 通用扫描规划脚本

供 OpenClaw 主会话通过 exec 调用，输出 plan JSON 供后续 sessions_spawn 使用。

用法:
  python scan_and_plan.py --task "任务描述" --target-dir "/path/to/project" --output plan.json
"""

import argparse
import json
import sys
from pathlib import Path

# 导入 orchestrator
sys.path.insert(0, str(Path(__file__).parent))
from orchestrator_v4_acp import OrchestratorV4ACP, OrchestratorConfig


def main():
    parser = argparse.ArgumentParser(description="Orchestrator V4 扫描规划")
    parser.add_argument("--task", required=True, help="任务描述")
    parser.add_argument("--target-dir", required=False, help="目标目录（可选）")
    parser.add_argument("--output", default="plan.json", help="输出文件路径（默认 plan.json）")
    parser.add_argument("--max-parallel", type=int, default=5, help="最大并发数（默认 5）")
    args = parser.parse_args()

    orch = OrchestratorV4ACP(OrchestratorConfig(resume_from_latest_checkpoint=False))

    # 扫描
    scan = None
    if args.target_dir:
        scan = orch.scan_task_scope(args.task, target_dir=args.target_dir)

    # 规划
    context = {"target_dir": args.target_dir} if args.target_dir else None
    plan = orch.plan_complex_task(args.task, context=context)

    # 输出摘要到 stdout
    print(f"total_subtasks: {plan['total_subtasks']}")
    print(f"strategy: {plan['strategy']}")
    print(f"is_large_project: {plan.get('is_large_project', False)}")
    print()
    for st in plan["subtasks"]:
        mk = st.get("module_key", "N/A")
        fc = str(st.get("module_file_count", "?"))
        timeout = st.get("estimated_time_sec", 300)
        cap = str(st.get("file_read_cap", "?"))
        print(f"  {st['id']:10s} | {mk:20s} | {fc:>4} files | {timeout:>4d}s | cap={cap}")

    # 写入 JSON
    output = {
        "task": args.task,
        "target_dir": args.target_dir,
        "max_parallel": args.max_parallel,
        "scan": scan,
        "plan": plan,
    }
    output_path = Path(args.output)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPlan saved to {output_path}")


if __name__ == "__main__":
    main()
