"""
test_v3_e2e.py - V3 Bridge 端到端通信测试

测试内容：
1. V3Bridge 启动 v3_worker.py 作为子进程
2. 测试 PING/PONG 心跳通信
3. 测试发送 TASK 消息，接收 PROGRESS 和 RESULT
4. 测试 LongTaskExecutor.execute() 端到端（发任务，收进度更新，收最终结果）
5. 测试优雅关闭（发 CONTROL:shutdown）
6. 测试心跳超时检测
"""

import asyncio
import os
import sys
import time

# 添加当前目录到路径，确保能导入 v3_bridge
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from v3_bridge import V3Bridge, LongTaskExecutor, BridgeMessage, MessageType, BridgeState


# 获取 v3_worker.py 的绝对路径
V3_WORKER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v3_worker.py")


class TestResult:
    """测试结果统计"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def add(self, name: str, passed: bool, msg: str = ""):
        self.tests.append((name, passed, msg))
        if passed:
            self.passed += 1
        else:
            self.failed += 1

    def summary(self):
        total = self.passed + self.failed
        print("\n" + "=" * 60)
        print("测试结果汇总")
        print("=" * 60)
        for name, passed, msg in self.tests:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {status} - {name}")
            if msg:
                print(f"       {msg}")
        print("-" * 60)
        print(f"总计: {total} 项 | 通过: {self.passed} | 失败: {self.failed}")
        print("=" * 60)
        return self.failed == 0


async def test_1_bridge_start_worker():
    """测试1: V3Bridge 启动 v3_worker.py 作为子进程"""
    print("\n[测试1] V3Bridge 启动 v3_worker.py 作为子进程")
    
    bridge = V3Bridge(heartbeat_interval=2.0, heartbeat_timeout=5.0)
    command = [sys.executable, V3_WORKER_PATH]
    
    try:
        ok = await bridge.connect(command)
        if not ok:
            return False, "连接失败"
        
        # 等待一小段时间确保进程启动
        await asyncio.sleep(0.5)
        
        # 检查进程是否存活
        if not bridge.is_alive():
            await bridge.disconnect(graceful=False)
            return False, "子进程未存活"
        
        if bridge.get_state() != BridgeState.CONNECTED:
            await bridge.disconnect(graceful=False)
            return False, f"状态不正确: {bridge.get_state().name}"
        
        await bridge.disconnect(graceful=True)
        return True, f"子进程 PID={bridge._process.pid if bridge._process else 'N/A'}"
    except Exception as e:
        await bridge.disconnect(graceful=False)
        return False, f"异常: {e}"


async def test_2_ping_pong():
    """测试2: PING/PONG 心跳通信"""
    print("\n[测试2] PING/PONG 心跳通信")
    
    bridge = V3Bridge(heartbeat_interval=1.0, heartbeat_timeout=3.0)
    command = [sys.executable, V3_WORKER_PATH]
    
    try:
        ok = await bridge.connect(command)
        if not ok:
            return False, "连接失败"
        
        # 等待心跳循环发送 PING 并收到 PONG
        await asyncio.sleep(2.5)
        
        # 检查是否收到过 PONG（通过检查 last_pong_time）
        if bridge._last_pong_time == 0:
            await bridge.disconnect(graceful=False)
            return False, "未收到 PONG"
        
        # 手动发送 PING 测试
        ping_msg = BridgeMessage(
            msg_type=MessageType.PING,
            payload={"test": True}
        )
        sent = await bridge.send(ping_msg)
        if not sent:
            await bridge.disconnect(graceful=False)
            return False, "发送 PING 失败"
        
        # 等待 PONG
        await asyncio.sleep(0.5)
        
        # 验证状态仍然正常
        if bridge.get_state() != BridgeState.CONNECTED:
            await bridge.disconnect(graceful=False)
            return False, f"心跳后状态异常: {bridge.get_state().name}"
        
        await bridge.disconnect(graceful=True)
        return True, "心跳通信正常"
    except Exception as e:
        await bridge.disconnect(graceful=False)
        return False, f"异常: {e}"


async def test_3_task_progress_result():
    """测试3: 发送 TASK 消息，接收 PROGRESS 和 RESULT"""
    print("\n[测试3] 发送 TASK 消息，接收 PROGRESS 和 RESULT")
    
    bridge = V3Bridge(heartbeat_interval=2.0, heartbeat_timeout=5.0)
    command = [sys.executable, V3_WORKER_PATH]
    
    try:
        ok = await bridge.connect(command)
        if not ok:
            return False, "连接失败"
        
        # 发送 TASK 消息
        task_msg = BridgeMessage(
            msg_type=MessageType.TASK,
            payload={
                "task_id": "test_task_001",
                "content": "测试任务内容",
                "total_steps": 3  # 减少步骤加快测试
            }
        )
        sent = await bridge.send(task_msg)
        if not sent:
            await bridge.disconnect(graceful=False)
            return False, "发送 TASK 失败"
        
        # 接收消息
        progress_count = 0
        result_received = False
        
        for _ in range(10):  # 最多接收10条消息
            msg = await bridge.recv(timeout=5.0)
            if msg is None:
                break
            
            if msg.msg_type == MessageType.PROGRESS:
                progress_count += 1
                print(f"    收到 PROGRESS: {msg.payload.get('progress')}%, {msg.payload.get('detail')}")
            elif msg.msg_type == MessageType.RESULT:
                result_received = True
                print(f"    收到 RESULT: {msg.payload.get('result', 'N/A')[:50]}...")
                break
            elif msg.msg_type == MessageType.ERROR:
                await bridge.disconnect(graceful=False)
                return False, f"收到错误: {msg.payload.get('error')}"
        
        await bridge.disconnect(graceful=True)
        
        if progress_count == 0:
            return False, "未收到 PROGRESS 消息"
        if not result_received:
            return False, "未收到 RESULT 消息"
        
        return True, f"收到 {progress_count} 个进度更新和最终结果"
    except Exception as e:
        await bridge.disconnect(graceful=False)
        return False, f"异常: {e}"


async def test_4_long_task_executor():
    """测试4: LongTaskExecutor.execute() 端到端"""
    print("\n[测试4] LongTaskExecutor.execute() 端到端")
    
    bridge = V3Bridge(heartbeat_interval=2.0, heartbeat_timeout=5.0)
    command = [sys.executable, V3_WORKER_PATH]
    
    try:
        ok = await bridge.connect(command)
        if not ok:
            return False, "连接失败"
        
        executor = LongTaskExecutor(bridge)
        
        updates = []
        async for update in executor.execute("测试长任务执行"):
            updates.append(update)
            status = update.get("status")
            if status == "progress":
                print(f"    进度: {update.get('progress')}%, {update.get('detail', '')}")
            elif status == "completed":
                print(f"    完成: {update.get('result', 'N/A')[:50]}...")
            elif status == "error":
                print(f"    错误: {update.get('error')}")
        
        await bridge.disconnect(graceful=True)
        
        # 验证更新序列
        if len(updates) < 2:
            return False, f"更新数量不足: {len(updates)}"
        
        if updates[0].get("status") != "started":
            return False, "第一个更新不是 started"
        
        if updates[-1].get("status") != "completed":
            return False, "最后一个更新不是 completed"
        
        # 检查进度递增
        progress_values = [u.get("progress") for u in updates if u.get("status") == "progress"]
        if len(progress_values) < 3:
            return False, f"进度更新数量不足: {len(progress_values)}"
        
        return True, f"收到 {len(updates)} 个更新，进度从 {progress_values[0]}% 到 {progress_values[-1]}%"
    except Exception as e:
        await bridge.disconnect(graceful=False)
        return False, f"异常: {e}"


async def test_5_graceful_shutdown():
    """测试5: 优雅关闭（发 CONTROL:shutdown）"""
    print("\n[测试5] 优雅关闭（发 CONTROL:shutdown）")
    
    bridge = V3Bridge(heartbeat_interval=2.0, heartbeat_timeout=5.0)
    command = [sys.executable, V3_WORKER_PATH]
    
    try:
        ok = await bridge.connect(command)
        if not ok:
            return False, "连接失败"
        
        # 记录子进程 PID
        pid = bridge._process.pid if bridge._process else None
        
        # 发送优雅关闭指令
        await bridge.disconnect(graceful=True)
        
        # 检查进程是否已退出
        if bridge._process is not None:
            return False, "进程引用未清空"
        
        if bridge.get_state() != BridgeState.DISCONNECTED:
            return False, f"状态不正确: {bridge.get_state().name}"
        
        return True, f"子进程 PID={pid} 已优雅退出"
    except Exception as e:
        await bridge.disconnect(graceful=False)
        return False, f"异常: {e}"


async def test_6_heartbeat_timeout():
    """测试6: 心跳超时检测"""
    print("\n[测试6] 心跳超时检测")
    
    # 创建一个不响应 PONG 的脚本
    dead_script = '''
import sys
while True:
    line = sys.stdin.readline()
    if not line:
        break
'''
    
    bridge = V3Bridge(heartbeat_interval=1.0, heartbeat_timeout=2.0)
    command = [sys.executable, "-c", dead_script]
    
    try:
        ok = await bridge.connect(command)
        if not ok:
            return False, "连接失败"
        
        # 等待心跳超时
        print("    等待心跳超时...")
        await asyncio.sleep(4)
        
        # 检查状态是否变为 ERROR
        if bridge.get_state() != BridgeState.ERROR:
            await bridge.disconnect(graceful=False)
            return False, f"状态未变为 ERROR: {bridge.get_state().name}"
        
        await bridge.disconnect(graceful=False)
        return True, "心跳超时检测正常"
    except Exception as e:
        await bridge.disconnect(graceful=False)
        return False, f"异常: {e}"


async def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("V3 Bridge 端到端通信测试")
    print("=" * 60)
    print(f"Python: {sys.executable}")
    print(f"Worker 路径: {V3_WORKER_PATH}")
    print(f"Worker 存在: {os.path.exists(V3_WORKER_PATH)}")
    
    result = TestResult()
    
    # 测试1: Bridge 启动 Worker
    try:
        passed, msg = await test_1_bridge_start_worker()
        result.add("Bridge 启动 Worker", passed, msg)
        print(f"  结果: {'PASS' if passed else 'FAIL'} - {msg}")
    except Exception as e:
        result.add("Bridge 启动 Worker", False, f"异常: {e}")
        print(f"  结果: FAIL - 异常: {e}")
    
    # 测试2: PING/PONG 心跳
    try:
        passed, msg = await test_2_ping_pong()
        result.add("PING/PONG 心跳通信", passed, msg)
        print(f"  结果: {'PASS' if passed else 'FAIL'} - {msg}")
    except Exception as e:
        result.add("PING/PONG 心跳通信", False, f"异常: {e}")
        print(f"  结果: FAIL - 异常: {e}")
    
    # 测试3: TASK/PROGRESS/RESULT
    try:
        passed, msg = await test_3_task_progress_result()
        result.add("TASK/PROGRESS/RESULT 消息", passed, msg)
        print(f"  结果: {'PASS' if passed else 'FAIL'} - {msg}")
    except Exception as e:
        result.add("TASK/PROGRESS/RESULT 消息", False, f"异常: {e}")
        print(f"  结果: FAIL - 异常: {e}")
    
    # 测试4: LongTaskExecutor
    try:
        passed, msg = await test_4_long_task_executor()
        result.add("LongTaskExecutor 端到端", passed, msg)
        print(f"  结果: {'PASS' if passed else 'FAIL'} - {msg}")
    except Exception as e:
        result.add("LongTaskExecutor 端到端", False, f"异常: {e}")
        print(f"  结果: FAIL - 异常: {e}")
    
    # 测试5: 优雅关闭
    try:
        passed, msg = await test_5_graceful_shutdown()
        result.add("优雅关闭", passed, msg)
        print(f"  结果: {'PASS' if passed else 'FAIL'} - {msg}")
    except Exception as e:
        result.add("优雅关闭", False, f"异常: {e}")
        print(f"  结果: FAIL - 异常: {e}")
    
    # 测试6: 心跳超时检测
    try:
        passed, msg = await test_6_heartbeat_timeout()
        result.add("心跳超时检测", passed, msg)
        print(f"  结果: {'PASS' if passed else 'FAIL'} - {msg}")
    except Exception as e:
        result.add("心跳超时检测", False, f"异常: {e}")
        print(f"  结果: FAIL - 异常: {e}")
    
    # 打印总结
    all_passed = result.summary()
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
