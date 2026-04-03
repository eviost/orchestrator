"""测试新的复杂度评估和自动类型检测"""
import asyncio
from orchestrator_v4_acp import OrchestratorV4ACP, OrchestratorConfig

async def test():
    orch = OrchestratorV4ACP(OrchestratorConfig(resume_from_latest_checkpoint=False))
    
    print("=" * 60)
    print("复杂度评估测试（加权打分，取最高分）")
    print("=" * 60)
    
    cases = [
        ("你好", "应为1"),
        ("简单解释一下GIL", "应为2（简单1 vs 解释2 → 取2）"),
        ("简单设计一个系统", "应为4（简单1 vs 设计4 → 取4）"),
        ("分析一下这个方案", "应为3"),
        ("设计一个完整的分布式缓存架构", "应为5（设计4 vs 完整5 → 取5）"),
        ("hi", "应为1"),
        ("implement a REST API", "应为4"),
        ("comprehensive end-to-end testing", "应为5"),
        ("x" * 50, "应为2（无关键词，50字）"),
        ("x" * 250, "应为3（无关键词，250字，长文本加分）"),
        ("x" * 600, "应为4（无关键词，600字，长文本加分）"),
    ]
    
    for text, expected in cases:
        score = orch._assess_complexity(text)
        display = text[:30] + "..." if len(text) > 30 else text
        print(f"  [{score}] {display:35s} ({expected})")
    
    print()
    print("=" * 60)
    print("自动类型检测测试")
    print("=" * 60)
    
    type_cases = [
        ("帮我写一个爬虫脚本", "code"),
        ("这个bug怎么修", "debug"),
        ("调研一下目前主流的消息队列", "research"),
        ("今天天气怎么样", "general"),
        ("implement a REST API", "code"),
        ("fix this error", "debug"),
        ("compare Redis vs Memcached", "research"),
        ("创建一个用户管理模块", "code"),
        ("为什么不工作了", "debug"),
        ("有哪些好用的框架", "research"),
    ]
    
    for text, expected in type_cases:
        detected = orch._auto_detect_request_type(text)
        status = "✓" if detected == expected else "✗"
        print(f"  {status} [{detected:8s}] {text:35s} (期望: {expected})")
    
    print()
    print("=" * 60)
    print("测试完成")
    print("=" * 60)

asyncio.run(test())
