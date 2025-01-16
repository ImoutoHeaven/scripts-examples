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
    """
    监控 gclone 进程。
    
    当检测到：
      - 连续错误数 >= 5
      - 且已传输文件数多次保持不变（consecutive_same_transfer >= 5）
    时，设置 need_retry = True 并返回。

    外层可根据 need_retry 的值，决定是否进行 8 小时休眠并重试，
    或者是直接退出不再重试。
    
    :return: bool, 为 True 表示需要外部休眠 8 小时再重试；False 表示无需重试，脚本可以结束。
    """
    print("请输入要执行的指令:", flush=True)
    cmd = input().strip()
    input()  # 等待第二次回车
    
    if not cmd:
        print("指令不能为空", flush=True)
        return False  # 不需要重试，直接退出

    # 确保命令中包含 -P 参数
    if '-P' not in cmd:
        cmd += ' -P'

    need_retry = False  # 用于标记是否需要外部 sleep 8h 后重试

    while True:
        print(f"\n[{datetime.now()}] 执行命令: {cmd}", flush=True)
        
        # 使用 subprocess.STARTUPINFO 来隐藏新窗口（仅在 Windows 有效）
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
        in_transferring_section = False  # 标记是否在 "Transferring:" 部分内

        # 实时读取输出
        while process.poll() is None:
            try:
                # 检查标准输出
                while True:
                    try:
                        line = stdout_queue.get_nowait()
                        
                        # 清除 ANSI 转义序列并打印
                        clean_line = clean_ansi(line)
                        print(clean_line, end='', flush=True)
                        
                        # 检查是否进入或离开 "Transferring:" 部分
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
                        
                        # 当检测到连续错误数 >= 5 且传输数停滞 >= 5 时
                        # 标记 need_retry=True，终止当前 gclone，并返回到外层处理
                        if error_count >= 5 and consecutive_same_transfer >= 5:
                            print(f"\n[{datetime.now()}] 检测到连续错误且传输停滞，需要休眠后重试", flush=True)
                            process.terminate()
                            need_retry = True
                            break

                    except Empty:
                        break

                # 若需要重试则跳出最外层循环
                if need_retry:
                    break

                # 检查错误输出
                while True:
                    try:
                        err = stderr_queue.get_nowait()
                        clean_err = clean_ansi(err)
                        print(clean_err, end='', flush=True, file=sys.stderr)
                    except Empty:
                        break

                time.sleep(0.1)  # 避免 CPU 占用过高

            except KeyboardInterrupt:
                process.terminate()
                print("\n程序被用户中断", flush=True)
                return False  # 不需要重试，用户主动中断

        # 进程结束后的处理
        exit_code = process.poll()
        
        # 清空剩余输出
        for q in (stdout_queue, stderr_queue):
            while True:
                try:
                    line = q.get_nowait()
                    clean_line = clean_ansi(line)
                    print(clean_line, end='', flush=True)
                except Empty:
                    break

        # 如果在循环中被标记了 need_retry，就直接返回 True
        if need_retry:
            return True  # 通知外层脚本：需要 8 小时休眠后重试

        # 正常情况下，根据退出码判断是否成功或失败
        if exit_code == 0:
            print(f"\n[{datetime.now()}] 命令执行完成", flush=True)
            return False  # 成功执行，不需要重试
        else:
            print(f"\n[{datetime.now()}] 命令执行失败，退出码: {exit_code}", flush=True)
            return False  # 失败退出，不需要重试

def main():
    """
    程序入口：连续检测 monitor_gclone() 的返回值。
    如果返回 True，则等待 8 小时后再重试。
    如果返回 False，则表示无需继续重试，直接退出。
    """
    while True:
        try:
            need_retry = monitor_gclone()
            if need_retry:
                print("\n[主进程] 检测到 need_retry=True，等待 8 小时后重试...", flush=True)
                time.sleep(8 * 3600)  # 休眠 8 小时
            else:
                # 不需要重试，直接退出循环
                break
        except KeyboardInterrupt:
            print("\n[主进程] 程序被用户中断", flush=True)
            break
        except Exception as e:
            print(f"[主进程] 发生错误: {e}", flush=True)
            break

if __name__ == "__main__":
    main()
