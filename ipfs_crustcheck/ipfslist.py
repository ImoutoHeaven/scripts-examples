#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import posixpath
import sys

def list_ipfs_directory(path):
    """
    调用 ipfs 命令列出指定目录下的文件和文件夹信息，返回输出的每一行（列表）。
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
    解析 ipfs 命令输出的每一行内容。
    利用从右向左切分的方法（rsplit），切分成三个部分：
      - 最右侧部分为文件大小（数字）
      - 中间部分为 cid（英文字母和数字组成）
      - 剩余部分为文件或文件夹名称
    返回 (name, cid, size) 三元组。
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
      - 对于文件，只保存文件名（不含路径）。
      - 对于文件夹，保存时只保留文件夹的名称（去掉末尾的 "/"，且不包含路径）。
    同时需要构造完整路径用于递归调用 ipfs 命令。
    """
    lines = list_ipfs_directory(path)
    for line in lines:
        parsed = parse_listing_line(line)
        if parsed is None:
            continue
        name, cid, size = parsed

        if name.endswith("/"):
            # 计算完整路径用于递归调用
            full_path = posixpath.join(path, name) if path != "/" else "/" + name
            # 对于文件夹，仅保存其名称，去掉末尾的 "/"
            folder_name = name.rstrip("/")
            folder_list.append((folder_name, cid, size))
            recursive_parse(full_path, file_list, folder_list)
        else:
            # 对于文件，只保存文件名（name 由 ipfs 输出时已为当前目录下的文件名）
            file_list.append((name, cid, size))

def main():
    file_list = []
    folder_list = []
    
    # 从根目录开始递归查询
    recursive_parse("/", file_list, folder_list)
    
    # 输出文件 CID 表（只显示文件名、cid、文件大小）
    print("===File Cid Table===")
    for filename, cid, size in file_list:
        print(f"{filename} {cid} {size}")
    
    # 输出文件夹 CID 表（只显示文件夹名称，不包含路径和末尾的 "/"）
    print("\n===Folder Cid Table===")
    for folder_name, cid, size in folder_list:
        print(f"{folder_name} {cid} {size}")

if __name__ == '__main__':
    main()
