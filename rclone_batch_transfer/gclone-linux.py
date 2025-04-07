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

# 尝试的编码列表，优化顺序和组合
ENCODINGS = [
    'utf-8',
    'utf-8-sig',  # 处理带BOM的UTF-8
    ('utf-8', 'ignore'),  # 忽略无法解码的部分
    'gb18030',  # 超集，包含GBK、GB2312
    'gbk',
    'big5',
    'shift-jis',
    'euc-jp',
    'euc-kr',
    'iso-8859-1'
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
    """尝试使用多种编码解码字节串"""
    if not isinstance(byte_string, bytes):
        return byte_string

    # 检测是否可能是纯ASCII
    try:
        result = byte_string.decode('ascii')
        return result
    except UnicodeDecodeError:
        pass

    # 首先尝试系统默认编码
    try:
        result = byte_string.decode(locale.getpreferredencoding())
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
                result = byte_string.decode(encoding)
            
            # 检查解码结果的质量
            if '\ufffd' not in result:  # 如果没有替换字符，可能是正确的编码
                return normalize_encoding(result)
            elif not result.startswith('\ufffd'):  # 如果开头没有替换字符，可能是部分正确
                return normalize_encoding(result)
        except UnicodeDecodeError:
            continue
    
    # 如果所有尝试都失败了，使用 UTF-8 with replacement
    result = byte_string.decode('utf-8', errors='replace')
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
    """设置信号处理器"""
    def signal_handler(signum, frame):
        print("\n程序被用户中断", flush=True)
        sys.exit(130)  # 标准的SIGINT错误代码
    
    signal.signal(signal.SIGINT, signal_handler)
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

def monitor_gclone(cmd=None):
    """监控gclone命令执行，处理HTTP 403错误并在必要时重试
    
    参数:
        cmd: 可选，直接指定要执行的命令
        
    返回:
        int: 命令执行的退出代码
    """
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
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                bufsize=0,  # 无缓冲
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None,  # Linux特有，设置进程组
                encoding=None  # 不指定编码，使用bytes
            )
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
                            print(f"\n[{datetime.now()}] 检测到HTTP 403错误且传输停滞，暂停8小时后重试", flush=True)
                            try:
                                if hasattr(os, 'killpg'):
                                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                                else:
                                    process.terminate()
                            except:
                                process.terminate()
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
                try:
                    if hasattr(os, 'killpg'):
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    else:
                        process.terminate()
                except:
                    process.terminate()
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
