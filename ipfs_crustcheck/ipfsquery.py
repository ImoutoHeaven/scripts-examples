#!/usr/bin/env python3
import subprocess
import shlex
import sys
import os
import fcntl
import time
import math
import json
import tempfile
from datetime import datetime
import threading
import concurrent.futures
from collections import defaultdict

# 获取环境变量中的 ipfs 执行命令，并分割成列表
def get_ipfs_cmd():
    ipfs_exec = os.environ.get('ipfsexec')
    if ipfs_exec:
        # 使用 shlex.split 正确处理带空格的命令
        return shlex.split(ipfs_exec)
    return ['ipfs']  # 默认命令

# 全局变量保存 IPFS 命令
IPFS_CMD = get_ipfs_cmd()

# 日志锁，防止多线程输出混乱
log_lock = threading.Lock()

def log_info(message, thread_id=None):
    """线程安全的日志输出"""
    with log_lock:
        if thread_id is not None:
            print(f"[INFO] [线程 {thread_id}] {message}")
        else:
            print(f"[INFO] {message}")

def log_warn(message, thread_id=None):
    """线程安全的警告输出"""
    with log_lock:
        if thread_id is not None:
            print(f"[WARN] [线程 {thread_id}] {message}", file=sys.stderr)
        else:
            print(f"[WARN] {message}", file=sys.stderr)

def log_error(message, thread_id=None):
    """线程安全的错误输出"""
    with log_lock:
        if thread_id is not None:
            print(f"[ERROR] [线程 {thread_id}] {message}", file=sys.stderr)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)

def run_command_with_retry(cmd_args, max_attempts=3, retry_delay=2):
    """
    带重试逻辑的命令执行，最多尝试指定次数。
    cmd_args 是一个列表，例如 ["ipfs", "files", "ls", "-l", "/some/path"]。
    """
    attempts = 0
    last_error = None
    
    while attempts < max_attempts:
        attempts += 1
        try:
            log_info(f"执行: {' '.join(cmd_args)} (尝试 {attempts}/{max_attempts})")
            result = subprocess.run(
                cmd_args, 
                text=True,
                capture_output=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            last_error = e
            log_error(f"调用命令失败: {' '.join(cmd_args)} (尝试 {attempts}/{max_attempts})")
            log_error(e.stderr)
            
            if attempts < max_attempts:
                log_info(f"{retry_delay} 秒后重试...")
                time.sleep(retry_delay)
        except FileNotFoundError as e:
            log_error(f"找不到可执行文件: {cmd_args[0]} - {e}")
            sys.exit(1)
    
    # 所有重试都失败
    log_error(f"命令 {' '.join(cmd_args)} 在 {max_attempts} 次尝试后仍然失败")
    if last_error:
        log_error(last_error.stderr)
    return None

def parse_ipfs_ls_line(line):
    """
    对一行输出（例如：
      2025-01-12 IPFS/	bafybeidi2vknaeciqi5oknimdxyjmmugwgrxpdblffsbbcyfnh2cfsqyom	0）
    拆分出文件名、CID 和文件大小。
    """
    line = line.rstrip('\n')
    tokens = line.split()  # 按任意空白分割
    if len(tokens) < 3:
        log_warn(f"无法解析行: {line}")
        return None, None, None
    size_str = tokens[-1]
    cid = tokens[-2]
    name_parts = tokens[:-2]
    name = " ".join(name_parts)
    try:
        size = int(size_str)
    except ValueError:
        log_warn(f"无法解析size为数字: {line}")
        return None, None, None
    return name, cid, size

def list_files_recursive(mfs_path, collected_files, max_retries=3):
    """
    递归列出 MFS 路径下所有文件（非文件夹）。
    mfs_path: 形如 "/", "/some folder/", "/some folder/inner folder/" 等。
    collected_files: 用于存放 (文件名, CID, 大小) 的列表。
    max_retries: 每个IPFS命令的最大重试次数
    注意：
    - 如果 mfs_path 末尾没有 '/', 则自动补上。
    """
    # 如果 mfs_path 末尾没有 '/'，则添加
    if not mfs_path.endswith("/"):
        mfs_path = mfs_path + "/"
    cmd = IPFS_CMD + ["files", "ls", "-l", mfs_path]
    output = run_command_with_retry(cmd, max_attempts=max_retries)
    
    # 如果即使在重试后命令仍然失败，则跳过此目录
    if output is None:
        log_warn(f"无法列出目录 {mfs_path}，跳过此目录")
        return
    for line in output.splitlines():
        if not line.strip():
            continue
        name, cid, size = parse_ipfs_ls_line(line)
        if name is None:
            continue
        if name.endswith("/"):
            # 说明为文件夹，构造新的 MFS 路径并递归处理
            folder_name = name  # 已包含 '/'
            new_path = os.path.join(mfs_path, folder_name)
            # 清理可能出现的多余斜杠
            new_path = new_path.replace("//", "/")
            list_files_recursive(new_path, collected_files, max_retries)
        else:
            # 对于文件，我们检查是否已经获取了有效的 CID
            if cid and len(cid) > 0:
                file_path = os.path.join(mfs_path, name).replace("//", "/")
                collected_files.append((file_path, cid, size))
            else:
                log_warn(f"跳过无效 CID 的文件: {os.path.join(mfs_path, name)}")

def parse_crustcheck_results(output_text, keep_path=False):
    """解析crustcheck输出，提取表格数据"""
    results = {
        'table1': [],
        'table2': [],
        'table3': []
    }
    
    current_table = None
    header = None
    
    for line in output_text.splitlines():
        line = line.strip()
        
        # 跳过API断开连接的消息
        if "API disconnected" in line:
            continue
            
        # 检测表格分隔符
        if line == '====':
            current_table = None
            header = None
            continue
        
        # 检测表格标题开始
        if line.startswith('FILE_NAME\t'):
            if 'ONCHAIN_STATUS' in line:
                current_table = 'table1'
            elif 'INPUT FILE SIZE ONLY' in line:
                current_table = 'table2'
            else:
                current_table = 'table3'
            header = line
            continue
        
        # 检测表格标题或表格分隔线
        if line == '----' or line.startswith('FAILED CIDs'):
            continue
            
        # 如果在表格中且不是标题或分隔符，则添加数据行
        if current_table and header and line:
            # 检查行是否符合表格格式（至少包含2个制表符，确保有3个数据字段）
            if line.count('\t') >= 2:
                # 只有在keep_path=True时才替换竖线为斜杠
                if keep_path:
                    parts = line.split('\t')
                    if len(parts) > 0:
                        filename_part = parts[0]
                        # 将竖线替换回斜杠，还原路径显示
                        fixed_filename = filename_part.replace('|', '/')
                        # 重建行
                        parts[0] = fixed_filename
                        line = '\t'.join(parts)
                
                results[current_table].append(line)
            # 否则可能是一些输出信息混入了表格数据
    
    return results

def run_crustcheck(thread_id, files, tmp_file_path, crustcheck_args, total_threads, results_dict, keep_path=False):
    """
    执行一个 crustcheck 进程，处理指定文件列表，并收集结果
    
    thread_id: 线程ID（从1开始）
    files: 包含 (文件名, CID, 大小) 的列表
    tmp_file_path: 临时文件路径
    crustcheck_args: 传递给 crustcheck 的参数
    total_threads: 总线程数
    results_dict: 共享的结果字典，用于存储输出
    
    返回: crustcheck 的退出码
    """
    log_info(f"开始处理 {len(files)} 个文件", thread_id)
    
    # 创建临时文件
    try:
        with open(tmp_file_path, "w", encoding="utf-8", errors="replace") as f:
            for (file_path, file_cid, file_size) in files:
                try:
                    if keep_path:
                        # 将路径中的斜杠替换为竖线，以保持路径层级的可视化
                        safe_file_name = file_path.replace('/', '|')
                    else:
                        # 只取文件名部分，不包含路径
                        file_name = os.path.basename(file_path)
                        safe_file_name = file_name
                        
                    safe_line = f"{safe_file_name}\t{file_cid}\t{file_size}\n"
                    f.write(safe_line)
                except UnicodeEncodeError:
                    # 如果有编码问题，使用 repr() 来获取一个安全的可打印表示
                    if keep_path:
                        safe_file_name = repr(file_path)[1:-1].replace('/', '|')  # 去掉引号并替换斜杠
                    else:
                        file_name = os.path.basename(file_path)
                        safe_file_name = repr(file_name)[1:-1]  # 去掉引号
                        
                    safe_line = f"{safe_file_name}\t{file_cid}\t{file_size}\n"
                    log_warn(f"文件名包含特殊字符，进行转义: {safe_file_name}", thread_id)
                    f.write(safe_line)
    except Exception as e:
        log_error(f"创建临时文件 {tmp_file_path} 失败: {e}", thread_id)
        return 1
    
    # 打开日志文件上锁，并调用 crustcheck 程序
    try:
        with open(tmp_file_path, "r+") as f_log:
            try:
                fcntl.flock(f_log, fcntl.LOCK_EX)
                # 组装 crustcheck 命令：添加 --input 参数和其它传入的参数
                cmd = ["crustcheck", "--input", tmp_file_path] + crustcheck_args
                
                log_info(f"执行: {' '.join(shlex.quote(x) for x in cmd)}", thread_id)
                
                # 创建临时文件来收集输出
                output_file = tempfile.NamedTemporaryFile(delete=False, mode='w+b')
                
                try:
                    # 使用subprocess.run捕获输出，而不是实时显示
                    process = subprocess.Popen(
                        cmd,
                        stdout=output_file,
                        stderr=subprocess.STDOUT,
                        bufsize=1
                    )
                    
                    # 等待进程完成
                    returncode = process.wait()
                    log_info(f"crustcheck 完成，退出码: {returncode}", thread_id)
                    
                    # 读取输出
                    output_file.flush()
                    output_file.close()
                    
                    with open(output_file.name, 'r', encoding='utf-8', errors='replace') as f:
                        output_text = f.read()
                    
                    # 解析输出中的结果
                    parsed_results = parse_crustcheck_results(output_text, keep_path)
                    
                    # 将结果添加到共享字典
                    with log_lock:  # 使用锁保护结果字典的访问
                        results_dict['table1'].extend(parsed_results['table1'])
                        results_dict['table2'].extend(parsed_results['table2'])
                        results_dict['table3'].extend(parsed_results['table3'])
                    
                    return returncode
                except Exception as e:
                    log_error(f"执行 crustcheck 出错: {e}", thread_id)
                    return 1
                finally:
                    # 删除临时输出文件
                    try:
                        os.unlink(output_file.name)
                    except:
                        pass
            finally:
                try:
                    fcntl.flock(f_log, fcntl.LOCK_UN)
                except Exception as e:
                    log_warn(f"解锁临时文件失败: {e}", thread_id)
    except Exception as e:
        log_error(f"打开临时文件失败: {e}", thread_id)
        return 1
    finally:
        try:
            os.remove(tmp_file_path)
        except OSError as e:
            log_warn(f"删除临时文件 {tmp_file_path} 失败: {e}", thread_id)

def display_combined_results(results_dict, save_log=False, output_path=None):
    """显示合并后的结果表格"""
    output_lines = []
    
    # TABLE 1
    output_lines.append('FILE_NAME\tFILE_CID\tFILE_SIZE\tFILE_ONCHAIN_STATUS\tFILE_REPLICAS')
    output_lines.append('----')
    output_lines.extend(results_dict['table1'])
    
    # 表格分隔
    output_lines.append('====')
    
    # TABLE 2
    output_lines.append('FILE_NAME\tFILE_CID\tFILE_SIZE(INPUT FILE SIZE ONLY)')
    output_lines.append('----')
    output_lines.extend(results_dict['table2'])
    
    # 如果有失败的CID，显示TABLE 3
    if results_dict['table3']:
        output_lines.append('====')
        output_lines.append('FAILED CIDs (SKIPPED AFTER 3 ATTEMPTS)')
        output_lines.append('FILE_NAME\tFILE_CID\tFILE_SIZE\tERROR_REASON')
        output_lines.append('----')
        output_lines.extend(results_dict['table3'])
    
    # 显示结果
    print("\n" + "\n".join(output_lines))
    
    # 如果需要保存日志
    if save_log:
        # 生成日志文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_output_path = f"check_status_{timestamp}.log"
        file_path = output_path if output_path else default_output_path
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(output_lines))
            log_info(f"结果已保存到 {file_path}")
        except Exception as e:
            log_error(f"保存日志文件失败: {e}")

def main():
    """
    脚本入口：
      用法： python3 this.py [relative_path] [--keep-path|-k] [--其他参数传递给 crustcheck]
      - 如果指定了 relative_path（必须以 "/" 开头），则使用该目录作为递归起点。
      - 如果未指定或第一个参数以 "-" 开头，则默认使用 "/"。
      - --keep-path 或 -k：保留文件的相对路径信息，如果不指定则只输出文件名。
    """
    # 并发线程数
    NUM_THREADS = 10
    
    # 在开始时打印使用的 IPFS 命令
    log_info(f"使用 IPFS 命令: {' '.join(IPFS_CMD)}")
    log_info(f"将使用 {NUM_THREADS} 个并发线程处理文件")
    
    # 根据命令行参数确定起始目录和传递给 crustcheck 的参数
    if len(sys.argv) > 1:
        if sys.argv[1].startswith("/"):
            mfs_root = sys.argv[1]
            crustcheck_args = sys.argv[2:]
        elif sys.argv[1].startswith("-"):
            mfs_root = "/"
            crustcheck_args = sys.argv[1:]
        else:
            log_error("第一个参数必须以 '/' 开头，代表 IPFS 文件的相对根目录，例如 / 或 /test123")
            sys.exit(1)
    else:
        mfs_root = "/"
        crustcheck_args = []
    
    # 检查是否需要保留路径信息
    keep_path = False
    # 从crustcheck_args中查找并移除--keep-path或-k参数
    i = 0
    while i < len(crustcheck_args):
        if crustcheck_args[i] == "--keep-path" or crustcheck_args[i] == "-k":
            keep_path = True
            crustcheck_args.pop(i)
        else:
            i += 1
            
    if keep_path:
        log_info("将保留文件路径信息")
    else:
        log_info("将只输出文件名，不包含路径")
    
    # 检查是否需要保存日志文件
    save_log = False
    output_path = None
    for i, arg in enumerate(crustcheck_args):
        if arg == "--save-log" and i+1 < len(crustcheck_args):
            if crustcheck_args[i+1].lower() == "true":
                save_log = True
        elif arg == "--out" and i+1 < len(crustcheck_args):
            output_path = crustcheck_args[i+1]
            save_log = True

    # 收集所有文件信息（添加重试逻辑）
    collected_files = []
    try:
        list_files_recursive(mfs_root, collected_files, max_retries=3)
    except Exception as e:
        log_error(f"列出文件时发生错误: {e}")
        sys.exit(1)

    # 如果没有收集到任何文件，打印警告并退出
    if not collected_files:
        log_warn(f"在路径 {mfs_root} 下没有找到任何文件")
        sys.exit(0)
    
    log_info(f"共收集了 {len(collected_files)} 个文件")
    
    # 生成临时文件前缀，基于时间戳
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 将文件分配给每个线程
    files_per_thread = math.ceil(len(collected_files) / NUM_THREADS)
    thread_files = []
    
    # 如果文件数少于NUM_THREADS，则调整线程数
    actual_threads = min(NUM_THREADS, len(collected_files))
    
    # 分配文件到各个线程
    for i in range(actual_threads):
        start_idx = i * files_per_thread
        end_idx = min((i + 1) * files_per_thread, len(collected_files))
        thread_files.append(collected_files[start_idx:end_idx])
    
    log_info(f"将 {len(collected_files)} 个文件分给 {actual_threads} 个线程处理，每个线程约 {files_per_thread} 个文件")
    
    # 创建共享结果字典
    results_dict = {
        'table1': [],
        'table2': [],
        'table3': []
    }
    
    # 设置线程池执行器
    with concurrent.futures.ThreadPoolExecutor(max_workers=actual_threads) as executor:
        # 创建每个线程的任务
        futures = []
        for i in range(actual_threads):
            thread_id = i + 1
            tmp_file_path = f"/tmp/{timestamp_str}_thread{thread_id}.log"
            
            # 提交任务到线程池
            future = executor.submit(
                run_crustcheck, 
                thread_id, 
                thread_files[i], 
                tmp_file_path, 
                crustcheck_args, 
                actual_threads,
                results_dict,
                keep_path
            )
            futures.append(future)
        
        # 显示进度条
        completed = 0
        total = len(futures)
        while completed < total:
            done_count = sum(1 for f in futures if f.done())
            if done_count > completed:
                completed = done_count
                progress = int(completed * 100 / total)
                progress_bar = f"[{'#' * (progress // 5)}{'.' * (20 - progress // 5)}] {progress}% ({completed}/{total})"
                log_info(f"进度: {progress_bar}")
            time.sleep(0.5)
        
        # 等待所有线程完成并收集结果
        results = []
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                log_error(f"线程执行过程中发生异常: {e}")
                results.append(1)  # 出错视为退出码1
    
    # 显示合并后的结果
    log_info("所有线程处理完成，显示汇总结果:")
    display_combined_results(results_dict, save_log, output_path)
    
    # 如果有任何线程失败，就返回非零退出码
    if any(code != 0 for code in results if code is not None):
        log_warn("一些线程处理失败，返回非零退出码")
        sys.exit(1)
    elif all(code == 0 for code in results):
        log_info("所有线程处理成功")
        sys.exit(0)
    else:
        # 有些线程返回了None（这意味着有异常）
        log_warn("一些线程处理过程中发生异常")
        sys.exit(1)

if __name__ == "__main__":
    main()
