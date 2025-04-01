#!/usr/bin/env python3

import subprocess
import shlex
import sys
import os
import fcntl
import time
from datetime import datetime

# 获取环境变量中的 ipfs 执行命令，并分割成列表
def get_ipfs_cmd():
    ipfs_exec = os.environ.get('ipfsexec')
    if ipfs_exec:
        # 使用 shlex.split 正确处理带空格的命令
        return shlex.split(ipfs_exec)
    return ['ipfs']  # 默认命令

# 全局变量保存 IPFS 命令
IPFS_CMD = get_ipfs_cmd()

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
            print(f"[EXEC] {''.join(cmd_args)} (尝试 {attempts}/{max_attempts})")
            result = subprocess.run(
                cmd_args, 
                text=True,
                capture_output=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            last_error = e
            print(f"[ERROR] 调用命令失败: {' '.join(cmd_args)} (尝试 {attempts}/{max_attempts})", file=sys.stderr)
            print(e.stderr, file=sys.stderr)
            
            if attempts < max_attempts:
                print(f"[INFO] {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
        except FileNotFoundError as e:
            print(f"[ERROR] 找不到可执行文件: {cmd_args[0]} - {e}", file=sys.stderr)
            sys.exit(1)
    
    # 所有重试都失败
    print(f"[ERROR] 命令 {' '.join(cmd_args)} 在 {max_attempts} 次尝试后仍然失败", file=sys.stderr)
    if last_error:
        print(last_error.stderr, file=sys.stderr)
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
        print(f"[WARN] 无法解析行: {line}")
        return None, None, None

    size_str = tokens[-1]
    cid = tokens[-2]
    name_parts = tokens[:-2]
    name = " ".join(name_parts)

    try:
        size = int(size_str)
    except ValueError:
        print(f"[WARN] 无法解析size为数字: {line}")
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
        print(f"[WARN] 无法列出目录 {mfs_path}，跳过此目录")
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
                print(f"[WARN] 跳过无效 CID 的文件: {os.path.join(mfs_path, name)}")

def main():
    """
    脚本入口：
      用法： python3 this.py [relative_path] [--其他参数传递给 crustcheck]
      - 如果指定了 relative_path（必须以 "/" 开头），则使用该目录作为递归起点。
      - 如果未指定或第一个参数以 "-" 开头，则默认使用 "/"。
    """
    # 在开始时打印使用的 IPFS 命令
    print(f"[INFO] 使用 IPFS 命令: {' '.join(IPFS_CMD)}")
    
    # 根据命令行参数确定起始目录和传递给 crustcheck 的参数
    if len(sys.argv) > 1:
        if sys.argv[1].startswith("/"):
            mfs_root = sys.argv[1]
            crustcheck_args = sys.argv[2:]
        elif sys.argv[1].startswith("-"):
            mfs_root = "/"
            crustcheck_args = sys.argv[1:]
        else:
            print("[ERROR] 第一个参数必须以 '/' 开头，代表 IPFS 文件的相对根目录，例如 / 或 /test123", file=sys.stderr)
            sys.exit(1)
    else:
        mfs_root = "/"
        crustcheck_args = []

    # 收集所有文件信息（添加重试逻辑）
    collected_files = []
    try:
        list_files_recursive(mfs_root, collected_files, max_retries=3)
    except Exception as e:
        print(f"[ERROR] 列出文件时发生错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 如果没有收集到任何文件，打印警告并退出
    if not collected_files:
        print(f"[WARN] 在路径 {mfs_root} 下没有找到任何文件")
        sys.exit(0)
    
    print(f"[INFO] 共收集了 {len(collected_files)} 个文件")

    # 生成临时日志文件，文件名基于时间戳
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_file_path = f"/tmp/{timestamp_str}.log"

    with open(tmp_file_path, "w", encoding="utf-8", errors="replace") as f:
        for (file_name, file_cid, file_size) in collected_files:
            # 确保任何文件名都是有效的 UTF-8，替换任何无法编码的字符
            try:
                safe_file_name = file_name
                safe_line = f"{safe_file_name}\t{file_cid}\t{file_size}\n"
                f.write(safe_line)
            except UnicodeEncodeError:
                # 如果有编码问题，使用 repr() 来获取一个安全的可打印表示
                safe_file_name = repr(file_name)[1:-1]  # 去掉引号
                safe_line = f"{safe_file_name}\t{file_cid}\t{file_size}\n"
                print(f"[WARN] 文件名包含特殊字符，进行转义: {safe_file_name}")
                f.write(safe_line)

    # 打开日志文件上锁，并调用 crustcheck 程序
    f_log = open(tmp_file_path, "r+")
    try:
        fcntl.flock(f_log, fcntl.LOCK_EX)

        # 组装 crustcheck 命令：添加 --input 参数和其它传入的参数
        cmd = ["crustcheck", "--input", tmp_file_path] + crustcheck_args
        print(f"[INFO] 正在调用: {' '.join(shlex.quote(x) for x in cmd)}")
        
        # 使用带有重试逻辑的方式启动 crustcheck
        max_crustcheck_attempts = 1  # crustcheck 本身已经有重试逻辑，所以这里只尝试一次
        returncode = None
        
        try:
            # 不使用 text=True，而是手动处理字节流，更安全地处理特殊字符
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,  # 使用二进制模式
                bufsize=1
            )

            # 实时打印 crustcheck 的输出，使用 errors='replace' 来处理无法解码的字符
            for line_bytes in process.stdout:
                try:
                    line = line_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    # 对于无法解码的部分，使用替代字符
                    line = line_bytes.decode('utf-8', errors='replace')
                print(line, end='')

            returncode = process.wait()
            print(f"[INFO] crustcheck 退出码: {returncode}")
        except Exception as e:
            print(f"[ERROR] 执行 crustcheck 出错: {e}", file=sys.stderr)
            returncode = 1

    finally:
        fcntl.flock(f_log, fcntl.LOCK_UN)
        f_log.close()
        try:
            os.remove(tmp_file_path)
        except OSError as e:
            print(f"[WARN] 删除临时文件 {tmp_file_path} 失败: {e}", file=sys.stderr)

    sys.exit(returncode if returncode is not None else 1)

if __name__ == "__main__":
    main()
