import subprocess
import re
import time
import sys
import locale
from datetime import datetime
from threading import Thread
from queue import Queue, Empty

# 尝试的编码列表
ENCODINGS = ['utf-8', 'gbk', 'gb18030', 'cp936', 'big5', 'shift-jis']

def parse_transferred_count(line):
    """解析已传输文件数量，排除包含容量单位的行"""
    if any(unit in line for unit in ['B', 'iB', 'KB', 'MB', 'GB', 'TB']):
        return None
    
    match = re.search(r'Transferred:\s*(\d+)\s*/\s*\d+', line)
    if match:
        return int(match.group(1))
    return None

def parse_error_count(line):
    """解析错误计数行"""
    match = re.search(r'Errors:\s*(\d+)', line)
    if match:
        return int(match.group(1))
    return None

def try_decode(byte_string):
    """尝试使用多种编码解码字节串"""
    if not isinstance(byte_string, bytes):
        return byte_string

    for encoding in ENCODINGS:
        try:
            return byte_string.decode(encoding)
        except UnicodeDecodeError:
            continue
    return byte_string.decode('utf-8', errors='replace')

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
        out.close()

def monitor_gclone():
    print("请输入要执行的指令:", flush=True)
    cmd = input().strip()
    input()  # 等待第二次回车
    
    if not cmd:
        print("指令不能为空", flush=True)
        return

    # 确保命令中包含 -P 参数
    if '-P' not in cmd:
        cmd += ' -P'

    while True:
        print(f"\n[{datetime.now()}] 执行命令: {cmd}", flush=True)
        
        # 使用 subprocess.STARTUPINFO 来隐藏新窗口
        startupinfo = None
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        # 启动进程并捕获输出
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            bufsize=0,  # 无缓冲
            startupinfo=startupinfo
        )

        # 创建输出队列和线程
        stdout_queue = Queue()
        stderr_queue = Queue()
        stdout_thread = Thread(target=enqueue_output, args=(process.stdout, stdout_queue))
        stderr_thread = Thread(target=enqueue_output, args=(process.stderr, stderr_queue))
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()

        error_count = 0
        last_transferred = 0
        consecutive_same_transfer = 0
        last_output_time = time.time()
        in_transferring_section = False  # 标记是否在 Transferring 部分

        # 实时读取输出
        while process.poll() is None:
            try:
                # 检查标准输出
                while True:
                    try:
                        line = stdout_queue.get_nowait()
                        last_output_time = time.time()
                        
                        # 清除ANSI转义序列并打印
                        clean_line = clean_ansi(line)
                        print(clean_line, end='', flush=True)
                        
                        # 检查是否进入或离开 Transferring 部分
                        if 'Transferring:' in clean_line:
                            in_transferring_section = True
                        elif clean_line.strip() and not clean_line.startswith(' '):
                            in_transferring_section = False
                        
                        # 只在非 Transferring 部分检查错误
                        if not in_transferring_section:
                            # 检查错误计数
                            errors = parse_error_count(clean_line)
                            if errors is not None:
                                error_count = errors
                                if error_count > 0:
                                    print(f"[DEBUG] Error count: {error_count}", flush=True)
                        
                        # 解析传输数量
                        transferred = parse_transferred_count(clean_line)
                        if transferred is not None:
                            if transferred == last_transferred:
                                consecutive_same_transfer += 1
                                print(f"[DEBUG] Same transfer count: {consecutive_same_transfer}", flush=True)
                            else:
                                consecutive_same_transfer = 0
                                last_transferred = transferred
                        
                        # 检查是否需要暂停
                        if error_count >= 5 and consecutive_same_transfer >= 5:
                            print(f"\n[{datetime.now()}] 检测到连续错误且传输停滞，暂停8小时后重试", flush=True)
                            process.terminate()
                            time.sleep(8 * 3600)  # 休眠8小时
                            error_count = 0
                            consecutive_same_transfer = 0
                            break

                    except Empty:
                        break

                # 检查错误输出
                while True:
                    try:
                        err = stderr_queue.get_nowait()
                        last_output_time = time.time()
                        clean_err = clean_ansi(err)
                        print(clean_err, end='', flush=True, file=sys.stderr)
                        
                    except Empty:
                        break

                # 检查是否有一段时间没有输出（可能是卡住了）
                if time.time() - last_output_time > 300:  # 5分钟没有任何输出
                    print(f"\n[{datetime.now()}] 检测到5分钟无输出，重新启动任务", flush=True)
                    process.terminate()
                    break

                time.sleep(0.1)  # 避免CPU占用过高

            except KeyboardInterrupt:
                process.terminate()
                print("\n程序被用户中断", flush=True)
                return

        # 进程结束后的处理
        exit_code = process.poll()
        
        # 清空剩余输出
        for queue in [stdout_queue, stderr_queue]:
            while True:
                try:
                    line = queue.get_nowait()
                    clean_line = clean_ansi(line)
                    print(clean_line, end='', flush=True)
                except Empty:
                    break

        if exit_code == 0:
            print(f"\n[{datetime.now()}] 命令执行完成", flush=True)
            break
        elif error_count >= 5 and consecutive_same_transfer >= 5:
            continue
        else:
            print(f"\n[{datetime.now()}] 命令执行失败，退出码: {exit_code}", flush=True)
            break

if __name__ == "__main__":
    try:
        monitor_gclone()
    except KeyboardInterrupt:
        print("\n程序被用户中断", flush=True)
    except Exception as e:
        print(f"发生错误: {e}", flush=True)
