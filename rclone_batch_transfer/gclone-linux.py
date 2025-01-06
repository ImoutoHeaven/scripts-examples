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
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

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
        
        # 在Linux下创建进程
        try:
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                bufsize=0,  # 无缓冲
                preexec_fn=os.setsid,  # Linux特有，设置进程组
                encoding=None  # 不指定编码，使用bytes
            )
        except Exception as e:
            print(f"启动进程失败: {e}", flush=True)
            return

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
        in_transferring_section = False

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
                            try:
                                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            except:
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
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    except:
                        process.terminate()
                    break

                time.sleep(0.1)  # 避免CPU占用过高

            except KeyboardInterrupt:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except:
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
        setup_signal_handlers()
        monitor_gclone()
    except KeyboardInterrupt:
        print("\n程序被用户中断", flush=True)
    except Exception as e:
        print(f"发生错误: {e}", flush=True)
