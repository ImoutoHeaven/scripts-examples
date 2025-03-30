#!/usr/bin/env python3

import sys
import re
import subprocess
import os
import shlex

# 获取环境变量中的 ipfs 执行命令，并分割成列表
def get_ipfs_cmd():
    ipfs_exec = os.environ.get('ipfsexec')
    if ipfs_exec:
        # 使用 shlex.split 正确处理带空格的命令
        return shlex.split(ipfs_exec)
    return ['ipfs']  # 默认命令

def parse_line(line):
    line = line.rstrip()
    # 从右向左匹配阿拉伯数字字符串, 作为FILE_SIZE_IN_BYTES
    size_match = re.search(r'(\d+)$', line)
    if not size_match:
        return None
    FILE_SIZE_IN_BYTES = size_match.group(1)
    line = line[:size_match.start()]
    line = line.rstrip()
    # 匹配大小写英文字符+数字格式的字符串, 作为FILE_CID
    cid_match = re.search(r'([A-Za-z0-9]+)$', line)
    if not cid_match:
        return None
    FILE_CID = cid_match.group(1)
    line = line[:cid_match.start()]
    line = line.rstrip()
    # 检查并删除末尾的"/"
    if line.endswith('/'):
        line = line[:-1]
    # 剩下的内容作为FILE_NAME
    FILE_NAME = line.strip()
    return FILE_NAME, FILE_CID, FILE_SIZE_IN_BYTES

def main():
    ipfs_cmd = get_ipfs_cmd()
    print(f"使用 IPFS 命令: {' '.join(ipfs_cmd)}")
    
    print("请输入每行数据，格式为：<FILE_NAME FILE_CID FILE_SIZE_IN_BYTES>")
    print("一行一个，输入完毕后按 Ctrl+D 开始执行。")

    try:
        # 交互式用户输入
        lines = sys.stdin.read().splitlines()
    except KeyboardInterrupt:
        return
    
    try:
        for line in lines:
            if not line.strip():
                continue  # 跳过空行
            result = parse_line(line)
            if result is None:
                print(f"无法解析行: {line}", file=sys.stderr)
                continue
            FILE_NAME, FILE_CID, FILE_SIZE_IN_BYTES = result
            print(f"正在删除文件：/{FILE_NAME}")
            subprocess.run(ipfs_cmd + ["files", "rm", "-r", f"/{FILE_NAME}"])
            print(f"正在取消固定 CID：{FILE_CID}")
            subprocess.run(ipfs_cmd + ["pin", "rm", FILE_CID])
        print("操作完成。")
    except FileNotFoundError as e:
        print(f"找不到可执行文件: {ipfs_cmd[0]} - {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
