import subprocess
import re
import time
import sys
import os
import locale
import argparse
from datetime import datetime
from threading import Thread
from queue import Queue, Empty
import signal
import ctypes
from ctypes import wintypes
import psutil  # 需要安装: pip install psutil

# Set console to UTF-8 on Windows
def set_windows_utf8():
    if os.name == 'nt':
        try:
            # Code page 65001 is UTF-8
            subprocess.run(['chcp', '65001'], shell=True, check=True, 
                          stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            # Enable virtual terminal processing for ANSI colors in Windows 10
            kernel32 = ctypes.WinDLL('kernel32')
            STD_OUTPUT_HANDLE = -11
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            mode = wintypes.DWORD()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
            print("Console set to UTF-8 mode", flush=True)
        except Exception as e:
            print(f"Warning: Failed to set console to UTF-8 mode: {e}", flush=True)

# Windows-specific process termination - 改进版本
def terminate_process(process):
    """终止进程及其所有子进程"""
    if os.name == 'nt':
        try:
            # 使用psutil来获取进程树并终止所有相关进程
            try:
                import psutil
                parent = psutil.Process(process.pid)
                children = parent.children(recursive=True)
                
                # 先终止所有子进程
                for child in children:
                    try:
                        print(f"[DEBUG] Terminating child process: PID={child.pid}, Name={child.name()}", flush=True)
                        child.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                # 等待子进程终止
                gone, alive = psutil.wait_procs(children, timeout=3)
                
                # 强制杀死仍然存活的子进程
                for p in alive:
                    try:
                        print(f"[DEBUG] Force killing child process: PID={p.pid}", flush=True)
                        p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                # 最后终止父进程
                try:
                    parent.terminate()
                    parent.wait(timeout=3)
                except psutil.TimeoutExpired:
                    print(f"[DEBUG] Force killing parent process: PID={parent.pid}", flush=True)
                    parent.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                    
            except ImportError:
                # 如果没有psutil，使用原有方法但更激进
                print("[WARNING] psutil not installed, using fallback method", flush=True)
                
                # 先尝试正常终止
                process.terminate()
                time.sleep(0.5)
                
                # 使用taskkill强制终止整个进程树
                if process.poll() is None:
                    # 使用/F强制，/T终止进程树
                    result = subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', str(process.pid)], 
                        shell=False,  # 不使用shell以避免额外的cmd进程
                        capture_output=True,
                        text=True
                    )
                    if result.returncode != 0:
                        print(f"[ERROR] taskkill failed: {result.stderr}", flush=True)
                        # 尝试使用wmic作为后备方案
                        try:
                            subprocess.run(
                                f'wmic process where "ParentProcessId={process.pid}" delete',
                                shell=True, check=False, capture_output=True
                            )
                            subprocess.run(
                                f'wmic process where "ProcessId={process.pid}" delete',
                                shell=True, check=False, capture_output=True
                            )
                        except:
                            pass
                            
        except Exception as e:
            print(f"[ERROR] Failed to terminate process: {e}", flush=True)
            # 最后的尝试
            try:
                os.kill(process.pid, signal.SIGTERM)
            except:
                pass
    else:
        # Unix-based process termination
        try:
            if hasattr(os, 'killpg'):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
        except Exception:
            process.terminate()

# 尝试的编码列表，优化顺序和组合
ENCODINGS = [
    'utf-8',
    ('utf-8', 'ignore'),  # Windows默认使用ignore模式
    'utf-8-sig',  # 处理带BOM的UTF-8
    'cp936',      # Windows中文系统常用
    'gb18030',    # 超集，包含GBK、GB2312
    'gbk',
    'big5',
    'shift-jis',
    'euc-jp',
    'euc-kr',
    'iso-8859-1',
    'cp1252'      # Windows西欧编码
]

def is_http_403_error(line):
    """
    判断是否为真正的HTTP 403错误
    
    判断标准：
    1. 包含 "Error 403:" 或 "403" + 以下关键词之一：
       - quota
       - limit
       - exceeded
       - rate
       - forbidden
    2. 403不能作为数字的一部分出现（如文件大小）
    
    返回：bool
    """
    # 直接匹配 Google API 的 403 错误格式
    if "Error 403:" in line:
        return True
        
    # 确保 403 不是文件大小的一部分
    # 使用正则表达式检查 403 的前后字符
    # 检查是否包含常见的 403 错误关键词组合
    error_patterns = [
        r'(?<!\d)403(?!\d).*(?:quota|limit|exceed|rate|forbidden)',  # 403后跟错误关键词
        r'(?:quota|limit|exceed|rate|forbidden).*(?<!\d)403(?!\d)',  # 403前有错误关键词
        r'HTTP.*(?<!\d)403(?!\d)',  # HTTP相关的403
        r'(?<!\d)403(?!\d).*Forbidden',  # 403 Forbidden
    ]
    
    # 任一模式匹配即认为是 HTTP 403 错误
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in error_patterns)

def normalize_encoding(text):
    """标准化文本编码，处理特殊字符和组合字符"""
    import unicodedata
    try:
        # 将文本转换为NFC标准形式
        normalized = unicodedata.normalize('NFC', text)
        # 尝试替换一些常见的问题字符
        normalized = normalized.replace('\ufffd', '?')  # 替换替换字符
        return normalized
    except Exception:
        return text

def try_decode(byte_string):
    """尝试使用多种编码解码字节串，Windows下默认使用ignore处理解码错误"""
    if not isinstance(byte_string, bytes):
        return byte_string

    # 检测是否可能是纯ASCII
    try:
        result = byte_string.decode('ascii')
        return result
    except UnicodeDecodeError:
        pass

    # Windows优先使用带ignore的UTF-8解码
    if os.name == 'nt':
        try:
            result = byte_string.decode('utf-8', errors='ignore')
            return normalize_encoding(result)
        except Exception:
            pass

    # 首先尝试系统默认编码
    try:
        system_encoding = locale.getpreferredencoding()
        result = byte_string.decode(system_encoding, errors='ignore' if os.name == 'nt' else 'strict')
        if not result.startswith('\ufffd'):  # 检查是否以替换字符开始
            return normalize_encoding(result)
    except UnicodeDecodeError:
        pass

    # 然后尝试其他编码
    for encoding in ENCODINGS:
        try:
            if isinstance(encoding, tuple):
                # 处理带错误处理方式的编码
                result = byte_string.decode(encoding[0], errors=encoding[1])
            else:
                # Windows下默认使用ignore作为错误处理模式
                error_mode = 'ignore' if os.name == 'nt' else 'strict'
                result = byte_string.decode(encoding, errors=error_mode)
            
            # 检查解码结果的质量
            if '\ufffd' not in result:  # 如果没有替换字符，可能是正确的编码
                return normalize_encoding(result)
            elif not result.startswith('\ufffd'):  # 如果开头没有替换字符，可能是部分正确
                return normalize_encoding(result)
        except UnicodeDecodeError:
            continue
    
    # 如果所有尝试都失败了，使用 UTF-8 with 'ignore'
    result = byte_string.decode('utf-8', errors='ignore')
    return normalize_encoding(result)

def clean_ansi(text):
    """清除ANSI转义序列"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def enqueue_output(out, queue):
    """将输出流放入队列中"""
    try:
        for line in iter(out.readline, b''):
            if line.strip():  # 忽略空行
                decoded_line = try_decode(line)
                if decoded_line:
                    queue.put(decoded_line)
    except Exception as e:
        queue.put(f"[错误] 输出处理异常: {str(e)}\n")
    finally:
        try:
            out.close()
        except:
            pass

def setup_signal_handlers():
    """设置信号处理器，Windows兼容"""
    def signal_handler(signum, frame):
        print("\n程序被用户中断", flush=True)
        sys.exit(130)  # 标准的SIGINT错误代码
    
    # Windows和POSIX平台通用的信号
    signal.signal(signal.SIGINT, signal_handler)
    
    # 仅在POSIX平台上设置SIGTERM
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)

def parse_transferred_count(line):
    """解析已传输文件数量，排除包含容量单位的行"""
    if any(unit in line for unit in ['B', 'iB', 'KB', 'MB', 'GB', 'TB']):
        return None
    
    match = re.search(r'Transferred:\s*(\d+)\s*/\s*\d+', line)
    if match:
        return int(match.group(1))
    return None

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='监控并执行gclone/rclone/fclone命令，处理HTTP 403错误')
    parser.add_argument('-shell', type=str, help='非交互式执行的命令')
    return parser.parse_args()

def check_psutil_availability():
    """检查psutil是否可用，如果不可用则给出警告"""
    try:
        import psutil
        return True
    except ImportError:
        print("[WARNING] psutil module not found. Process termination may not work properly.", flush=True)
        print("[WARNING] Install it using: pip install psutil", flush=True)
        return False

def monitor_gclone(cmd=None):
    """监控gclone命令执行，处理HTTP 403错误并在必要时重试
    
    参数:
        cmd: 可选，直接指定要执行的命令
        
    返回:
        int: 命令执行的退出代码
    """
    # 检查psutil可用性
    has_psutil = check_psutil_availability()
    
    if cmd is None:
        # 交互式模式
        print("请输入要执行的指令:", flush=True)
        cmd = input().strip()
        try:
            input()  # 等待第二次回车
        except EOFError:
            pass  # 如果在管道中运行，可能没有第二个输入
    
    if not cmd:
        print("指令不能为空", flush=True)
        return 1  # 返回错误代码

    # 确保命令中包含 -P 参数
    if '-P' not in cmd:
        cmd += ' -P'

    last_exit_code = 0  # 初始化为0，表示成功

    while True:
        print(f"\n[{datetime.now()}] 执行命令: {cmd}", flush=True)
        
        try:
            # Windows兼容的进程启动
            startupinfo = None
            creationflags = 0
            
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                
                # 创建新的进程组，便于终止整个进程树
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                bufsize=0,  # 无缓冲
                encoding=None,  # 不指定编码，使用bytes
                startupinfo=startupinfo,  # Windows特有
                creationflags=creationflags  # Windows进程创建标志
            )
            
            print(f"[DEBUG] Process started with PID: {process.pid}", flush=True)
            
        except Exception as e:
            print(f"启动进程失败: {e}", flush=True)
            return 1  # 返回错误代码

        # 创建输出队列和线程
        stdout_queue = Queue()
        stderr_queue = Queue()
        stdout_thread = Thread(target=enqueue_output, args=(process.stdout, stdout_queue))
        stderr_thread = Thread(target=enqueue_output, args=(process.stderr, stderr_queue))
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()

        # 仅对HTTP 403错误进行计数
        error_count_403 = 0  
        last_transferred = 0
        consecutive_same_transfer = 0
        in_transferring_section = False

        # 用于标记"脚本主动杀死进程，准备重试"
        need_retry = False

        while process.poll() is None:
            try:
                # 读取并处理 stdout
                while True:
                    try:
                        line = stdout_queue.get_nowait()
                        
                        clean_line = clean_ansi(line)
                        print(clean_line, end='', flush=True)
                        
                        # 是否进入或离开 Transferring 部分
                        if 'Transferring:' in clean_line:
                            in_transferring_section = True
                        elif clean_line.strip() and not clean_line.startswith(' '):
                            in_transferring_section = False
                        
                        # 检测HTTP 403错误
                        if "ERROR" in clean_line and is_http_403_error(clean_line):
                            error_count_403 += 1
                            print(f"[DEBUG] 403 Error count: {error_count_403}", flush=True)

                        # 解析传输数量
                        transferred = parse_transferred_count(clean_line)
                        if transferred is not None:
                            if transferred == last_transferred:
                                consecutive_same_transfer += 1
                                print(f"[DEBUG] Same transfer count: {consecutive_same_transfer}", flush=True)
                            else:
                                consecutive_same_transfer = 0
                                last_transferred = transferred

                        # 当检测到 403 错误累计 >=5 且传输停滞次数 >=5 时，执行休眠 8 小时
                        if error_count_403 >= 5 and consecutive_same_transfer >= 5:
                            print(f"\n[{datetime.now()}] 检测到HTTP 403错误且传输停滞，准备终止进程并暂停8小时", flush=True)
                            
                            # 终止进程
                            print("[DEBUG] Terminating process...", flush=True)
                            terminate_process(process)
                            
                            # 确保进程已经终止
                            try:
                                process.wait(timeout=10)
                                print("[DEBUG] Process terminated successfully", flush=True)
                            except subprocess.TimeoutExpired:
                                print("[ERROR] Process did not terminate in time, forcing kill", flush=True)
                                # 再次尝试强制终止
                                if os.name == 'nt':
                                    subprocess.run(f'taskkill /F /T /PID {process.pid}', shell=True, capture_output=True)
                                else:
                                    os.kill(process.pid, signal.SIGKILL)
                            
                            # 等待一下确保进程完全终止
                            time.sleep(2)
                            
                            print(f"[{datetime.now()}] 开始暂停8小时...", flush=True)
                            time.sleep(8 * 3600)  # 休眠8小时
                            
                            # 重置计数
                            error_count_403 = 0
                            consecutive_same_transfer = 0
                            need_retry = True
                            break

                    except Empty:
                        break

                if need_retry:
                    break

                # 读取并处理 stderr
                while True:
                    try:
                        err = stderr_queue.get_nowait()
                        clean_err = clean_ansi(err)
                        print(clean_err, end='', flush=True, file=sys.stderr)
                    except Empty:
                        break

                time.sleep(0.1)

            except KeyboardInterrupt:
                print("\n[DEBUG] Keyboard interrupt detected, terminating process...", flush=True)
                terminate_process(process)
                print("\n程序被用户中断", flush=True)
                return 130  # 标准的SIGINT错误代码

        exit_code = process.poll()
        last_exit_code = exit_code  # 保存最后一次的退出代码

        # 输出可能残留在队列中的内容
        for queue in [stdout_queue, stderr_queue]:
            while True:
                try:
                    line = queue.get_nowait()
                    clean_line = clean_ansi(line)
                    print(clean_line, end='', flush=True)
                except Empty:
                    break

        if need_retry:
            need_retry = False
            continue

        # 根据 exit_code 判断退出
        if exit_code == 0:
            print(f"\n[{datetime.now()}] 命令执行完成", flush=True)
            break
        else:
            print(f"\n[{datetime.now()}] 命令执行失败，退出码: {exit_code}", flush=True)
            break

    return last_exit_code  # 返回最后一次的退出代码

def main():
    try:
        # 在Windows上设置UTF-8编码
        set_windows_utf8()
        
        args = parse_args()
        setup_signal_handlers()
        
        if args.shell:
            # 非交互式模式
            exit_code = monitor_gclone(args.shell)
        else:
            # 交互式模式
            exit_code = monitor_gclone()
        
        sys.exit(exit_code)  # 使用gclone命令的退出代码作为脚本的退出代码
            
    except KeyboardInterrupt:
        print("\n程序被用户中断", flush=True)
        sys.exit(130)  # 标准的SIGINT错误代码
    except Exception as e:
        print(f"发生错误: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
