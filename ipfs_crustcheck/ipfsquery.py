#!/usr/bin/env python3

import subprocess
import shlex
import sys
import os
import fcntl
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

def run_command(cmd_args):
    """
    直接调用外部命令, 返回 stdout(str)。
    cmd_args 是一个列表，例如 ["ipfs", "files", "ls", "-l", "/some/path"]。
    """
    try:
        result = subprocess.run(
            cmd_args, 
            text=True,
            capture_output=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] 调用命令失败: {' '.join(cmd_args)}", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"[ERROR] 找不到可执行文件: {cmd_args[0]} - {e}", file=sys.stderr)
        sys.exit(1)

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

def list_files_recursive(mfs_path, collected_files):
    """
    递归列出 MFS 路径下所有文件（非文件夹）。

    mfs_path: 形如 "/", "/some folder/", "/some folder/inner folder/" 等。
    collected_files: 用于存放 (文件名, CID, 大小) 的列表。

    注意：
    - 如果 mfs_path 末尾没有 '/', 则自动补上。
    """
    # 如果 mfs_path 末尾没有 '/'，则添加
    if not mfs_path.endswith("/"):
        mfs_path = mfs_path + "/"

    cmd = IPFS_CMD + ["files", "ls", "-l", mfs_path]
    output = run_command(cmd)

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
            list_files_recursive(new_path, collected_files)
        else:
            collected_files.append((name, cid, size))

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

    # 收集所有文件信息
    collected_files = []
    list_files_recursive(mfs_root, collected_files)

    # 生成临时日志文件，文件名基于时间戳
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_file_path = f"/tmp/{timestamp_str}.log"

    with open(tmp_file_path, "w", encoding="utf-8") as f:
        for (file_name, file_cid, file_size) in collected_files:
            f.write(f"{file_name}\t{file_cid}\t{file_size}\n")

    # 打开日志文件上锁，并调用 crustcheck 程序
    f_log = open(tmp_file_path, "r+")
    try:
        fcntl.flock(f_log, fcntl.LOCK_EX)

        # 组装 crustcheck 命令：添加 --input 参数和其它传入的参数
        cmd = ["crustcheck", "--input", tmp_file_path] + crustcheck_args
        print(f"[INFO] 正在调用: {' '.join(shlex.quote(x) for x in cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # 实时打印 crustcheck 的输出
        for line in process.stdout:
            print(line, end='')

        returncode = process.wait()
        print(f"[INFO] crustcheck 退出码: {returncode}")

    finally:
        fcntl.flock(f_log, fcntl.LOCK_UN)
        f_log.close()
        try:
            os.remove(tmp_file_path)
        except OSError as e:
            print(f"[WARN] 删除临时文件 {tmp_file_path} 失败: {e}", file=sys.stderr)

    sys.exit(returncode)

if __name__ == "__main__":
    main()
