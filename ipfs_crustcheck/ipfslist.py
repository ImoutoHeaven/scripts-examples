#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import posixpath
import sys
import argparse
import os
import shlex

# 获取环境变量中的 ipfs 执行命令，并分割成列表
def get_ipfs_cmd():
    ipfs_exec = os.environ.get('ipfsexec')
    if ipfs_exec:
        # 使用 shlex.split 正确处理带空格的命令
        return shlex.split(ipfs_exec)
    return ['ipfs']  # 默认命令

def list_ipfs_directory(path):
    """
    调用 ipfs 命令列出指定目录下的文件和文件夹信息，
    返回输出的每一行组成的列表。
    """
    # 获取基础命令列表
    cmd = get_ipfs_cmd() + ["files", "ls", "-l", path]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, check=True)
        output = result.stdout.strip()
        if output:
            return output.splitlines()
        else:
            return []
    except subprocess.CalledProcessError as e:
        print(f"执行命令 {' '.join(cmd)} 时出错: {e}", file=sys.stderr)
        return []
    except FileNotFoundError as e:
        print(f"找不到可执行文件: {cmd[0]} - {e}", file=sys.stderr)
        sys.exit(1)

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

def recursive_parse(ipfs_path, current_rel, file_list, folder_list):
    """
    递归查询指定 ipfs_path 下的内容，同时记录相对于起始路径的相对路径 current_rel：
      - 当检测到名称以 "/" 结尾时，认为这是一个文件夹，
        保存时存储相对于起始路径的相对路径，
        同时构造完整路径用于递归调用。
      - 否则认为是文件，直接保存相对于起始路径的相对路径。
    """
    lines = list_ipfs_directory(ipfs_path)
    for line in lines:
        parsed = parse_listing_line(line)
        if parsed is None:
            continue
        name, cid, size = parsed

        if name.endswith("/"):
            folder_name = name.rstrip("/")
            # 计算该文件夹相对于起始路径的相对路径
            new_rel = posixpath.join(current_rel, folder_name) if current_rel else folder_name
            folder_list.append((new_rel, cid, size))
            # 构造完整路径以便递归调用 ipfs 命令
            full_path = posixpath.join(ipfs_path, name) if ipfs_path != "/" else "/" + name
            recursive_parse(full_path, new_rel, file_list, folder_list)
        else:
            # 计算文件相对于起始路径的相对路径
            rel_path = posixpath.join(current_rel, name) if current_rel else name
            file_list.append((rel_path, cid, size))

def main():
    ipfs_cmd = get_ipfs_cmd()
    print(f"使用 IPFS 命令: {' '.join(ipfs_cmd)}")
    
    parser = argparse.ArgumentParser(description='IPFS 目录递归查询并显示文件和文件夹的 CID 表')
    parser.add_argument('start_path', nargs='?', default='/', help='起始 IPFS 路径，默认 "/"')
    parser.add_argument('--show-mode', choices=['filename', 'relativepath'], default='filename',
                        help='显示模式: "filename" 表示仅显示文件名，"relativepath" 表示显示相对于起始路径的相对路径')
    args = parser.parse_args()

    start_path = args.start_path
    show_mode = args.show_mode

    file_list = []
    folder_list = []

    # 从用户指定的起始路径开始递归查询，初始相对路径为空
    recursive_parse(start_path, "", file_list, folder_list)

    print(f"Starting from IPFS path: {start_path}")
    print("===File Cid Table===")
    for rel_path, cid, size in file_list:
        # 根据显示模式选择展示内容
        display_name = posixpath.basename(rel_path) if show_mode == 'filename' else rel_path
        print(f"{display_name} {cid} {size}")

    print("\n===Folder Cid Table===")
    for rel_path, cid, size in folder_list:
        display_name = posixpath.basename(rel_path) if show_mode == 'filename' else rel_path
        print(f"{display_name} {cid} {size}")

if __name__ == '__main__':
    main()
