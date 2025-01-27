import subprocess
import re
import time
import sys
import os
import locale
from datetime import datetime
from threading import Thread
from queue import Queue, Empty
import signal
import ctypes
from ctypes import wintypes
import msvcrt

# Windows API 常量和函数定义
PROCESS_TERMINATE = 0x0001
CTRL_C_EVENT = 0
CTRL_BREAK_EVENT = 1
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

# 加载Windows API
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

# 定义Windows Job对象相关结构和函数
class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_int64),
        ('PerJobUserTimeLimit', ctypes.c_int64),
        ('LimitFlags', ctypes.c_uint32),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', ctypes.c_uint32),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', ctypes.c_uint32),
        ('SchedulingClass', ctypes.c_uint32)
    ]

class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ('IoInfo', ctypes.c_uint64 * 2),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t)
    ]

# 设置Windows API函数参数类型
kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
kernel32.SetInformationJobObject.restype = wintypes.BOOL
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

def create_job_object():
    """创建Windows Job对象用于进程管理"""
    job = kernel32.CreateJobObjectW(None, None)
    if job == 0:
        return None
    
    job_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    job_info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    
    length = ctypes.sizeof(job_info)
    kernel32.SetInformationJobObject(job, 9, ctypes.byref(job_info), length)
    
    return job

# 编码尝试顺序
UTF8_ENCODINGS = [
    'utf-8-sig',    # 带BOM的UTF-8
    'utf-8',        # UTF-8
]

CHINESE_ENCODINGS = [
    'cp936',        # Windows 默认中文编码
    'gb18030',      # GB18030 超集
    'gbk',          # GBK编码
]

OTHER_ENCODINGS = [
    'big5',         # 繁体中文
    'shift-jis',    # 日文
    'euc-jp',       # 日文
    'euc-kr',       # 韩文
    'iso-8859-1'    # 西欧
]

def is_http_403_error(line):
    """判断是否为真正的HTTP 403错误"""
    if "Error 403:" in line:
        return True
    
    error_patterns = [
        r'(?<!\d)403(?!\d).*(?:quota|limit|exceed|rate|forbidden)',
        r'(?:quota|limit|exceed|rate|forbidden).*(?<!\d)403(?!\d)',
        r'HTTP.*(?<!\d)403(?!\d)',
        r'(?<!\d)403(?!\d).*Forbidden',
    ]
    
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in error_patterns)

def normalize_encoding(text):
    """标准化文本编码，处理特殊字符和组合字符"""
    import unicodedata
    try:
        normalized = unicodedata.normalize('NFC', text)
        normalized = normalized.replace('\ufffd', '?')
        return normalized
    except Exception:
        return text

def try_decode(byte_string):
    """尝试使用多种编码解码字节串，按优先级尝试不同编码"""
    if not isinstance(byte_string, bytes):
        return byte_string

    def decode_quality(text):
        """评估解码质量，返回替换字符的数量"""
        return text.count('\ufffd')

    def try_encoding(byte_data, encoding, errors='strict'):
        """尝试特定编码并评估质量"""
        try:
            result = byte_data.decode(encoding, errors=errors)
            return result, decode_quality(result)
        except UnicodeDecodeError:
            return None, float('inf')

    # 1. 优先尝试 UTF-8 编码
    for encoding in UTF8_ENCODINGS:
        result, quality = try_encoding(byte_string, encoding)
        if quality == 0:  # UTF-8 完美解码
            return normalize_encoding(result)

    # 2. 尝试常见中文编码
    best_result = None
    best_quality = float('inf')
    
    for encoding in CHINESE_ENCODINGS:
        result, quality = try_encoding(byte_string, encoding)
        if quality == 0:  # 完美解码
            return normalize_encoding(result)
        if quality < best_quality:
            best_quality = quality
            best_result = result

    # 如果中文编码得到了较好的结果（替换字符少于5%）
    if best_result and best_quality < len(best_result) * 0.05:
        return normalize_encoding(best_result)

    # 3. 尝试其他编码
    for encoding in OTHER_ENCODINGS:
        result, quality = try_encoding(byte_string, encoding)
        if quality == 0:  # 完美解码
            return normalize_encoding(result)
        if quality < best_quality:
            best_quality = quality
            best_result = result

    # 4. 如果之前的尝试得到了还可以的结果（替换字符少于10%）
    if best_result and best_quality < len(best_result) * 0.1:
        return normalize_encoding(best_result)

    # 5. 最后兜底：使用系统默认编码
    try:
        result = byte_string.decode(locale.getpreferredencoding(), errors='replace')
        if decode_quality(result) < len(result) * 0.2:  # 允许最多20%的替换字符
            return normalize_encoding(result)
    except:
        pass

    # 6. 最终兜底：使用 UTF-8 + replace
    return normalize_encoding(byte_string.decode('utf-8', errors='replace'))

def clean_ansi(text):
    """清除ANSI转义序列"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def enqueue_output(out, queue):
    """将输出流放入队列中"""
    try:
        for line in iter(out.readline, b''):
            if line.strip():
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

def terminate_process_tree(pid):
    """终止进程树"""
    try:
        # 使用taskkill命令终止进程树
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], 
                      stdout=subprocess.PIPE, 
                      stderr=subprocess.PIPE,
                      check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def parse_transferred_count(line):
    """解析已传输文件数量，排除包含容量单位的行"""
    if any(unit in line for unit in ['B', 'iB', 'KB', 'MB', 'GB', 'TB']):
        return None
    
    match = re.search(r'Transferred:\s*(\d+)\s*/\s*\d+', line)
    if match:
        return int(match.group(1))
    return None

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

    # 创建Job对象
    job = create_job_object()
    if not job:
        print("无法创建Job对象，进程管理可能受限", flush=True)

    while True:
        print(f"\n[{datetime.now()}] 执行命令: {cmd}", flush=True)
        
        try:
            # 创建进程
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                bufsize=0,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                encoding=None
            )

            # 将进程加入Job对象
            if job:
                kernel32.AssignProcessToJobObject(job, int(process._handle))
        except Exception as e:
            print(f"启动进程失败: {e}", flush=True)
            return

        stdout_queue = Queue()
        stderr_queue = Queue()
        stdout_thread = Thread(target=enqueue_output, args=(process.stdout, stdout_queue))
        stderr_thread = Thread(target=enqueue_output, args=(process.stderr, stderr_queue))
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()

        error_count_403 = 0
        last_transferred = 0
        consecutive_same_transfer = 0
        in_transferring_section = False
        need_retry = False

        while process.poll() is None:
            try:
                while True:
                    try:
                        line = stdout_queue.get_nowait()
                        clean_line = clean_ansi(line)
                        print(clean_line, end='', flush=True)
                        
                        if 'Transferring:' in clean_line:
                            in_transferring_section = True
                        elif clean_line.strip() and not clean_line.startswith(' '):
                            in_transferring_section = False
                        
                        if "ERROR" in clean_line and is_http_403_error(clean_line):
                            error_count_403 += 1
                            print(f"[DEBUG] 403 Error count: {error_count_403}", flush=True)

                        transferred = parse_transferred_count(clean_line)
                        if transferred is not None:
                            if transferred == last_transferred:
                                consecutive_same_transfer += 1
                                print(f"[DEBUG] Same transfer count: {consecutive_same_transfer}", flush=True)
                            else:
                                consecutive_same_transfer = 0
                                last_transferred = transferred

                        if error_count_403 >= 5 and consecutive_same_transfer >= 5:
                            print(f"\n[{datetime.now()}] 检测到HTTP 403错误且传输停滞，暂停8小时后重试", flush=True)
                            terminate_process_tree(process.pid)
                            time.sleep(8 * 3600)
                            error_count_403 = 0
                            consecutive_same_transfer = 0
                            need_retry = True
                            break

                    except Empty:
                        break

                if need_retry:
                    break

                while True:
                    try:
                        err = stderr_queue.get_nowait()
                        clean_err = clean_ansi(err)
                        print(clean_err, end='', flush=True, file=sys.stderr)
                    except Empty:
                        break

                time.sleep(0.1)

            except KeyboardInterrupt:
                print("\n正在终止进程...", flush=True)
                terminate_process_tree(process.pid)
                return

        exit_code = process.poll()

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

        if exit_code == 0:
            print(f"\n[{datetime.now()}] 命令执行完成", flush=True)
            break
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
    finally:
        sys.exit(0)
