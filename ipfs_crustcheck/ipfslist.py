#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import posixpath
import sys

def list_ipfs_directory(path):
    """
    调用 ipfs 命令列出指定目录下的文件和文件夹信息，
    返回输出的每一行组成的列表。
    """
    cmd = ["ipfs", "files", "ls", "-l", path]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, check=True)
        output = result.stdout.strip()
        if output:
            return output.splitlines()
        else:
            return []
    except subprocess.CalledProcessError as e:
        print(f"执行命令 {cmd} 时出错: {e}", file=sys.stderr)
        return []

def parse_listing_line(line):
    """
    解析 ipfs 命令输出的每一行数据，利用 rsplit 从右侧分割成三部分：
      - 最右侧部分为文件大小（阿拉伯数字）
      - 中间部分为 cid（由英文字母和数字组成）
      - 剩余部分为文件或文件夹名称
    返回 (name, cid, size) 三元组，若解析出错则返回 None。
    """
    try:
        name, cid, size_str = line.rsplit(None, 2)
        size = int(size_str)
        return name, cid, size
    except ValueError:
        print(f"解析行时出错: {line}", file=sys.stderr)
        return None

def recursive_parse(path, file_list, folder_list):
    """
    递归查询指定 path 下的内容：
      - 当检测到名称以 "/" 结尾时，认为这是一个文件夹，
        保存时去掉末尾的 "/"（仅保留文件夹名称，不含路径），
        同时构造完整路径用于递归调用。
      - 否则认为是文件，直接保存 ipfs 输出的文件名（已经为当前目录下的名称）。
    """
    lines = list_ipfs_directory(path)
    for line in lines:
        parsed = parse_listing_line(line)
        if parsed is None:
            continue
        name, cid, size = parsed

        if name.endswith("/"):
            # 构造完整路径以便递归调用 ipfs 命令
            full_path = posixpath.join(path, name) if path != "/" else "/" + name
            # 仅保存文件夹名称：去掉末尾的 "/" 后即为名称，不包含路径
            folder_name = name.rstrip("/")
            folder_list.append((folder_name, cid, size))
            recursive_parse(full_path, file_list, folder_list)
        else:
            file_list.append((name, cid, size))

def main():
    # 支持用户传入起始 IPFS 路径，默认为 "/"
    if len(sys.argv) > 1:
        start_path = sys.argv[1]
    else:
        start_path = "/"
        
    file_list = []
    folder_list = []
    
    # 从用户指定的起始路径开始递归查询
    recursive_parse(start_path, file_list, folder_list)
    
    print(f"Starting from IPFS path: {start_path}")
    print("===File Cid Table===")
    for filename, cid, size in file_list:
        print(f"{filename} {cid} {size}")
    
    print("\n===Folder Cid Table===")
    for folder_name, cid, size in folder_list:
        print(f"{folder_name} {cid} {size}")

if __name__ == '__main__':
    main()
