#!/usr/bin/env python3

import subprocess
import shlex
import sys
import os
import fcntl
import time
from datetime import datetime

def run_command(cmd_args):
    """
    直接调用外部命令, 返回 stdout(str).
    cmd_args 是一个 列表/数组, 例如 ["ipfs", "files", "ls", "-l", "/some/path"].
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

def parse_ipfs_ls_line(line):
    """
    对一行, 形如:
      2025-01-12 IPFS/	bafybeidi2vknaeciqi5oknimdxyjmmugwgrxpdblffsbbcyfnh2cfsqyom	0
    拆分出 name, cid, size
    """
    line = line.rstrip('\n')
    tokens = line.split()  # split(None) 表示按任何空白分割
    if len(tokens) < 3:
        print(f"[WARN] 无法解析行: {line}")
        return None, None, None

    # 最后一个元素 => size
    size_str = tokens[-1]
    # 倒数第二 => cid
    cid = tokens[-2]
    # 其余的全部归并到 name
    name_parts = tokens[:-2]
    # 用空格拼回去
    name = " ".join(name_parts)

    # 尝试转换为 int
    try:
        size = int(size_str)
    except ValueError:
        print(f"[WARN] 无法解析size为数字: {line}")
        return None, None, None

    return name, cid, size


def list_files_recursive(mfs_path, collected_files):
    """
    递归列出 MFS 路径下所有文件(非文件夹).

    mfs_path: 形如 "/", "/some folder/", "/some folder/inner folder/" 等
    collected_files: 用于存放 (file_name, file_cid, file_size) 的列表

    注意:
    - 如果 mfs_path 末尾没有 '/', 需要拼上, 以便 "ipfs files ls -l /xxxx"
    - 对含空格的 mfs_path, 调用前需要 shlex.quote() 或其他方式做安全处理
    """
    cmd = ["ipfs", "files", "ls", "-l", mfs_path]
    output = run_command(cmd)

    for line in output.splitlines():
        if not line.strip():
            continue
        name, cid, size = parse_ipfs_ls_line(line)
        if name is None:
            # 无法解析行，跳过
            continue

        # name 这里可能已经包含结尾的 '/', 例如 "2025-01-12 IPFS/"
        if name.endswith("/"):
            # 说明是一个文件夹 => 递归列出其子文件
            folder_name = name  # 带 '/'
            # 拼接成新的 MFS 路径
            # 假设当前 mfs_path = "/"
            #       folder_name = "2025-01-12 IPFS/"
            # 那么新的子路径: "/2025-01-12 IPFS/" (可能有多级)
            new_path = os.path.join(mfs_path, folder_name)
            # 如果 mfs_path 已经是 "/"，os.path.join 可能会给出类似 "/./folder/"，
            # 这里做一个简单的 cleanup
            new_path = new_path.replace("//", "/")
            # 递归
            list_files_recursive(new_path, collected_files)
        else:
            # 说明是文件
            # 收集到 collected_files
            collected_files.append((name, cid, size))


def main():
    # -------------------------------------------------------------------------
    # 1. 先获取 "ipfs files ls -l /" 的列表(或者你要的具体某个根目录)
    #    并递归遍历全部子文件夹, 收集所有文件信息
    # -------------------------------------------------------------------------
    collected_files = []
    list_files_recursive("/", collected_files)

    # -------------------------------------------------------------------------
    # 2. 将 stdout 输出的所有 file list 存到 /tmp/<timestamp>.log 文件
    #    这里用一个简单的时间戳来区分
    # -------------------------------------------------------------------------
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_file_path = f"/tmp/{timestamp_str}.log"

    # 注意：务必用 "utf-8" 等编码写入
    with open(tmp_file_path, "w", encoding="utf-8") as f:
        for (file_name, file_cid, file_size) in collected_files:
            # 根据需求, 一行写成: <file name> <file cid> <file size>
            # 如果 file_name 有空格/特殊字符, 可以做一次 shlex.quote():
            # file_name_quoted = shlex.quote(file_name)
            # 不过 crustcheck 本身可能需要指定格式，这里仅示例
            # 也可根据 crustcheck 的要求写 CSV 或其他格式
            f.write(f"{file_name}\t{file_cid}\t{file_size}\n")

    # -------------------------------------------------------------------------
    # 3. 给该文件上锁, 并调用 crustcheck --input /tmp/<timestamp>.log --<other arguments>
    #
    #   (3.1) 这里仅示例如何将命令行剩下的参数原封不动地传入 crustcheck.
    #          比如脚本执行方式: python3 script.py --some-arg1 --some-arg2
    #          则 sys.argv[1:] 就是 ["--some-arg1","--some-arg2"]
    # -------------------------------------------------------------------------
    #    (3.2) 需要对 crustcheck 的 stdout/stderr 做实时捕捉并打印
    #
    #    (3.3) crustcheck 退出后, 释放文件锁, 删除临时文件
    # -------------------------------------------------------------------------

    # 打开我们刚写完的日志文件, 上排他锁
    f_log = open(tmp_file_path, "r+")
    try:
        fcntl.flock(f_log, fcntl.LOCK_EX)  # 给文件上排他锁

        # 组装命令行: crustcheck --input tmp_file_path + 其他传参
        # 例如: crustcheck --input /tmp/xxx.log --some-arg1 --some-arg2
        other_args = sys.argv[1:]  # 假设用户把 crustcheck 所需的所有其他参数都放在脚本命令行后面
        cmd = ["crustcheck", "--input", tmp_file_path] + other_args

        print(f"[INFO] 正在调用: {' '.join(shlex.quote(x) for x in cmd)}")
        # 启动子进程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1  # 行缓冲
        )

        # 实时打印 crustcheck 输出
        for line in process.stdout:
            # 这里可以再做必要的处理或日志记录
            print(line, end='')

        # 等子进程退出
        returncode = process.wait()
        print(f"[INFO] crustcheck 退出码: {returncode}")

    finally:
        # 解锁
        fcntl.flock(f_log, fcntl.LOCK_UN)
        f_log.close()

        # 删除临时文件
        try:
            os.remove(tmp_file_path)
        except OSError as e:
            print(f"[WARN] 删除临时文件 {tmp_file_path} 失败: {e}", file=sys.stderr)

    # 退出脚本
    sys.exit(returncode)


if __name__ == "__main__":
    main()
