#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import subprocess
import os
import sys
import re
import json
import locale
from typing import List, Dict, Tuple, Set, Optional
from pathlib import Path

# 在Windows系统上设置UTF-8编码
if os.name == 'nt':
    try:
        # 尝试设置控制台代码页为UTF-8 (65001)
        os.system('chcp 65001 > nul')
        # 尝试设置环境变量
        os.environ['PYTHONIOENCODING'] = 'utf-8'
    except Exception as e:
        print(f"警告: 无法设置Windows控制台为UTF-8: {e}")
        print("某些非ASCII字符可能无法正确显示")

# 获取系统默认编码
system_encoding = locale.getpreferredencoding()

def parse_size(size_str: str) -> int:
    """将人类可读的大小格式 (如 1GB, 10MB) 转换为字节数"""
    units = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT]?B)$', size_str, re.IGNORECASE)
    if not match:
        raise ValueError(f"无效的大小格式: {size_str}")
    num, unit = match.groups()
    return int(float(num) * units[unit.upper()])

def format_size(size_bytes: int) -> str:
    """将字节数格式化为人类可读的大小格式"""
    if size_bytes < 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0 or unit == 'TB':
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0

def run_rclone_command(cmd: List[str]) -> str:
    """运行rclone命令并返回输出，处理编码问题"""
    try:
        print(f"执行命令: {' '.join(cmd)}")
        
        # 在Windows上特殊处理，捕获输出时设置编码和错误处理
        if os.name == 'nt':
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding='utf-8',
                errors='ignore'  # 忽略无法解码的字符
            )
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                print(f"运行命令出错: {' '.join(cmd)}")
                print(f"错误信息: {stderr}")
                sys.exit(1)
                
            return stdout
        else:
            # 非Windows系统使用标准方法
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"运行命令出错: {' '.join(cmd)}")
        print(f"错误信息: {e.stderr}")
        sys.exit(1)
    except Exception as e:
        print(f"执行命令时发生未知错误: {e}")
        sys.exit(1)

def get_rclone_executable() -> str:
    """获取rclone可执行文件的路径"""
    # 首先检查是否在PATH中
    if os.name == 'nt':  # Windows
        try:
            result = subprocess.run(["where", "rclone"], check=True, capture_output=True, text=True)
            return "rclone"
        except subprocess.CalledProcessError:
            # 检查当前目录下是否有rclone.exe
            if os.path.exists("rclone.exe"):
                return os.path.abspath("rclone.exe")
    else:  # Linux/Unix
        try:
            result = subprocess.run(["which", "rclone"], check=True, capture_output=True, text=True)
            return "rclone"
        except subprocess.CalledProcessError:
            # 检查当前目录下是否有rclone
            if os.path.exists("rclone"):
                return os.path.abspath("rclone")
    
    # 如果都没有找到，返回默认值并发出警告
    print("警告: 未在PATH或当前目录中找到rclone，假设它可以直接调用'rclone'")
    return "rclone"

def list_remote_contents(rclone_exec: str, remote_path: str, max_depth: int) -> Dict[str, bool]:
    """列出远程路径中的文件和目录，最多递归到指定深度"""
    paths = {}
    processed_dirs = set()  # 用于跟踪已处理的目录，避免重复处理
    
    # 从remote_path中分离基础路径和远程名称
    if ':' in remote_path:
        remote_name, base_path = remote_path.split(':', 1)
        remote_prefix = remote_name + ':'
    else:
        base_path = remote_path
        remote_prefix = ""
    
    # 递归辅助函数，用于遍历目录结构
    def traverse_dir(current_path: str, relative_path: str = "", current_depth: int = 1):
        if current_depth > max_depth or current_path in processed_dirs:
            return
            
        processed_dirs.add(current_path)
        print(f"遍历目录 [深度 {current_depth}/{max_depth}]: {current_path}")
        
        # 一次性获取目录和文件，减少rclone调用次数
        # 列出所有目录
        cmd = [rclone_exec, "lsf", "--dirs-only", current_path]
        dirs_output = run_rclone_command(cmd)
        
        # 列出所有文件
        cmd = [rclone_exec, "lsf", "--files-only", current_path]
        files_output = run_rclone_command(cmd)
        
        # 处理目录
        for dir_name in dirs_output.splitlines():
            if not dir_name:
                continue
                
            dir_relative_path = f"{relative_path}/{dir_name}" if relative_path else dir_name
            paths[dir_relative_path] = True  # True表示是目录
            
            # 如果未达到最大深度，则递归处理子目录
            if current_depth < max_depth:
                next_path = f"{current_path}/{dir_name}"
                traverse_dir(next_path, dir_relative_path, current_depth + 1)
        
        # 处理文件
        for file_name in files_output.splitlines():
            if not file_name:
                continue
                
            file_relative_path = f"{relative_path}/{file_name}" if relative_path else file_name
            paths[file_relative_path] = False  # False表示是文件
    
    # 开始递归
    traverse_dir(remote_path)
    
    # 返回结果，保持路径的相对性（不包含远程名称）
    return paths

def get_depth(path: str) -> int:
    """计算路径的深度"""
    # 分割路径并计算部分的数量
    # 排除空部分(来自于前导/尾随斜杠)
    return len([p for p in path.strip('/').split('/') if p])

def get_parent_at_depth(path: str, depth: int) -> str:
    """获取指定深度的父路径"""
    segments = [p for p in path.strip('/').split('/') if p]
    if len(segments) <= depth:
        return path
    return '/'.join(segments[:depth])

def group_items_by_depth(items: Dict[str, bool]) -> Dict[int, List[Tuple[str, bool]]]:
    """按深度对项目进行分组"""
    result = {}
    for item, is_dir in items.items():
        depth = get_depth(item)
        if depth not in result:
            result[depth] = []
        result[depth].append((item, is_dir))
    return result

def get_consolidated_paths(items_by_depth: Dict[int, List[Tuple[str, bool]]], target_depth: int) -> Set[str]:
    """根据目标深度整合路径，优化版本"""
    if not items_by_depth:
        return set()
        
    max_depth = max(items_by_depth.keys())
    
    # 如果没有达到目标深度的项目，就回退到最大可用深度
    effective_depth = min(target_depth, max_depth)
    if target_depth > max_depth:
        print(f"警告: 请求的深度{target_depth}超过了最大可用深度{max_depth}，使用深度1")
        effective_depth = 1  # 根据示例，此时应该回退到深度1
    
    consolidated = set()
    covered_items = set()  # 跟踪已被覆盖的项目
    
    # 创建一个项目到其所有深度路径的映射，用于快速查找
    item_paths = {}
    for depth, items in items_by_depth.items():
        for item, is_dir in items:
            item_paths[item] = item
    
    # 首先处理目标深度的项目
    if effective_depth in items_by_depth:
        print(f"处理深度 {effective_depth} 的项目...")
        for item, is_dir in items_by_depth[effective_depth]:
            if item in covered_items:
                continue
                
            parent = get_parent_at_depth(item, effective_depth)
            consolidated.add(parent)
            
            # 标记所有被这个父路径覆盖的项目
            # 使用更高效的方法来确定被覆盖的项目
            parent_prefix = parent + '/'
            for other_item in item_paths:
                if other_item == parent or other_item.startswith(parent_prefix):
                    covered_items.add(other_item)
    
    # 处理较低深度且尚未被覆盖的项目
    for depth in range(1, effective_depth):
        if depth in items_by_depth:
            print(f"处理深度 {depth} 的项目...")
            for item, is_dir in items_by_depth[depth]:
                if item in covered_items:
                    continue
                    
                consolidated.add(item)
                
                # 标记所有被此项目覆盖的内容
                item_prefix = item + '/'
                for other_item in item_paths:
                    if other_item == item or other_item.startswith(item_prefix):
                        covered_items.add(other_item)
    
    return consolidated

def calculate_size(rclone_exec: str, path: str) -> Tuple[str, int]:
    """使用rclone size计算路径的大小"""
    cmd = [rclone_exec, "size", path, "--json"]
    output = run_rclone_command(cmd)
    try:
        result = json.loads(output)
        return path, result.get("bytes", 0)
    except json.JSONDecodeError:
        print(f"解析路径的JSON输出时出错: {path}")
        return path, 0

def calculate_sizes(rclone_exec: str, paths: Set[str], full_remote_path: str, remote_base: str) -> Dict[str, int]:
    """计算每个路径的大小，确保使用完整的远程路径"""
    results = {}
    total_paths = len(paths)
    
    # 从完整远程路径中分离远程名称和路径
    if ':' in full_remote_path:
        remote_name, base_path = full_remote_path.split(':', 1)
        remote_prefix = remote_name + ':'
    else:
        base_path = full_remote_path
        remote_prefix = ""
    
    # 确保base_path以/结尾
    if base_path and not base_path.endswith('/'):
        base_path += '/'
    
    for i, path in enumerate(paths, 1):
        # 构建完整路径，确保包含远程名称和基本路径
        if ':' in path:  # 路径已包含远程名称
            full_path = path
        else:
            if path.startswith('/'):
                path = path[1:]  # 移除前导斜杠
            
            if base_path and not path.startswith(base_path):
                full_path = f"{remote_prefix}{base_path}{path}"
            else:
                full_path = f"{remote_prefix}{path}"
        
        print(f"计算大小 [{i}/{total_paths}]: {full_path}")
        path_result, size = calculate_size(rclone_exec, full_path)
        results[full_path] = size
    return results

def group_by_part_size(items: Dict[str, int], part_size: int) -> List[List[Tuple[str, int]]]:
    """将项目分组，使每组的总大小最接近指定的部分大小"""
    # 按大小对项目进行排序(从大到小)
    sorted_items = sorted(items.items(), key=lambda x: x[1], reverse=True)
    
    # 使用贪心算法进行分箱打包
    parts = []
    remaining_items = list(sorted_items)
    
    # 处理太大的单个项目
    large_items = [item for item in remaining_items if item[1] > part_size]
    for item in large_items:
        parts.append([item])
        remaining_items.remove(item)
    
    # 尝试找到最佳组合以接近part_size
    while remaining_items:
        best_combo = find_best_combination(remaining_items, part_size)
        if not best_combo:
            # 如果找不到组合，就把剩下的项目都放在最后一个部分
            parts.append(remaining_items)
            break
        
        parts.append(best_combo)
        for item in best_combo:
            remaining_items.remove(item)
    
    return parts

def find_best_combination(items: List[Tuple[str, int]], target_size: int) -> List[Tuple[str, int]]:
    """找到总和最接近但不超过目标大小的项目组合"""
    if not items:
        return []
    
    # 如果只有一个项目，且它小于目标大小，则返回它
    if len(items) == 1 and items[0][1] <= target_size:
        return [items[0]]
    
    # 尝试从剩余项目中找到最佳组合
    best_combo = []
    best_size = 0
    
    # 尝试将第一个项目与其他项目组合
    first_item = items[0]
    if first_item[1] <= target_size:
        best_combo = [first_item]
        best_size = first_item[1]
    
    # 尝试其他组合
    for i in range(1, len(items) + 1):
        for j in range(i + 1, len(items) + 1):
            combo = items[i-1:j]
            combo_size = sum(item[1] for item in combo)
            
            if combo_size <= target_size and combo_size > best_size:
                best_combo = combo
                best_size = combo_size
    
    return best_combo

def main():
    parser = argparse.ArgumentParser(description="使用rclone分析远程目录结构")
    parser.add_argument("remote_path", help="要分析的远程路径 (例如, 'remoteName:/remote/Path')")
    parser.add_argument("--depth", type=int, required=True, help="递归深度")
    parser.add_argument("--out", required=True, help="输出日志文件的路径")
    parser.add_argument("--part-size", help="分组的部分大小 (例如, '1GB', '10MB')")
    parser.add_argument("--encoding", default="utf-8", help="输出文件编码，默认为utf-8")
    
    args = parser.parse_args()
    
    # 检查remote_path格式
    if ':' not in args.remote_path:
        print("错误: remote_path必须包含冒号，格式为'remoteName:/remote/Path'")
        sys.exit(1)
    
    # 分离远程名称和路径
    remote_base, remote_path = args.remote_path.split(':', 1)
    remote_base += ':'
    
    # 获取rclone可执行文件
    rclone_exec = get_rclone_executable()
    print(f"使用rclone: {rclone_exec}")
    
    # 递归列出内容，只遍历到指定深度
    print(f"正在列出{args.remote_path}的内容（最大深度：{args.depth}）...")
    items = list_remote_contents(rclone_exec, args.remote_path, args.depth)
    
    if not items:
        print(f"警告: 在{args.remote_path}未找到内容")
    
    # 按深度对项目分组
    items_by_depth = group_items_by_depth(items)
    
    # 根据深度整合项目
    consolidated_paths = get_consolidated_paths(items_by_depth, args.depth)
    
    # 计算大小，保留完整远程路径
    print(f"正在计算{len(consolidated_paths)}个路径的大小...")
    # 保存原始远程路径用于构建完整路径
    full_remote_path = args.remote_path
    sizes = calculate_sizes(rclone_exec, consolidated_paths, full_remote_path, remote_base)
    
    # 将结果输出到控制台和日志文件
    output_lines = []
    output_lines.append(f"深度{args.depth}的{args.remote_path}的大小计算:")
    
    for path, size in sorted(sizes.items()):
        formatted_size = format_size(size)
        output_line = f"{path}: {formatted_size}"
        output_lines.append(output_line)
        try:
            print(output_line)
        except UnicodeEncodeError:
            # 如果控制台无法显示某些字符，使用替换模式
            print(f"{path}: {formatted_size}".encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding))
    
    # 如果指定了part-size，对项目进行分组
    if args.part_size:
        try:
            part_size_bytes = parse_size(args.part_size)
            print(f"\n按部分大小分组: {args.part_size} ({format_size(part_size_bytes)})")
            
            groups = group_by_part_size(sizes, part_size_bytes)
            
            output_lines.append("\n部分分组:")
            for i, group in enumerate(groups, 1):
                total_size = sum(size for _, size in group)
                output_lines.append(f"\n---Part{i:02d}--- (总计: {format_size(total_size)})")
                for path, _ in group:
                    output_lines.append(path)
                    try:
                        print(path)
                    except UnicodeEncodeError:
                        print(path.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding))
        except ValueError as e:
            print(f"错误: {e}")
            print("忽略part-size参数并继续...")
    
    # 写入输出文件
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(output_path, 'w', encoding=args.encoding, errors='ignore') as f:
            f.write('\n'.join(output_lines))
    except Exception as e:
        print(f"写入输出文件时出错: {e}")
        print(f"尝试使用系统默认编码...")
        with open(output_path, 'w', encoding=system_encoding, errors='ignore') as f:
            f.write('\n'.join(output_lines))
    
    print(f"\n输出已保存到 {args.out}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"程序执行出错: {e}")
        if os.name == 'nt':
            print("提示: 如果错误与字符编码有关，请尝试在PowerShell中使用以下命令后再运行脚本:")
            print("$OutputEncoding = [System.Text.Encoding]::UTF8")
            print("或在CMD中使用: chcp 65001")
        sys.exit(1)
