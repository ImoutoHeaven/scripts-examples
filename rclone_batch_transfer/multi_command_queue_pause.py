#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time
import threading
import queue
import os
import signal
import platform
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import datetime

# 命令状态常量 - 更新为要求的状态名称
class CommandStatus:
    INQUEUE = "INQUEUE"   # 改为 INQUEUE (原 PENDING)
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"   # 改为 COMPLETED (原 SUCCEEDED)
    FAILED = "FAILED"

# 全局状态
input_queue = queue.Queue()
command_lock = threading.Lock()  # 用于命令状态的线程安全操作
stop_event = threading.Event()   # 信号所有线程停止

# 保存命令状态的字典
# 格式: {command_id: {"command": cmd_str, "status": CommandStatus, "process": subprocess_obj, 
#                    "retry_count": int, "start_time": datetime, "end_time": datetime}}
command_states = {}

def parse_args():
    parser = argparse.ArgumentParser(description='并发执行命令并支持重试。')
    parser.add_argument('--total-retries', type=int, default=3, help='失败命令的重试次数。0表示不重试。')
    parser.add_argument('--max-concurrent', type=int, default=5, help='最大并发命令数。')
    parser.add_argument('--status-interval', type=int, default=10, help='状态更新打印间隔（秒）。')
    return parser.parse_args()

def get_commands():
    print("输入命令（每行一条）。连续按两次回车结束输入:")
    commands = []
    while True:
        try:
            cmd = input().strip()
            if not cmd:  # 空行，结束循环
                break
            commands.append(cmd)
        except KeyboardInterrupt:
            print("\n输入被中断。停止命令收集。")
            break
        except EOFError:
            print("\n到达输入末尾。")
            break
    return commands

def format_command_list(commands):
    """格式化命令列表显示"""
    formatted = "\n--- 命令列表 ---\n"
    for i, cmd in enumerate(commands):
        formatted += f"{i+1}. {cmd}\n"
    formatted += "-------------------\n"
    return formatted

def format_command_status():
    """格式化命令状态显示 - 修改为显示所有命令，包括已完成的"""
    with command_lock:
        if not command_states:
            return "\n--- 没有正在运行的命令 ---\n"
        
        now = datetime.datetime.now()
        formatted = "\n--- 命令状态 ---\n"
        
        # 按照状态对命令进行分组显示
        status_groups = {
            CommandStatus.RUNNING: [],
            CommandStatus.INQUEUE: [],
            CommandStatus.PAUSED: [],
            CommandStatus.COMPLETED: [],
            CommandStatus.FAILED: []
        }
        
        # 分组所有命令
        for cmd_id, state in sorted(command_states.items()):
            status_groups[state["status"]].append((cmd_id, state))
        
        # 输出每组命令
        for status, group in status_groups.items():
            if group:  # 只有在组内有命令时才显示组标题
                formatted += f"\n--- {status} 命令 ({len(group)}) ---\n"
                for cmd_id, state in group:
                    command = state["command"]
                    
                    # 计算持续时间
                    duration = ""
                    if state["start_time"]:
                        end_time = state["end_time"] if state["end_time"] else now
                        duration_sec = (end_time - state["start_time"]).total_seconds()
                        minutes, seconds = divmod(int(duration_sec), 60)
                        hours, minutes = divmod(minutes, 60)
                        duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    
                    retry_info = f" (重试: {state['retry_count']})" if state["retry_count"] > 0 else ""
                    formatted += f"ID {cmd_id+1}: [{duration}]{retry_info} {command}\n"
        
        formatted += "\n---------------------\n"
        return formatted

def input_listener():
    """监听用户命令的线程函数"""
    while not stop_event.is_set():
        try:
            user_input = input().strip().lower()
            input_queue.put(user_input)
            
            if user_input == "exit":
                print("\n[停止所有命令并退出...]")
                stop_event.set()
                # 终止所有运行中的进程
                terminate_all_processes()
                break
            elif user_input == "status":
                print(format_command_status())
            elif user_input.startswith("pause") or user_input.startswith("resume"):
                parts = user_input.split()
                cmd = parts[0]
                
                # 处理特定命令或所有命令的暂停/恢复
                if len(parts) > 1 and parts[1].isdigit():
                    cmd_id = int(parts[1]) - 1  # 转换为0开始的索引
                    if cmd == "pause":
                        pause_command(cmd_id)
                    elif cmd == "resume":
                        resume_command(cmd_id)
                else:
                    if cmd == "pause":
                        pause_all_commands()
                    elif cmd == "resume":
                        resume_all_commands()
        except EOFError:
            break
        except Exception as e:
            print(f"输入监听器错误: {e}")

def pause_command(cmd_id):
    """暂停特定命令"""
    with command_lock:
        if cmd_id in command_states and command_states[cmd_id]["status"] == CommandStatus.RUNNING:
            command_states[cmd_id]["status"] = CommandStatus.PAUSED
            if command_states[cmd_id]["process"]:
                terminate_process(command_states[cmd_id]["process"])
            print(f"\n[命令 {cmd_id+1} 已暂停]")
        else:
            print(f"\n[命令 {cmd_id+1} 未在运行或不存在]")

def resume_command(cmd_id):
    """恢复特定命令"""
    with command_lock:
        if cmd_id in command_states and command_states[cmd_id]["status"] == CommandStatus.PAUSED:
            command_states[cmd_id]["status"] = CommandStatus.INQUEUE  # 将被重新执行 (原PENDING)
            print(f"\n[命令 {cmd_id+1} 已排队等待重启]")
        else:
            print(f"\n[命令 {cmd_id+1} 未被暂停或不存在]")

def pause_all_commands():
    """暂停所有运行中的命令"""
    with command_lock:
        paused_count = 0
        for cmd_id, state in command_states.items():
            if state["status"] == CommandStatus.RUNNING:
                state["status"] = CommandStatus.PAUSED
                if state["process"]:
                    terminate_process(state["process"])
                paused_count += 1
        print(f"\n[已暂停 {paused_count} 个运行中的命令]")

def resume_all_commands():
    """恢复所有已暂停的命令"""
    with command_lock:
        resumed_count = 0
        for cmd_id, state in command_states.items():
            if state["status"] == CommandStatus.PAUSED:
                state["status"] = CommandStatus.INQUEUE  # 将被重新执行 (原PENDING)
                resumed_count += 1
        print(f"\n[已恢复 {resumed_count} 个已暂停的命令]")

def terminate_process(process):
    """终止进程及其所有子进程"""
    if process is None:
        return
    
    process_id = process.pid
    
    try:
        # 在类Unix系统上杀死整个进程组
        if platform.system() != "Windows":
            # 向进程组发送SIGTERM信号
            pgid = os.getpgid(process_id)
            os.killpg(pgid, signal.SIGTERM)
            time.sleep(0.5)
            
            # 如果进程仍然存在，强制杀死
            try:
                os.killpg(pgid, 0)  # 检查进程是否存在
                os.killpg(pgid, signal.SIGKILL)  # 如果存在，强制杀死
            except OSError:
                pass  # 进程组已终止
        else:
            # 在Windows上，我们只能终止主进程
            # 使用taskkill尝试杀死子进程
            process.terminate()
            time.sleep(0.5)
            if process.poll() is None:
                process.kill()
                # 额外尝试在Windows上杀死子进程
                subprocess.call(f'taskkill /F /T /PID {process_id}', 
                                shell=True, 
                                stdout=subprocess.DEVNULL, 
                                stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"终止进程时出错: {e}")

def terminate_all_processes():
    """终止所有运行中的进程"""
    with command_lock:
        for cmd_id, state in command_states.items():
            if state["status"] == CommandStatus.RUNNING and state["process"]:
                terminate_process(state["process"])

def status_updater(interval):
    """定期打印状态更新的线程"""
    while not stop_event.is_set():
        time.sleep(interval)
        if not stop_event.is_set():  # 睡眠后再次检查
            print(format_command_status())

def execute_command(cmd_id, cmd, total_retries):
    """执行命令，支持重试和暂停/恢复"""
    with command_lock:
        # 初始化或更新命令状态
        if cmd_id not in command_states:
            command_states[cmd_id] = {
                "command": cmd,
                "status": CommandStatus.INQUEUE,  # 更新为INQUEUE (原PENDING)
                "process": None,
                "retry_count": 0,
                "start_time": None,
                "end_time": None
            }
        else:
            # 为重试重置状态
            command_states[cmd_id]["status"] = CommandStatus.INQUEUE  # 更新为INQUEUE (原PENDING)
            command_states[cmd_id]["process"] = None
    
    retry_count = 0
    cmd_prefix = f"[CMD-{cmd_id+1}] "
    
    while retry_count <= total_retries and not stop_event.is_set():
        # 检查命令是否已暂停
        with command_lock:
            if command_states[cmd_id]["status"] == CommandStatus.PAUSED:
                # 命令已暂停，等待恢复
                time.sleep(0.5)
                continue

        # 检查是否需要重试
        if retry_count > 0:
            print(f"{cmd_prefix}重试中 (尝试 {retry_count}/{total_retries})...")
            
            with command_lock:
                command_states[cmd_id]["retry_count"] = retry_count
        
        # 更新命令状态为运行中
        with command_lock:
            command_states[cmd_id]["status"] = CommandStatus.RUNNING
            if command_states[cmd_id]["start_time"] is None:
                command_states[cmd_id]["start_time"] = datetime.datetime.now()
        
        print(f"{cmd_prefix}开始执行: {cmd}")
        
        try:
            # 根据平台配置进程创建
            popen_kwargs = {
                'shell': True,
                'stdout': subprocess.PIPE,
                'stderr': subprocess.STDOUT,
                'bufsize': 1,  # 行缓冲
            }
            
            # 在类Unix系统上创建新的进程组
            if platform.system() != "Windows":
                popen_kwargs['preexec_fn'] = os.setsid
            
            # 使用subprocess.Popen实时捕获输出
            process = subprocess.Popen(cmd, **popen_kwargs)
            
            # 在命令状态中存储进程
            with command_lock:
                command_states[cmd_id]["process"] = process
            
            # 实时处理输出
            while not stop_event.is_set():
                # 检查命令是否被暂停
                with command_lock:
                    if command_states[cmd_id]["status"] == CommandStatus.PAUSED:
                        print(f"{cmd_prefix}命令已暂停，将在恢复后重新启动。")
                        break
                
                # 尝试读取一行（非阻塞）
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    # 进程已退出且没有更多输出
                    break
                
                if line:
                    try:
                        decoded_line = line.decode('utf-8', errors='replace')
                        # 为每行添加命令ID前缀
                        print(f"{cmd_prefix}{decoded_line}", end='')
                        sys.stdout.flush()  # 确保输出立即显示
                    except Exception as e:
                        print(f"{cmd_prefix}解码输出错误: {e}", file=sys.stderr)
                else:
                    # 没有输出但进程仍在运行，给一个小的暂停
                    time.sleep(0.1)
            
            # 如果由于暂停而中断，继续下一次迭代
            with command_lock:
                if command_states[cmd_id]["status"] == CommandStatus.PAUSED:
                    continue
            
            # 如果我们正在停止所有内容，中断
            if stop_event.is_set():
                break
                
            # 关闭stdout以避免资源泄漏
            if process and process.stdout:
                process.stdout.close()
            
            # 获取返回代码
            return_code = process.poll()
            
            with command_lock:
                command_states[cmd_id]["process"] = None  # 清除进程引用
                
                if return_code == 0:
                    print(f"{cmd_prefix}执行成功，退出代码: 0")
                    command_states[cmd_id]["status"] = CommandStatus.COMPLETED  # 更新为COMPLETED (原SUCCEEDED)
                    command_states[cmd_id]["end_time"] = datetime.datetime.now()
                    return True
                else:
                    print(f"{cmd_prefix}执行失败，退出代码: {return_code}")
                    retry_count += 1
                    
                    if retry_count > total_retries:
                        command_states[cmd_id]["status"] = CommandStatus.FAILED
                        command_states[cmd_id]["end_time"] = datetime.datetime.now()
                    # else: 下一次迭代时将回到INQUEUE/RUNNING状态
        except Exception as e:
            print(f"{cmd_prefix}执行错误: {e}")
            with command_lock:
                retry_count += 1
                if retry_count > total_retries:
                    command_states[cmd_id]["status"] = CommandStatus.FAILED
                    command_states[cmd_id]["end_time"] = datetime.datetime.now()
    
    return False

def main():
    try:
        args = parse_args()
        commands = get_commands()
        
        if not commands:
            print("没有输入有效命令。退出。")
            sys.exit(1)
        
        # 打印命令列表
        print(format_command_list(commands))
        
        # 指令说明
        print(f"\n并发执行 {len(commands)} 条命令，失败重试次数: {args.total_retries}...")
        print(f"最大并发命令数: {args.max_concurrent}")
        print("可用命令:")
        print("  'status': 打印所有命令的当前状态")
        print("  'pause': 暂停所有运行中的命令")
        print("  'pause <id>': 按ID暂停特定命令")
        print("  'resume': 恢复所有已暂停的命令")
        print("  'resume <id>': 按ID恢复特定命令")
        print("  'exit': 终止所有命令并退出程序\n")
        
        # 初始化命令状态字典，确保所有命令都有一个初始状态
        for i, cmd in enumerate(commands):
            command_states[i] = {
                "command": cmd,
                "status": CommandStatus.INQUEUE,  # 使用INQUEUE状态(原PENDING)
                "process": None,
                "retry_count": 0,
                "start_time": None,
                "end_time": None
            }
        
        # 启动输入监听线程
        input_thread = threading.Thread(target=input_listener, daemon=True)
        input_thread.start()
        
        # 启动状态更新线程
        status_thread = threading.Thread(
            target=status_updater, 
            args=(args.status_interval,), 
            daemon=True
        )
        status_thread.start()
        
        # 创建命令执行的线程池
        with ThreadPoolExecutor(max_workers=args.max_concurrent) as executor:
            # 将命令提交到执行器
            futures = {
                executor.submit(execute_command, i, cmd, args.total_retries): (i, cmd)
                for i, cmd in enumerate(commands)
            }
            
            # 等待所有命令完成或停止事件
            while futures and not stop_event.is_set():
                # 处理任何已完成的future
                done, not_done = wait(
                    futures, 
                    timeout=1.0,
                    return_when=FIRST_COMPLETED
                )
                
                # 更新futures只包含未完成的future
                futures = not_done
                
                # 处理任何待处理的输入
                while not input_queue.empty():
                    # 只获取输入，它将由input_listener线程处理
                    input_queue.get()
            
            # 最终状态更新
            if not stop_event.is_set():
                print(format_command_status())
                
                # 统计成功和失败
                with command_lock:
                    success_count = sum(1 for state in command_states.values() 
                                     if state["status"] == CommandStatus.COMPLETED)  # 使用COMPLETED状态(原SUCCEEDED)
                    failure_count = sum(1 for state in command_states.values() 
                                     if state["status"] == CommandStatus.FAILED)
                
                print(f"\n执行完成。{success_count}/{len(commands)} 条命令成功，"
                      f"{failure_count}/{len(commands)} 条命令失败。")
    
    except KeyboardInterrupt:
        print("\n用户中断执行。退出。")
        stop_event.set()
        terminate_all_processes()
        sys.exit(1)
    except Exception as e:
        print(f"意外错误: {e}")
        stop_event.set()
        terminate_all_processes()
        sys.exit(1)
    finally:
        # 确保所有线程退出
        stop_event.set()

if __name__ == "__main__":
    main()
