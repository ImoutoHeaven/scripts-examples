#!/usr/bin/env python3
"""
Advanced Decompressor Script - Enhanced Version
Supports Windows 10/Debian 12 platforms
Recursively scans and extracts various archive formats including SFX files
Fixed Unicode handling for all subprocess operations
Added Windows short path API support, script locking, and new decompress policies
"""

import os
import sys
import re
import struct
import subprocess
import argparse
import shutil
import time
import threading
import uuid
import glob
import socket
import platform
import random
import signal
import atexit
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Union, Tuple

# Global verbose flag
VERBOSE = False


# === 传统zip编码检测实现 ===
def is_traditional_zip(archive_path):
    """
    检查ZIP文件是否使用传统编码（非UTF-8）
    
    Args:
        archive_path: ZIP文件路径
        
    Returns:
        bool: 如果是传统编码ZIP返回True，否则返回False
    """
    try:
        if not archive_path.lower().endswith('.zip'):
            return False  # 只检查ZIP文件
            
        if VERBOSE:
            print(f"  DEBUG: 检查ZIP是否为传统编码: {archive_path}")
            
        with open(archive_path, 'rb') as f:
            # 读取本地文件头
            while True:
                header = f.read(30)
                if len(header) < 30:
                    break
                    
                # 检查PK签名
                if header[0:4] != b'PK\x03\x04':
                    break
                    
                # 通用目的位标志在字节6-7
                gpbf = int.from_bytes(header[6:8], 'little')
                
                # 位11表示UTF-8编码
                is_utf8 = (gpbf & (1 << 11)) != 0
                if is_utf8:
                    if VERBOSE:
                        print(f"  DEBUG: 发现UTF-8编码，非传统ZIP")
                    return False  # 它是UTF-8编码的
                    
                # 跳过文件名和额外字段
                filename_length = int.from_bytes(header[26:28], 'little')
                extra_field_length = int.from_bytes(header[28:30], 'little')
                f.seek(filename_length + extra_field_length, 1)  # 使用os.SEEK_CUR的值1
                
            if VERBOSE:
                print(f"  DEBUG: 未发现UTF-8标志，认为是传统ZIP")
            return True  # 未找到UTF-8标志，假设为传统ZIP
            
    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: 读取ZIP文件时出错 '{archive_path}': {e}")
        return False



# === depth 限制 实现 ====

def parse_depth_range(depth_range_str):
    """
    解析深度范围字符串
    
    Args:
        depth_range_str: 深度范围字符串，格式为 "int1-int2" 或 "int"
        
    Returns:
        tuple: (min_depth, max_depth) 或 None（如果解析失败）
        
    Raises:
        ValueError: 如果格式无效或深度值无效
    """
    if not depth_range_str:
        return None
        
    depth_range_str = depth_range_str.strip()
    
    if VERBOSE:
        print(f"  DEBUG: 解析深度范围: {depth_range_str}")
    
    try:
        if '-' in depth_range_str:
            # 格式: "int1-int2"
            parts = depth_range_str.split('-')
            if len(parts) != 2:
                raise ValueError(f"Invalid depth range format: {depth_range_str}")
                
            min_depth = int(parts[0].strip())
            max_depth = int(parts[1].strip())
            
            if min_depth < 0 or max_depth < 0:
                raise ValueError(f"Depth values must be non-negative: {depth_range_str}")
                
            if min_depth > max_depth:
                raise ValueError(f"Min depth must be <= max depth: {depth_range_str}")
                
            if VERBOSE:
                print(f"  DEBUG: 解析范围 {min_depth}-{max_depth}")
                
            return (min_depth, max_depth)
        else:
            # 格式: "int"
            depth = int(depth_range_str)
            if depth < 0:
                raise ValueError(f"Depth value must be non-negative: {depth_range_str}")
                
            if VERBOSE:
                print(f"  DEBUG: 解析单一深度 {depth}")
                
            return (depth, depth)
            
    except ValueError as e:
        if VERBOSE:
            print(f"  DEBUG: 深度范围解析失败: {e}")
        raise
        


# ==== 解压filter实现 ====
def is_zip_multi_volume(zip_path):
    """
    判断ZIP文件是否为分卷压缩的一部分
    检查同目录下是否存在对应的.z01, .z02等文件

    Args:
        zip_path: ZIP文件路径

    Returns:
        bool: 如果是分卷ZIP返回True，否则返回False
    """
    if not zip_path.lower().endswith('.zip'):
        return False

    base_dir = os.path.dirname(zip_path)
    base_name = os.path.splitext(os.path.basename(zip_path))[0]

    if VERBOSE:
        print(f"  DEBUG: 检查ZIP是否为分卷: {zip_path}")

    # 查找.z01, .z02等文件
    try:
        for filename in os.listdir(base_dir):
            filename_lower = filename.lower()
            expected_pattern = f"{base_name.lower()}.z"
            if filename_lower.startswith(expected_pattern) and re.search(r'\.z\d+$', filename_lower):
                if VERBOSE:
                    print(f"  DEBUG: 发现ZIP分卷文件: {filename}")
                return True
    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: 检查ZIP分卷时出错: {e}")

    if VERBOSE:
        print(f"  DEBUG: ZIP文件为单个文件")
    return False


def _check_7z_sfx_multi_volume(exe_path, filename, base_dir):
    """
    检查7z SFX是否为分卷
    寻找同目录下同名的.7z.(d+)文件

    Args:
        exe_path: EXE文件路径
        filename: EXE文件名
        base_dir: EXE文件所在目录

    Returns:
        bool: 如果找到相关分卷文件返回True
    """
    # 获取exe文件的基础名称（去掉.exe）
    exe_base_name = os.path.splitext(filename)[0]

    if VERBOSE:
        print(f"  DEBUG: 检查7z SFX分卷，基础名称: {exe_base_name}")

    try:
        for check_filename in os.listdir(base_dir):
            check_filename_lower = check_filename.lower()
            exe_base_name_lower = exe_base_name.lower()

            # 检查是否存在 ${exe_file_name}.7z.(d+) 格式的文件
            expected_pattern = f"{exe_base_name_lower}.7z."
            if (check_filename_lower.startswith(expected_pattern) and
                    re.search(rf'^{re.escape(exe_base_name_lower)}\.7z\.\d+$', check_filename_lower)):
                if VERBOSE:
                    print(f"  DEBUG: 发现7z SFX分卷文件: {check_filename}")
                return True

    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: 检查7z SFX分卷时出错: {e}")

    if VERBOSE:
        print(f"  DEBUG: 未发现7z SFX分卷文件")
    return False


def _check_rar_sfx_multi_volume(exe_path, filename):
    """
    检查RAR SFX是否为分卷
    判断文件名末尾是否为.part(d+)模式

    Args:
        exe_path: EXE文件路径
        filename: EXE文件名

    Returns:
        bool: 如果是RAR SFX分卷返回True
    """
    filename_lower = filename.lower()

    if VERBOSE:
        print(f"  DEBUG: 检查RAR SFX分卷，文件名: {filename}")

    # 检查文件名末尾是否符合 .part(d+).exe 模式
    if re.search(r'\.part\d+\.exe$', filename_lower):
        if VERBOSE:
            print(f"  DEBUG: 发现RAR SFX分卷文件（文件名包含part标识）")
        return True

    if VERBOSE:
        print(f"  DEBUG: 未发现RAR SFX分卷模式")
    return False


def is_exe_multi_volume(exe_path, sfx_detector=None):
    """
    判断EXE文件是否为分卷SFX的一部分
    基于SFXDetector的检测结果来准确判断

    Args:
        exe_path: EXE文件路径
        sfx_detector: SFXDetector实例，用于检测SFX格式

    Returns:
        bool: 如果是分卷EXE返回True，否则返回False
    """
    if not exe_path.lower().endswith('.exe'):
        return False

    if sfx_detector is None:
        if VERBOSE:
            print(f"  DEBUG: 无SFXDetector实例，无法判断EXE分卷")
        return False

    filename = os.path.basename(exe_path)
    base_dir = os.path.dirname(exe_path)

    if VERBOSE:
        print(f"  DEBUG: 检查EXE是否为分卷SFX: {exe_path}")

    # Step 1: 使用SFXDetector确认exe是否为SFX
    try:
        is_sfx_result = sfx_detector.is_sfx(exe_path, detailed=True)

        if not is_sfx_result or not is_sfx_result.get('is_sfx', False):
            if VERBOSE:
                print(f"  DEBUG: EXE文件不是SFX，判断为单个文件")
            return False

        if VERBOSE:
            print(f"  DEBUG: 确认为SFX文件")

        # Step 2: 确认SFX类型（7z还是RAR）
        signature_info = is_sfx_result.get('signature', {})
        rar_marker = is_sfx_result.get('rar_marker', False)

        # 判断是RAR SFX还是7z SFX
        is_rar_sfx = False
        is_7z_sfx = False

        if signature_info.get('found', False):
            sfx_format = signature_info.get('format', '')
            if sfx_format == 'RAR':
                is_rar_sfx = True
            elif sfx_format == '7Z':
                is_7z_sfx = True

        # RAR标记也可以表明是RAR SFX
        if rar_marker:
            is_rar_sfx = True

        if VERBOSE:
            print(f"  DEBUG: SFX类型判断 - RAR: {is_rar_sfx}, 7z: {is_7z_sfx}")

        # Step 3: 根据SFX类型进行不同的分卷检查
        if is_7z_sfx:
            return _check_7z_sfx_multi_volume(exe_path, filename, base_dir)
        elif is_rar_sfx:
            return _check_rar_sfx_multi_volume(exe_path, filename)
        else:
            # 无法确定类型，使用保守策略
            if VERBOSE:
                print(f"  DEBUG: 无法确定SFX类型，检查所有可能的分卷模式")
            return (_check_7z_sfx_multi_volume(exe_path, filename, base_dir) or
                    _check_rar_sfx_multi_volume(exe_path, filename))

    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: SFX检测过程出错: {e}")
        return False


def should_skip_archive(archive_path, args, sfx_detector=None):
    """
    根据跳过参数判断是否应该跳过指定的归档文件

    Args:
        archive_path: 归档文件路径
        args: 命令行参数对象
        sfx_detector: SFXDetector实例，用于EXE文件检测

    Returns:
        tuple: (should_skip: bool, reason: str) 是否跳过和跳过原因
    """
    filename = os.path.basename(archive_path)
    filename_lower = filename.lower()

    if VERBOSE:
        print(f"  DEBUG: 检查是否跳过归档: {archive_path}")

    # 按照逻辑树进行判断，避免重复检查

    # 1. 检查7z分卷格式 (.7z.001, .7z.002等) - 必须先检查，因为.7z.001不以.7z结尾
    if re.search(r'\.7z\.\d+$', filename_lower):
        if args.skip_7z_multi:
            return True, "7z分卷文件被跳过 (--skip-7z-multi)"
        return False, ""

    # 2. 检查单个7z文件 (file.7z)
    if filename_lower.endswith('.7z'):
        if args.skip_7z:
            return True, "单个7z文件被跳过 (--skip-7z)"
        return False, ""

    # 3. 检查RAR新式分卷格式 (.partN.rar)
    if re.search(r'\.part\d+\.rar$', filename_lower):
        if args.skip_rar_multi:
            return True, "RAR分卷文件被跳过 (--skip-rar-multi)"
        return False, ""

    # 4. 检查RAR老式分卷格式 (.r00, .r01等)
    if re.search(r'\.r\d+$', filename_lower):
        if args.skip_rar_multi:
            return True, "RAR老式分卷文件被跳过 (--skip-rar-multi)"
        return False, ""

    # 5. 检查单个RAR文件 (file.rar)
    if filename_lower.endswith('.rar'):
        if args.skip_rar:
            return True, "单个RAR文件被跳过 (--skip-rar)"
        return False, ""

    # 6. 检查ZIP分卷文件 (.z01, .z02等)
    if re.search(r'\.z\d+$', filename_lower):
        if args.skip_zip_multi:
            return True, "ZIP分卷文件被跳过 (--skip-zip-multi)"
        return False, ""

    # 7. 检查ZIP文件 (file.zip) - 需要区分单个和分卷
    if filename_lower.endswith('.zip'):
        is_multi = is_zip_multi_volume(archive_path)
        if is_multi:
            # ZIP分卷主文件
            if args.skip_zip_multi:
                return True, "ZIP分卷主文件被跳过 (--skip-zip-multi)"
        else:
            # 单个ZIP文件
            if args.skip_zip:
                return True, "单个ZIP文件被跳过 (--skip-zip)"
        
        # 检查传统ZIP编码（新增）
        if hasattr(args, 'skip_traditional_zip') and args.skip_traditional_zip:
            if is_traditional_zip(archive_path):
                return True, "传统编码ZIP文件被跳过 (--skip-traditional-zip)"
        
        return False, ""

    # 8. 检查EXE文件 (file.exe) - 使用SFXDetector准确判断
    if filename_lower.endswith('.exe'):
        is_multi = is_exe_multi_volume(archive_path, sfx_detector)
        if is_multi:
            # EXE分卷
            if args.skip_exe_multi:
                return True, "EXE分卷文件被跳过 (--skip-exe-multi)"
        else:
            # 单个EXE文件
            if args.skip_exe:
                return True, "单个EXE文件被跳过 (--skip-exe)"
        return False, ""

    if VERBOSE:
        print(f"  DEBUG: 归档文件不被跳过")

    return False, ""

# ==================== 短路径API改造 ====================

def is_windows():
    """检查是否为Windows系统"""
    return platform.system() == 'Windows'


def get_short_path_name(long_path):
    """获取Windows短路径名（8.3格式），用于处理特殊字符"""
    if not is_windows():
        return long_path

    try:
        import ctypes
        from ctypes import wintypes

        # 获取短路径名
        GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        GetShortPathNameW.restype = wintypes.DWORD

        # 首先获取需要的缓冲区大小
        buffer_size = GetShortPathNameW(long_path, None, 0)
        if buffer_size == 0:
            return long_path

        # 创建缓冲区并获取短路径
        buffer = ctypes.create_unicode_buffer(buffer_size)
        result = GetShortPathNameW(long_path, buffer, buffer_size)
        if result == 0:
            return long_path

        return buffer.value
    except Exception:
        return long_path


def safe_path_for_operation(path, debug=False):
    """
    为文件系统操作获取安全的路径（优先使用短路径）

    Args:
        path: 原始路径
        debug: 是否输出调试信息

    Returns:
        str: 安全的路径（短路径或原路径）
    """
    if not path:
        return path

    if is_windows():
        short_path = get_short_path_name(path)
        if short_path != path and short_path:
            if debug:
                print(f"  DEBUG: 使用短路径: {path} -> {short_path}")
            return short_path
        elif debug:
            print(f"  DEBUG: 使用原路径: {path}")

    return path


def safe_exists(path, debug=False):
    """安全的路径存在性检查"""
    try:
        safe_path = safe_path_for_operation(path, debug)
        return os.path.exists(safe_path)
    except Exception as e:
        if debug:
            print(f"  DEBUG: 检查路径存在性失败 {path}: {e}")
        return False


def safe_isdir(path, debug=False):
    """安全的目录检查"""
    try:
        safe_path = safe_path_for_operation(path, debug)
        return os.path.isdir(safe_path)
    except Exception as e:
        if debug:
            print(f"  DEBUG: 检查路径是否为目录失败 {path}: {e}")
        return False


def safe_isfile(path, debug=False):
    """安全的文件检查"""
    try:
        safe_path = safe_path_for_operation(path, debug)
        return os.path.isfile(safe_path)
    except Exception as e:
        if debug:
            print(f"  DEBUG: 检查路径是否为文件失败 {path}: {e}")
        return False


def safe_makedirs(path, exist_ok=True, debug=False):
    """安全的目录创建"""
    try:
        safe_path = safe_path_for_operation(path, debug)
        os.makedirs(safe_path, exist_ok=exist_ok)
        if debug:
            print(f"  DEBUG: 成功创建目录: {path}")
        return True
    except Exception as e:
        if debug:
            print(f"  DEBUG: 创建目录失败 {path}: {e}")
        return False


def safe_remove(path, debug=False):
    """安全的文件删除"""
    try:
        safe_path = safe_path_for_operation(path, debug)
        os.remove(safe_path)
        if debug:
            print(f"  DEBUG: 成功删除文件: {path}")
        return True
    except Exception as e:
        if debug:
            print(f"  DEBUG: 删除文件失败 {path}: {e}")
        return False


def safe_rmdir(path, debug=False):
    """安全的空目录删除"""
    try:
        safe_path = safe_path_for_operation(path, debug)
        os.rmdir(safe_path)
        if debug:
            print(f"  DEBUG: 成功删除目录: {path}")
        return True
    except Exception as e:
        if debug:
            print(f"  DEBUG: 删除目录失败 {path}: {e}")
        return False


def safe_rmtree(path, debug=False):
    """安全的递归目录删除"""
    try:
        safe_path = safe_path_for_operation(path, debug)
        shutil.rmtree(safe_path)
        if debug:
            print(f"  DEBUG: 成功递归删除目录: {path}")
        return True
    except Exception as e:
        if debug:
            print(f"  DEBUG: 递归删除目录失败 {path}: {e}")
        return False


def safe_move(src, dst, debug=False):
    """安全的文件/目录移动/重命名"""
    try:
        safe_src = safe_path_for_operation(src, debug)
        safe_dst = safe_path_for_operation(dst, debug)

        # 如果目标已存在，先删除
        if safe_exists(dst, debug):
            if safe_isfile(dst, debug):
                safe_remove(dst, debug)
            else:
                safe_rmtree(dst, debug)

        shutil.move(safe_src, safe_dst)
        if debug:
            print(f"  DEBUG: 成功移动: {src} -> {dst}")
        return True
    except Exception as e:
        if debug:
            print(f"  DEBUG: 移动失败 {src} -> {dst}: {e}")
        return False


def safe_walk(top, debug=False):
    """安全的目录遍历"""
    try:
        safe_top = safe_path_for_operation(top, debug)
        for root, dirs, files in os.walk(safe_top):
            # 将短路径结果转换回相对于原始top的路径
            if safe_top != top:
                # 需要将root从短路径转换回长路径格式
                rel_root = os.path.relpath(root, safe_top)
                if rel_root == '.':
                    converted_root = top
                else:
                    converted_root = os.path.join(top, rel_root)
            else:
                converted_root = root

            yield converted_root, dirs, files
    except Exception as e:
        if debug:
            print(f"  DEBUG: 目录遍历失败 {top}: {e}")
        return


# ==================== 结束短路径API改造 ====================

# ==================== 锁机制 ====================

# 全局锁文件路径 - 确保路径一致性
def get_lock_file_path():
    """获取一致的锁文件路径"""
    if platform.system() == 'Windows':
        # Windows: 硬编码使用系统临时目录，确保路径一致性
        temp_dir = 'C:\\Windows\\Temp'
    else:
        # Unix/Linux: 使用标准临时目录
        temp_dir = '/tmp'

    return os.path.join(temp_dir, 'decomp_lock')


LOCK_FILE = get_lock_file_path()

# 全局变量保存锁文件句柄
lock_handle = None

# 新增：标记当前实例是否拥有锁的全局变量
lock_owner = False


def acquire_lock(max_attempts=30, min_wait=2, max_wait=10):
    """
    尝试获取全局锁，如果锁被占用则重试。
    使用文件存在性作为锁机制：文件存在=有锁，文件不存在=无锁。

    Args:
        max_attempts: 最大尝试次数
        min_wait: 重试最小等待时间（秒）
        max_wait: 重试最大等待时间（秒）

    Returns:
        bool: 是否成功获取锁
    """
    global lock_handle
    global LOCK_FILE
    global lock_owner  # 新增：锁所有者标记

    attempt = 0

    while attempt < max_attempts:
        try:
            # 检查锁文件是否存在
            if safe_exists(LOCK_FILE, VERBOSE):
                # 锁文件存在，说明有其他进程正在使用
                pass
            else:
                # 锁文件不存在，尝试创建锁文件
                try:
                    # 使用短路径获取安全的锁文件路径
                    safe_lock_file = safe_path_for_operation(LOCK_FILE)

                    # 使用 'x' 模式：只有当文件不存在时才创建，如果文件已存在会抛出异常
                    lock_handle = open(safe_lock_file, 'x')

                    # 成功创建锁文件，写入进程信息
                    hostname = socket.gethostname()
                    pid = os.getpid()
                    lock_info = f"{hostname}:{pid}:{time.time()}"
                    lock_handle.write(lock_info)
                    lock_handle.flush()
                    lock_handle.close()  # 关闭文件句柄，但保留锁文件
                    lock_handle = None

                    # 设置锁所有者标记
                    lock_owner = True

                    if VERBOSE:
                        print(f"  DEBUG: 成功获取全局锁: {LOCK_FILE}")

                    # 注册退出时的清理函数
                    atexit.register(release_lock)
                    return True

                except FileExistsError:
                    # 文件已存在，其他进程在我们检查后创建了锁文件
                    if lock_handle:
                        try:
                            lock_handle.close()
                        except:
                            pass
                        lock_handle = None

        except Exception as e:
            if VERBOSE:
                print(f"  DEBUG: 获取锁时出错: {e}")
            # 出现异常情况，清理并重试
            if lock_handle:
                try:
                    lock_handle.close()
                except:
                    pass
                lock_handle = None

        # 随机等待时间后重试
        wait_time = random.uniform(min_wait, max_wait)
        print(f"  锁被占用，将在 {wait_time:.2f} 秒后重试 (尝试 {attempt + 1}/{max_attempts})")
        time.sleep(wait_time)
        attempt += 1

    print(f"  无法获取锁，已达到最大重试次数 ({max_attempts})")
    return False


def release_lock():
    """释放全局锁，只有锁的拥有者才能释放锁"""
    global lock_handle
    global lock_owner

    # 只有锁的拥有者才能释放锁
    if not lock_owner:
        return

    # 关闭文件句柄（如果还打开着）
    if lock_handle:
        try:
            lock_handle.close()
        except:
            pass
        lock_handle = None

    # 尝试删除锁文件，最多重试5次
    max_retries = 5
    retry_delay = 5  # 每次重试间隔5秒

    for attempt in range(max_retries):
        try:
            if safe_exists(LOCK_FILE, VERBOSE):
                if safe_remove(LOCK_FILE, VERBOSE):
                    if VERBOSE:
                        print(f"  DEBUG: 成功删除锁文件: {LOCK_FILE}")
                    lock_owner = False  # 重置锁所有者标记
                    return
            else:
                # 文件不存在，说明已经被删除了
                lock_owner = False  # 重置锁所有者标记
                return

        except Exception as e:
            print(f"  删除锁文件失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:  # 不是最后一次尝试
                print(f"  将在 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                print(f"  删除锁文件失败，已达到最大重试次数 ({max_retries})")
                print(f"  请手动删除锁文件: {LOCK_FILE}")


def signal_handler(signum, frame):
    """信号处理器，用于在程序被中断时清理锁文件"""
    print(f"\n  收到信号 {signum}，正在清理...")
    release_lock()  # 只有锁的拥有者才会释放锁
    sys.exit(1)


# ==================== 结束锁机制 ====================

def setup_windows_utf8():
    """Setup UTF-8 encoding for Windows console operations"""
    if sys.platform.startswith('win'):
        try:
            # Set environment variables for UTF-8 encoding
            os.environ['PYTHONIOENCODING'] = 'utf-8'
            os.environ['LC_ALL'] = 'C.UTF-8'
            os.environ['LANG'] = 'C.UTF-8'

            # Try to set console code page to UTF-8 (65001)
            try:
                subprocess.run(['chcp', '65001'],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               check=False)
            except:
                pass

            if VERBOSE:
                print("  DEBUG: Windows UTF-8 environment setup attempted")
        except Exception as e:
            if VERBOSE:
                print(f"  DEBUG: Could not setup UTF-8 environment: {e}")


def safe_decode(byte_data, encoding='utf-8', fallback_encodings=None):
    """
    Safely decode byte data to string with multiple encoding fallbacks

    Args:
        byte_data: Bytes to decode
        encoding: Primary encoding to try (default: utf-8)
        fallback_encodings: List of fallback encodings to try

    Returns:
        str: Decoded string
    """
    if fallback_encodings is None:
        fallback_encodings = ['cp1252', 'iso-8859-1', 'gbk', 'shift-jis']

    if isinstance(byte_data, str):
        return byte_data

    # Try primary encoding with error handling
    try:
        return byte_data.decode(encoding, errors='replace')
    except (UnicodeDecodeError, LookupError):
        pass

    # Try fallback encodings
    for fallback in fallback_encodings:
        try:
            return byte_data.decode(fallback, errors='replace')
        except (UnicodeDecodeError, LookupError):
            continue

    # Last resort: decode with ignore errors
    try:
        return byte_data.decode('utf-8', errors='ignore')
    except:
        return str(byte_data, errors='ignore')


def safe_subprocess_run(cmd, **kwargs):
    """
    Safely run subprocess with proper encoding handling

    Args:
        cmd: Command to run
        **kwargs: Additional arguments for subprocess.run

    Returns:
        subprocess.CompletedProcess with safely decoded output
    """
    # Force binary mode and handle encoding manually
    kwargs_copy = kwargs.copy()
    kwargs_copy.pop('text', None)  # Remove text=True if present
    kwargs_copy.pop('encoding', None)  # Remove encoding if present
    kwargs_copy.pop('universal_newlines', None)  # Remove universal_newlines if present

    try:
        if VERBOSE:
            print(f"  DEBUG: 执行命令: {' '.join(cmd) if isinstance(cmd, list) else cmd}")

        result = subprocess.run(cmd, **kwargs_copy)

        # Safely decode stdout and stderr
        if hasattr(result, 'stdout') and result.stdout is not None:
            if isinstance(result.stdout, bytes):
                result.stdout = safe_decode(result.stdout)

        if hasattr(result, 'stderr') and result.stderr is not None:
            if isinstance(result.stderr, bytes):
                result.stderr = safe_decode(result.stderr)

        if VERBOSE:
            print(f"  DEBUG: 命令返回码: {result.returncode}")
            if result.stdout:
                print(f"  DEBUG: stdout摘要: {result.stdout[:200]}")
            if result.stderr:
                print(f"  DEBUG: stderr摘要: {result.stderr[:200]}")

        return result

    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: subprocess error: {e}")

        # Return a mock result object for error cases
        class MockResult:
            def __init__(self):
                self.returncode = 1
                self.stdout = ""
                self.stderr = str(e)

        return MockResult()


def safe_popen_communicate(cmd, **kwargs):
    """
    Safely use Popen and communicate with proper encoding handling

    Args:
        cmd: Command to run
        **kwargs: Additional arguments for Popen

    Returns:
        tuple: (stdout_str, stderr_str, returncode)
    """
    # Force binary mode
    kwargs_copy = kwargs.copy()
    kwargs_copy.pop('text', None)
    kwargs_copy.pop('encoding', None)
    kwargs_copy.pop('universal_newlines', None)

    try:
        if VERBOSE:
            print(f"  DEBUG: 执行Popen命令: {' '.join(cmd) if isinstance(cmd, list) else cmd}")

        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                **kwargs_copy)

        stdout_bytes, stderr_bytes = proc.communicate()

        # Safely decode output
        stdout_str = safe_decode(stdout_bytes) if stdout_bytes else ""
        stderr_str = safe_decode(stderr_bytes) if stderr_bytes else ""

        if VERBOSE:
            print(f"  DEBUG: Popen返回码: {proc.returncode}")
            if stdout_str:
                print(f"  DEBUG: stdout摘要: {stdout_str[:200]}")
            if stderr_str:
                print(f"  DEBUG: stderr摘要: {stderr_str[:200]}")

        return stdout_str, stderr_str, proc.returncode

    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: Popen error: {e}")
        return "", str(e), 1


class SFXDetector:
    """Detects if an EXE file is a self-extracting archive by analyzing file headers"""

    # Common archive format signatures
    SIGNATURES = {
        'RAR': [b'Rar!'],
        '7Z': [b'\x37\x7A\xBC\xAF\x27\x1C'],
        'ZIP': [b'PK\x03\x04'],
        'CAB': [b'MSCF'],
        'ARJ': [b'\x60\xEA'],
    }

    def __init__(self, verbose=False):
        """
        Initialize the SFX detector

        Args:
            verbose: Whether to output detailed information
        """
        self.verbose = verbose

    def is_exe(self, file_path):
        """
        Check if a file is a valid EXE file (only reads the first two bytes)

        Returns:
            bool: True if it's a valid EXE file, False otherwise
        """
        try:
            with open(file_path, 'rb') as f:
                result = f.read(2) == b'MZ'
                if self.verbose:
                    print(f"  DEBUG: EXE检查 {file_path}: {result}")
                return result
        except Exception as e:
            if self.verbose:
                print(f"  DEBUG: EXE检查失败 {file_path}: {e}")
            return False

    def get_pe_structure(self, file_path):
        """
        Analyze PE file structure to find the end of the executable part
        Only reads necessary header and section table information

        Returns:
            Dict: Analysis results containing:
                - valid: Whether it's a valid PE file
                - file_size: Total file size
                - executable_end: End position of the executable part
                - error: Error message (if any)
        """
        result = {
            'valid': False,
            'file_size': 0,
            'executable_end': 0,
            'error': None
        }

        try:
            if self.verbose:
                print(f"  DEBUG: 分析PE结构: {file_path}")

            with open(file_path, 'rb') as f:
                # Get total file size
                f.seek(0, 2)
                result['file_size'] = f.tell()
                f.seek(0)

                if self.verbose:
                    print(f"  DEBUG: 文件大小: {result['file_size']} bytes")

                # Read DOS header (only need the first 64 bytes)
                dos_header = f.read(64)
                if dos_header[:2] != b'MZ':
                    result['error'] = 'Not a valid PE file (MZ header)'
                    return result

                # Get PE header offset
                pe_offset = struct.unpack('<I', dos_header[60:64])[0]

                if self.verbose:
                    print(f"  DEBUG: PE头偏移: 0x{pe_offset:x}")

                # Check if PE offset is reasonable
                if pe_offset <= 0 or pe_offset >= result['file_size']:
                    result['error'] = 'Invalid PE header offset'
                    return result

                # Move to PE header
                f.seek(pe_offset)
                pe_signature = f.read(4)
                if pe_signature != b'PE\x00\x00':
                    result['error'] = 'Not a valid PE file (PE signature)'
                    return result

                # Read File Header (20 bytes)
                file_header = f.read(20)
                num_sections = struct.unpack('<H', file_header[2:4])[0]
                size_of_optional_header = struct.unpack('<H', file_header[16:18])[0]

                if self.verbose:
                    print(f"  DEBUG: 节数量: {num_sections}")

                # Skip Optional Header
                f.seek(pe_offset + 24 + size_of_optional_header)

                # Analyze section table to find the maximum file offset
                max_end_offset = 0

                for i in range(num_sections):
                    section = f.read(40)  # Each section table entry is 40 bytes
                    if len(section) < 40:
                        break

                    pointer_to_raw_data = struct.unpack('<I', section[20:24])[0]
                    size_of_raw_data = struct.unpack('<I', section[16:20])[0]

                    if pointer_to_raw_data > 0:
                        section_end = pointer_to_raw_data + size_of_raw_data
                        max_end_offset = max(max_end_offset, section_end)

                        if self.verbose:
                            section_name = section[:8].rstrip(b'\x00').decode('ascii', errors='ignore')
                            print(
                                f"  DEBUG: 节 {i + 1} ({section_name}): 偏移=0x{pointer_to_raw_data:x}, 大小={size_of_raw_data}, 结束=0x{section_end:x}")

                result['executable_end'] = max_end_offset
                result['valid'] = True

                if self.verbose:
                    print(f"  DEBUG: 可执行部分结束位置: 0x{max_end_offset:x}")

                return result

        except Exception as e:
            result['error'] = str(e)
            if self.verbose:
                print(f"  DEBUG: PE结构分析失败: {e}")
            return result

    def find_signature_after_exe(self, file_path, start_offset):
        """
        Find archive signatures from the specified offset by reading the file in chunks

        Returns:
            Dict: Results containing:
                - found: Whether a signature was found
                - format: Archive format found
                - offset: Position of the signature in the file
        """
        result = {
            'found': False,
            'format': None,
            'offset': 0
        }

        if self.verbose:
            print(f"  DEBUG: 从偏移0x{start_offset:x}开始查找归档签名")

        # Based on NSIS and other SFX implementations, archives are usually located at 512 or 4096 byte aligned positions
        aligned_offsets = []

        # Calculate nearest 512-byte aligned position
        if start_offset % 512 != 0:
            aligned_offsets.append(start_offset + (512 - start_offset % 512))
        else:
            aligned_offsets.append(start_offset)

        # Add next few aligned positions
        for i in range(1, 10):
            aligned_offsets.append(aligned_offsets[0] + i * 512)

        # Also check 4096-byte aligned positions
        if start_offset % 4096 != 0:
            aligned_offsets.append(start_offset + (4096 - start_offset % 4096))

        # Add extra potential positions
        aligned_offsets.append(start_offset)  # Start directly from executable end
        aligned_offsets.append(0x800)  # Some SFX use fixed offsets
        aligned_offsets.append(0x1000)

        # Remove duplicates and sort
        aligned_offsets = sorted(set(aligned_offsets))

        try:
            with open(file_path, 'rb') as f:
                # Check file size to ensure offset is valid
                f.seek(0, 2)
                file_size = f.tell()

                # Read block size
                block_size = 4096  # Read 4KB at a time

                # Check each aligned position
                for offset in aligned_offsets:
                    if offset >= file_size:
                        continue

                    if self.verbose:
                        print(f"  DEBUG: 检查对齐偏移: 0x{offset:x}")

                    f.seek(offset)
                    block = f.read(block_size)

                    # Check if this block contains any known archive signatures
                    for fmt, signatures in self.SIGNATURES.items():
                        for sig in signatures:
                            pos = block.find(sig)
                            if pos >= 0:
                                result['found'] = True
                                result['format'] = fmt
                                result['offset'] = offset + pos

                                if self.verbose:
                                    print(f"  DEBUG: 找到{fmt}签名，偏移: 0x{result['offset']:x}")

                                return result

                # If aligned positions didn't find anything, try sequential scanning
                # But limit scan range to avoid reading the entire file
                max_scan_size = min(10 * 1024 * 1024, file_size - start_offset)  # Scan max 10MB

                if max_scan_size > 0:
                    if self.verbose:
                        print(f"  DEBUG: 开始顺序扫描，最大扫描大小: {max_scan_size} bytes")

                    # Use larger block size for scanning
                    scan_block_size = 1024 * 1024  # 1MB blocks

                    for offset in range(start_offset, start_offset + max_scan_size, scan_block_size):
                        f.seek(offset)
                        block = f.read(scan_block_size)

                        for fmt, signatures in self.SIGNATURES.items():
                            for sig in signatures:
                                pos = block.find(sig)
                                if pos >= 0:
                                    result['found'] = True
                                    result['format'] = fmt
                                    result['offset'] = offset + pos

                                    if self.verbose:
                                        print(f"  DEBUG: 顺序扫描找到{fmt}签名，偏移: 0x{result['offset']:x}")

                                    return result

                return result

        except Exception as e:
            if self.verbose:
                print(f"  DEBUG: Error finding signature: {str(e)}")
            return result

    def check_7z_signature_variant(self, file_path):
        """
        Specially check for 7z SFX variant signatures
        Some 7z SFX may use different signatures or offsets

        Returns:
            Dict: Results
        """
        result = {
            'found': False,
            'offset': 0
        }

        if self.verbose:
            print(f"  DEBUG: 检查7z SFX变体签名")

        # Some known 7z SFX variant offsets and signatures
        known_offsets = [0x80000, 0x88000, 0x8A000, 0x8C000, 0x90000]

        try:
            with open(file_path, 'rb') as f:
                f.seek(0, 2)
                file_size = f.tell()

                for offset in known_offsets:
                    if offset >= file_size:
                        continue

                    if self.verbose:
                        print(f"  DEBUG: 检查7z变体偏移: 0x{offset:x}")

                    f.seek(offset)
                    # Check 7z signature
                    signature = f.read(6)
                    if signature == b'\x37\x7A\xBC\xAF\x27\x1C':
                        result['found'] = True
                        result['offset'] = offset

                        if self.verbose:
                            print(f"  DEBUG: 找到7z变体签名，偏移: 0x{offset:x}")

                        return result
        except Exception as e:
            if self.verbose:
                print(f"  DEBUG: 检查7z变体失败: {e}")
            pass

        return result

    def check_rar_special_marker(self, file_path):
        """
        Check for RAR SFX special markers
        Some WinRAR SFX files contain special markers at specific positions

        Returns:
            bool: Whether it contains RAR SFX markers
        """
        if self.verbose:
            print(f"  DEBUG: 检查RAR SFX特殊标记")

        try:
            with open(file_path, 'rb') as f:
                # Check file size
                f.seek(0, 2)
                file_size = f.tell()

                # Check several known RAR marker positions
                markers = [
                    (0x100, b'WinRAR SFX'),
                    (0x400, b'WINRAR'),
                    (0x400, b'WinRAR')
                ]

                for offset, marker in markers:
                    if offset + len(marker) <= file_size:
                        f.seek(offset)
                        if f.read(len(marker)) == marker:
                            if self.verbose:
                                print(f"  DEBUG: 找到RAR标记: {marker} 在偏移 0x{offset:x}")
                            return True

                # Try to find "WINRAR" or "WinRAR" strings in the first 8KB
                f.seek(0)
                header = f.read(8192)
                if b'WINRAR' in header or b'WinRAR' in header:
                    if self.verbose:
                        print(f"  DEBUG: 在文件头部找到WinRAR字符串")
                    return True

        except Exception as e:
            if self.verbose:
                print(f"  DEBUG: 检查RAR标记失败: {e}")
            pass

        return False

    def is_sfx(self, file_path, detailed=False):
        """
        Determine if a file is a self-extracting (SFX) archive by analyzing file headers

        Args:
            file_path: File path
            detailed: Whether to return detailed analysis results

        Returns:
            Union[bool, Dict]:
                If detailed=False, returns a boolean indicating whether it's an SFX file
                If detailed=True, returns a dictionary with detailed analysis results
        """
        if self.verbose:
            print(f"  DEBUG: SFX检测开始: {file_path}")

        if not safe_exists(file_path, self.verbose):
            if detailed:
                return {'is_sfx': False, 'error': 'File does not exist'}
            return False

        if not self.is_exe(file_path):
            if detailed:
                return {'is_sfx': False, 'error': 'Not a valid EXE file'}
            return False

        results = {}

        # 1. Analyze PE structure
        pe_analysis = self.get_pe_structure(file_path)
        results['pe_analysis'] = pe_analysis

        # 2. Check RAR special markers
        rar_marker_found = self.check_rar_special_marker(file_path)
        results['rar_marker'] = rar_marker_found

        # 3. Find archive signatures from executable end position
        signature_result = {'found': False}
        if pe_analysis['valid']:
            signature_result = self.find_signature_after_exe(
                file_path,
                pe_analysis['executable_end']
            )
        results['signature'] = signature_result

        # 4. Check 7z special variants
        if not signature_result['found']:
            sevenzip_variant = self.check_7z_signature_variant(file_path)
            results['7z_variant'] = sevenzip_variant
            signature_result['found'] = sevenzip_variant['found']

        # 5. Analyze extra data size (if PE analysis is valid)
        extra_data_size = 0
        if pe_analysis['valid']:
            extra_data_size = pe_analysis['file_size'] - pe_analysis['executable_end']
        results['extra_data_size'] = extra_data_size

        # Final determination
        is_sfx = (
                signature_result['found'] or
                rar_marker_found or
                (pe_analysis['valid'] and extra_data_size > 1024 * 10)  # 10KB threshold
        )
        results['is_sfx'] = is_sfx

        if self.verbose:
            print(f"  DEBUG: SFX检测结果: {is_sfx}")
            if is_sfx:
                print(f"  DEBUG: 签名发现: {signature_result['found']}")
                print(f"  DEBUG: RAR标记: {rar_marker_found}")
                print(f"  DEBUG: 额外数据大小: {extra_data_size}")

        if detailed:
            return results
        return is_sfx


def is_archive(filename):
    """
    Check if a file is an archive based on its extension

    Returns:
        bool or None: True if it's an archive, None if it might be (like an exe)
    """
    filename_lower = filename.lower()

    if VERBOSE:
        print(f"  DEBUG: 检查是否为归档文件: {filename}")

    # SFX executable files (self-extracting archives or regular executables)
    if filename_lower.endswith('.exe'):
        return None

    # 7z single archive
    if filename_lower.endswith('.7z'):
        return True

    # RAR single archive (not part of .partXX.rar structure)
    if filename_lower.endswith('.rar') and not re.search(r'\.part\d+\.rar$', filename_lower):
        return True

    # ZIP single archive or main volume of split ZIP
    if filename_lower.endswith('.zip'):
        return True
    return None


def is_main_volume(filepath):
    """
    Determine if a file is a main archive volume that needs to be checked.
    Returns True if it is a main volume, False otherwise.
    """
    filename = os.path.basename(filepath)
    filename_lower = filename.lower()

    if VERBOSE:
        print(f"  DEBUG: 检查是否为主卷: {filename}")

    # SFX executable files - we'll check if they're archives in the main function
    if filename_lower.endswith('.exe'):
        # Will need special handling in main function to check if it's an SFX
        return True

    # SFX RAR volumes (.part1.exe, .part01.exe, etc.)
    if re.search(r'\.part0*1\.exe$', filename_lower):
        return True

    # 7z single archive
    if filename_lower.endswith('.7z') and not re.search(r'\.7z\.\d+$', filename_lower):
        return True

    # 7z first volume of multi-volume archive
    if filename_lower.endswith('.7z.001'):
        return True

    # RAR single archive (not part of .partXX.rar structure)
    if filename_lower.endswith('.rar') and not re.search(r'\.part\d+\.rar$', filename_lower):
        return True

    # RAR first volume of multi-volume archive (.part1.rar, .part01.rar, .part001.rar, etc.)
    if re.search(r'\.part0*1\.rar$', filename_lower):
        return True

    # ZIP single archive or main volume of split ZIP
    if filename_lower.endswith('.zip'):
        # Check if there are .z01, .z02, etc. files with the same base name
        # For both single ZIP and split ZIP, we need to check the main volume
        return True

    return False


def is_secondary_volume(filepath):
    """
    Determine if a file is a secondary archive volume (not the main volume).
    Returns True if it is a secondary volume, False otherwise.
    """
    filename = os.path.basename(filepath)
    filename_lower = filename.lower()

    if VERBOSE:
        print(f"  DEBUG: 检查是否为次卷: {filename}")

    # SFX RAR secondary volumes (.part2.exe, .part02.exe, etc.)
    if re.search(r'\.part(?!0*1\.exe$)\d+\.exe$', filename_lower):
        return True

    # 7z secondary volumes (.7z.002, .7z.003, etc.)
    if re.search(r'\.7z\.(?!001$)\d+$', filename_lower):
        return True

    # RAR secondary volumes (.part2.rar, .part02.rar, .part002.rar, etc.)
    if re.search(r'\.part(?!0*1\.rar$)\d+\.rar$', filename_lower):
        return True

    # ZIP split files (.z01, .z02, etc. - not the main .zip)
    if re.search(r'\.z\d+$', filename_lower):
        return True

    return False


def check_encryption(filepath):
    """
    Check if an archive is encrypted by running 7z command with a dummy password.
    Returns True if encrypted, False if not, None if not an archive.
    """
    try:
        if VERBOSE:
            print(f"  DEBUG: Testing archive: {filepath}")

        # Direct approach: Try listing with a dummy password
        # This will immediately fail for encrypted archives with a clear error message
        if VERBOSE:
            print(f"  DEBUG: Checking with dummy password")

        # Use safe subprocess handling
        stdout_output, stderr_output, returncode = safe_popen_communicate(
            ['7z', 'l', '-slt', '-pDUMMYPASSWORD', filepath]
        )

        output_combined = stdout_output + stderr_output

        if VERBOSE:
            print(f"  DEBUG: Return code: {returncode}")
            print(f"  DEBUG: Output excerpt: {output_combined[:200]}")

        # Check for encryption indicators
        if "Cannot open encrypted archive. Wrong password?" in output_combined:
            if VERBOSE:
                print(f"  DEBUG: Wrong password error detected - file is encrypted")
            return True

        # Check if it's not an archive
        if "Cannot open the file as archive" in output_combined:
            if VERBOSE:
                print(f"  DEBUG: Not an archive detected")
            return None

        # If the dummy password didn't trigger an error, try without password
        # to check other encryption indicators
        if VERBOSE:
            print(f"  DEBUG: Checking without password")

        stdout_output, stderr_output, returncode = safe_popen_communicate(
            ['7z', 'l', '-slt', filepath]
        )

        output_combined = stdout_output + stderr_output

        if VERBOSE:
            print(f"  DEBUG: Return code: {returncode}")
            print(f"  DEBUG: Output excerpt: {output_combined[:200]}")

        # Check for other encryption indicators
        if "Encrypted = +" in output_combined:
            if VERBOSE:
                print(f"  DEBUG: Found 'Encrypted = +' in output")
            return True

        if "Enter password" in output_combined:
            if VERBOSE:
                print(f"  DEBUG: Found password prompt in output")
            return True

        if VERBOSE:
            print(f"  DEBUG: No encryption detected")
        return False

    except Exception as e:
        print(f"  Error checking encryption: {str(e)}")
        return None


def is_password_correct(archive_path, password):
    """Test if a password is correct for an archive."""
    try:
        if VERBOSE:
            print(f"  DEBUG: 测试密码: {archive_path} with {'<empty>' if not password else '<provided>'}")

        cmd = ['7z', 't', str(archive_path), f'-p{password}', '-y']
        result = safe_subprocess_run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        success = result.returncode == 0

        if VERBOSE:
            print(f"  DEBUG: 密码测试结果: {'成功' if success else '失败'}")

        return success
    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: Error testing password: {e}")
        return False


def try_extract(archive_path, password, tmp_dir, zip_decode=None, enable_rar=False, sfx_detector=None):
    """
    Extract archive to temporary directory.

    Args:
        archive_path: 归档文件路径
        password: 解压密码
        tmp_dir: 临时目录
        zip_decode: ZIP文件代码页（例如932表示shift-jis）
        enable_rar: 是否启用RAR解压器
        sfx_detector: SFXDetector实例，用于检测SFX文件格式
    """
    try:
        if VERBOSE:
            print(f"  DEBUG: 开始解压: {archive_path} -> {tmp_dir}")

        # 创建临时目录（重要！RAR和7z都需要目标目录存在）
        if not safe_makedirs(tmp_dir, debug=VERBOSE):
            if VERBOSE:
                print(f"  DEBUG: 创建临时目录失败: {tmp_dir}")
            return False

        # 判断是否应该使用RAR解压
        use_rar = should_use_rar_extractor(archive_path, enable_rar, sfx_detector)

        if use_rar:
            # 使用RAR命令解压
            if VERBOSE:
                print(f"  DEBUG: 使用RAR命令解压")

            # 获取安全的路径（短路径）
            safe_archive_path = safe_path_for_operation(archive_path, VERBOSE)
            safe_tmp_dir = safe_path_for_operation(tmp_dir, VERBOSE)

            cmd = ['rar', 'x', safe_archive_path, safe_tmp_dir]

            # 添加密码参数（如果有）
            if password:
                cmd.extend([f'-p{password}'])

            # 添加其他RAR参数
            cmd.extend(['-y'])  # 自动回答yes

            if VERBOSE:
                print(f"  DEBUG: RAR命令: {' '.join(cmd)}")
                print(f"  DEBUG: 原始路径: {archive_path}")
                print(f"  DEBUG: 安全路径: {safe_archive_path}")

            result = safe_subprocess_run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        else:
            # 使用7z命令解压
            if VERBOSE:
                print(f"  DEBUG: 使用7z命令解压")

            # 7z命令也使用安全路径
            safe_archive_path = safe_path_for_operation(archive_path, VERBOSE)
            safe_tmp_dir = safe_path_for_operation(tmp_dir, VERBOSE)

            cmd = ['7z', 'x', safe_archive_path, f'-o{safe_tmp_dir}', f'-p{password}', '-y']

            # 如果指定了zip_decode参数且当前文件是ZIP格式，则添加-scc参数
            if zip_decode is not None and is_zip_format(archive_path):
                scc_param = f'-scc{zip_decode}'
                cmd.append(scc_param)
                if VERBOSE:
                    print(f"  DEBUG: 添加ZIP代码页参数: {scc_param}")

            if VERBOSE:
                print(f"  DEBUG: 7z命令: {' '.join(cmd)}")
                print(f"  DEBUG: 原始路径: {archive_path}")
                print(f"  DEBUG: 安全路径: {safe_archive_path}")

            result = safe_subprocess_run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        success = result.returncode == 0

        if VERBOSE:
            extractor = 'RAR' if use_rar else '7z'
            print(f"  DEBUG: {extractor}解压结果: {'成功' if success else '失败'}")
            if not success and result.stderr:
                print(f"  DEBUG: 解压错误: {result.stderr[:300]}")

        return success

    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: Error extracting: {e}")
        return False


def get_archive_base_name(filepath):
    """Get base name for archive (corrected version following spec)."""
    filename = os.path.basename(filepath)
    filename_lower = filename.lower()

    if VERBOSE:
        print(f"  DEBUG: 获取归档基础名称: {filename}")

    # Handle different archive types correctly
    if filename_lower.endswith('.exe'):
        # For SFX files, remove .exe and part indicators
        base = re.sub(r'\.exe$', '', filename, flags=re.IGNORECASE)
        base = re.sub(r'\.part\d+$', '', base, flags=re.IGNORECASE)
        return base

    elif filename_lower.endswith('.rar'):
        if re.search(r'\.part\d+\.rar$', filename_lower):
            # Multi-part RAR: remove .partN.rar
            return re.sub(r'\.part\d+\.rar$', '', filename, flags=re.IGNORECASE)
        else:
            # Single RAR: remove .rar
            return re.sub(r'\.rar$', '', filename, flags=re.IGNORECASE)

    elif filename_lower.endswith('.7z'):
        # Single 7z: remove .7z
        return re.sub(r'\.7z$', '', filename, flags=re.IGNORECASE)

    elif re.search(r'\.7z\.\d+$', filename_lower):
        # Multi-part 7z: remove .7z.NNN
        return re.sub(r'\.7z\.\d+$', '', filename, flags=re.IGNORECASE)

    elif filename_lower.endswith('.zip'):
        # ZIP: remove .zip
        return re.sub(r'\.zip$', '', filename, flags=re.IGNORECASE)

    elif re.search(r'\.z\d+$', filename_lower):
        # ZIP volumes: remove .zNN
        return re.sub(r'\.z\d+$', '', filename, flags=re.IGNORECASE)

    # Fallback
    return os.path.splitext(filename)[0]


def find_archive_volumes(main_archive_path):
    """Find all volumes related to a main archive."""
    volumes = [main_archive_path]
    base_dir = os.path.dirname(main_archive_path)
    main_filename = os.path.basename(main_archive_path)
    main_filename_lower = main_filename.lower()

    if VERBOSE:
        print(f"  DEBUG: Finding volumes for: {main_archive_path}")

    # For different archive types, find related volumes
    if main_filename_lower.endswith('.rar') and not re.search(r'\.part\d+\.rar$', main_filename_lower):
        # Single RAR, look for .r00, .r01, etc.
        base_name = os.path.splitext(main_filename)[0]
        for i in range(100):  # Check up to .r99
            volume_name = f"{base_name}.r{i:02d}"
            volume_path = os.path.join(base_dir, volume_name)
            if safe_exists(volume_path, VERBOSE):
                volumes.append(volume_path)
                if VERBOSE:
                    print(f"  DEBUG: Found volume: {volume_path}")

    elif re.search(r'\.part0*1\.rar$', main_filename_lower):
        # Multi-part RAR, find all parts
        base_name = re.sub(r'\.part0*1\.rar$', '', main_filename, flags=re.IGNORECASE)
        try:
            for filename in os.listdir(base_dir):
                if re.search(rf'^{re.escape(base_name)}\.part\d+\.rar$', filename, re.IGNORECASE):
                    volume_path = os.path.join(base_dir, filename)
                    if volume_path != main_archive_path:
                        volumes.append(volume_path)
                        if VERBOSE:
                            print(f"  DEBUG: Found volume: {volume_path}")
        except Exception as e:
            if VERBOSE:
                print(f"  DEBUG: 查找RAR分卷失败: {e}")

    elif main_filename_lower.endswith('.7z.001'):
        # Multi-part 7z, find all parts
        base_name = main_filename[:-4]  # Remove .001 to get "filename.7z"
        for i in range(2, 1000):  # Check .002, .003, etc.
            volume_name = f"{base_name}.{i:03d}"  # Fixed: Add the missing dot
            volume_path = os.path.join(base_dir, volume_name)
            if safe_exists(volume_path, VERBOSE):
                volumes.append(volume_path)
                if VERBOSE:
                    print(f"  DEBUG: Found volume: {volume_path}")
            else:
                break

    elif main_filename_lower.endswith('.zip'):
        # Split ZIP, look for .z01, .z02, etc.
        base_name = os.path.splitext(main_filename)[0]
        for i in range(1, 100):
            volume_name = f"{base_name}.z{i:02d}"
            volume_path = os.path.join(base_dir, volume_name)
            if safe_exists(volume_path, VERBOSE):
                volumes.append(volume_path)
                if VERBOSE:
                    print(f"  DEBUG: Found volume: {volume_path}")

    elif re.search(r'\.part0*1\.exe$', main_filename_lower):
        # Multi-part SFX, find all parts
        base_name = re.sub(r'\.part0*1\.exe$', '', main_filename, flags=re.IGNORECASE)
        try:
            for filename in os.listdir(base_dir):
                if re.search(rf'^{re.escape(base_name)}\.part\d+\.exe$', filename, re.IGNORECASE):
                    volume_path = os.path.join(base_dir, filename)
                    if volume_path != main_archive_path:
                        volumes.append(volume_path)
                        if VERBOSE:
                            print(f"  DEBUG: Found volume: {volume_path}")
        except Exception as e:
            if VERBOSE:
                print(f"  DEBUG: 查找SFX分卷失败: {e}")

    if VERBOSE:
        print(f"  DEBUG: Total volumes found: {len(volumes)}")

    return volumes


def count_items_in_dir(directory):
    """Count files and directories in a directory recursively."""
    files = 0
    dirs = 0

    try:
        for root, dirnames, filenames in safe_walk(directory, VERBOSE):
            files += len(filenames)
            dirs += len(dirnames)
    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: 统计目录项目失败: {e}")

    if VERBOSE:
        print(f"  DEBUG: 目录 {directory} 包含 {files} 个文件, {dirs} 个目录")

    return files, dirs


def ensure_unique_name(target_path, unique_suffix):
    """Ensure target path is unique by adding unique_suffix if needed."""
    if not safe_exists(target_path, VERBOSE):
        return target_path

    base, ext = os.path.splitext(target_path)
    result = f"{base}_{unique_suffix}{ext}"

    if VERBOSE:
        print(f"  DEBUG: 路径冲突，使用唯一名称: {target_path} -> {result}")

    return result


def clean_temp_dir(temp_dir):
    """Safely remove temporary directory and confirm it's empty first."""
    try:
        if safe_exists(temp_dir, VERBOSE):
            # Check if directory is empty
            try:
                if not os.listdir(temp_dir):
                    safe_rmdir(temp_dir, VERBOSE)
                    if VERBOSE:
                        print(f"  DEBUG: 删除空临时目录: {temp_dir}")
                else:
                    # If not empty, force remove (this shouldn't happen in normal flow)
                    safe_rmtree(temp_dir, VERBOSE)
                    if VERBOSE:
                        print(f"  WARNING: 临时目录非空，强制删除: {temp_dir}")
            except Exception as e:
                if VERBOSE:
                    print(f"  DEBUG: 删除临时目录失败: {temp_dir}, {e}")
    except Exception as e:
        print(f"Warning: Could not remove temporary directory {temp_dir}: {e}")


def is_zip_format(archive_path):
    """
    判断文件是否为ZIP格式或ZIP分卷

    Args:
        archive_path: 归档文件路径

    Returns:
        bool: 如果是ZIP格式或ZIP分卷返回True，否则返回False
    """
    filename_lower = os.path.basename(archive_path).lower()

    if VERBOSE:
        print(f"  DEBUG: 检查是否为ZIP格式: {archive_path}")

    # 检查文件扩展名
    if filename_lower.endswith('.zip'):
        if VERBOSE:
            print(f"  DEBUG: 检测到ZIP文件")
        return True

    # 检查ZIP分卷格式 (.z01, .z02, etc.)
    if re.search(r'\.z\d+$', filename_lower):
        if VERBOSE:
            print(f"  DEBUG: 检测到ZIP分卷文件")
        return True

    # 检查文件魔术字节 (PK header)
    try:
        with open(archive_path, 'rb') as f:
            header = f.read(4)
            if header.startswith(b'PK'):
                if VERBOSE:
                    print(f"  DEBUG: 通过魔术字节检测到ZIP格式")
                return True
    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: 读取文件头失败: {e}")

    if VERBOSE:
        print(f"  DEBUG: 非ZIP格式")
    return False


# ==================== 新增解压策略 ====================

def find_file_content(tmp_dir, debug=False):
    """
    递归查找$file_content - 定义为同一深度有2个或以上文件夹/文件的层级

    Args:
        tmp_dir: 临时目录路径
        debug: 是否输出调试信息

    Returns:
        dict: {
            'found': bool,  # 是否找到
            'path': str,    # file_content所在路径
            'depth': int,   # 相对深度
            'items': list,  # file_content项目列表
            'parent_folder_path': str,  # file_content的父文件夹路径
            'parent_folder_name': str   # file_content的父文件夹名称
        }
    """
    result = {
        'found': False,
        'path': tmp_dir,
        'depth': 0,
        'items': [],
        'parent_folder_path': tmp_dir,
        'parent_folder_name': ''
    }

    if debug:
        print(f"  DEBUG: 开始查找file_content: {tmp_dir}")

    def get_items_at_depth(path, current_depth=1):
        """获取指定深度的所有项目"""
        try:
            items = []
            if current_depth == 1:
                # 直接列出当前目录内容
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    items.append({
                        'name': item,
                        'path': item_path,
                        'is_dir': safe_isdir(item_path, debug)
                    })
            else:
                # 递归查找指定深度的项目
                for root, dirs, files in safe_walk(path, debug):
                    rel_path = os.path.relpath(root, path)
                    depth = len([p for p in rel_path.split(os.sep) if p and p != '.'])

                    if depth == current_depth - 1:
                        # 这一层的目录，添加其子项目
                        for dir_name in dirs:
                            dir_path = os.path.join(root, dir_name)
                            items.append({
                                'name': dir_name,
                                'path': dir_path,
                                'is_dir': True
                            })
                        for file_name in files:
                            file_path = os.path.join(root, file_name)
                            items.append({
                                'name': file_name,
                                'path': file_path,
                                'is_dir': False
                            })
            return items
        except Exception as e:
            if debug:
                print(f"  DEBUG: 获取深度{current_depth}项目失败: {e}")
            return []

    # 从深度1开始递归查找
    max_search_depth = 10  # 避免无限递归

    for depth in range(1, max_search_depth + 1):
        items = get_items_at_depth(tmp_dir, depth)

        if debug:
            print(f"  DEBUG: 深度{depth}: 找到{len(items)}个项目")
            for item in items[:5]:  # 只显示前5个
                print(f"    {item['name']} ({'文件夹' if item['is_dir'] else '文件'})")

        if len(items) >= 2:
            # 找到file_content
            result['found'] = True
            result['depth'] = depth
            result['items'] = items

            # 计算file_content所在的父目录路径和名称
            if depth == 1:
                result['path'] = tmp_dir
                result['parent_folder_path'] = tmp_dir
                result['parent_folder_name'] = os.path.basename(tmp_dir)
            else:
                # 需要找到深度为depth-1的目录
                for root, dirs, files in safe_walk(tmp_dir, debug):
                    rel_path = os.path.relpath(root, tmp_dir)
                    if rel_path == '.':
                        current_depth = 0
                    else:
                        current_depth = len([p for p in rel_path.split(os.sep) if p])

                    if current_depth == depth - 1:
                        result['path'] = root
                        result['parent_folder_path'] = root
                        result['parent_folder_name'] = os.path.basename(root)
                        break

            if debug:
                print(f"  DEBUG: 找到file_content在深度{depth}")
                print(f"  DEBUG: file_content路径: {result['path']}")
                print(f"  DEBUG: 父文件夹路径: {result['parent_folder_path']}")
                print(f"  DEBUG: 父文件夹名称: {result['parent_folder_name']}")
            break

        if not items:
            # 没有更深的项目了
            break

    if not result['found']:
        # 特殊情况：没有找到满足条件的file_content
        # 找最深层的单个项目作为file_content
        if debug:
            print(f"  DEBUG: 没有找到标准file_content，查找最深层项目")

        deepest_items = []
        max_depth = 0
        deepest_parent_path = tmp_dir

        for root, dirs, files in safe_walk(tmp_dir, debug):
            rel_path = os.path.relpath(root, tmp_dir)
            if rel_path == '.':
                depth = 0
            else:
                depth = len([p for p in rel_path.split(os.sep) if p])

            if depth > max_depth:
                max_depth = depth
                deepest_items = []
                deepest_parent_path = root

                # 添加当前层的文件
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    deepest_items.append({
                        'name': file_name,
                        'path': file_path,
                        'is_dir': False
                    })

                # 添加当前层的空目录
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    # 检查这个目录是否有子内容
                    has_content = False
                    try:
                        for sub_root, sub_dirs, sub_files in safe_walk(dir_path, debug):
                            if sub_dirs or sub_files:
                                has_content = True
                                break
                    except:
                        pass

                    if not has_content:
                        deepest_items.append({
                            'name': dir_name,
                            'path': dir_path,
                            'is_dir': True
                        })
            elif depth == max_depth:
                # 添加到当前最深层
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    deepest_items.append({
                        'name': file_name,
                        'path': file_path,
                        'is_dir': False
                    })

        if deepest_items:
            result['found'] = True
            result['depth'] = max_depth + 1
            result['items'] = deepest_items
            result['path'] = deepest_parent_path
            result['parent_folder_path'] = deepest_parent_path
            result['parent_folder_name'] = os.path.basename(deepest_parent_path)

            if debug:
                print(f"  DEBUG: 使用最深层项目作为file_content，深度{result['depth']}")
                print(f"  DEBUG: 父文件夹路径: {result['parent_folder_path']}")
                print(f"  DEBUG: 父文件夹名称: {result['parent_folder_name']}")

    return result


def apply_only_file_content_policy(tmp_dir, output_dir, archive_name, unique_suffix):
    """
    应用only-file-content策略

    Args:
        tmp_dir: 临时目录
        output_dir: 输出目录
        archive_name: 归档名称
        unique_suffix: 唯一后缀
    """
    if VERBOSE:
        print(f"  DEBUG: 应用only-file-content策略")

    # 1. 查找file_content
    file_content = find_file_content(tmp_dir, VERBOSE)

    if not file_content['found']:
        if VERBOSE:
            print(f"  DEBUG: 未找到file_content，回退到separate策略")
        # 回退到separate策略
        apply_separate_policy_internal(tmp_dir, output_dir, archive_name, unique_suffix)
        return

    # 2. 创建content临时目录
    content_dir = f"content_{unique_suffix}"

    try:
        safe_makedirs(content_dir, debug=VERBOSE)

        if VERBOSE:
            print(f"  DEBUG: 创建content目录: {content_dir}")

        # 3. 移动file_content到content目录
        for item in file_content['items']:
            src_path = item['path']
            dst_path = os.path.join(content_dir, item['name'])

            if VERBOSE:
                print(f"  DEBUG: 移动file_content项目: {src_path} -> {dst_path}")

            safe_move(src_path, dst_path, VERBOSE)

        # 4. 确认tmp目录只剩空文件夹
        has_files = False
        try:
            for root, dirs, files in safe_walk(tmp_dir, VERBOSE):
                if files:
                    has_files = True
                    if VERBOSE:
                        print(f"  DEBUG: 警告：tmp目录仍有文件: {files}")
                    break
        except Exception as e:
            if VERBOSE:
                print(f"  DEBUG: 检查tmp目录失败: {e}")

        # 5. 创建最终输出目录
        final_archive_dir = os.path.join(output_dir, archive_name)
        final_archive_dir = ensure_unique_name(final_archive_dir, unique_suffix)
        safe_makedirs(final_archive_dir, debug=VERBOSE)

        # 6. 移动content到最终目录
        for item in os.listdir(content_dir):
            src_path = os.path.join(content_dir, item)
            dst_path = os.path.join(final_archive_dir, item)

            if VERBOSE:
                print(f"  DEBUG: 移动到最终目录: {src_path} -> {dst_path}")

            safe_move(src_path, dst_path, VERBOSE)

        print(f"  Extracted using only-file-content policy to: {final_archive_dir}")

    finally:
        # 7. 清理content目录
        if safe_exists(content_dir, VERBOSE):
            safe_rmtree(content_dir, VERBOSE)


def apply_file_content_with_folder_policy(tmp_dir, output_dir, archive_name, unique_suffix):
    """
    应用file-content-with-folder策略

    Args:
        tmp_dir: 临时目录
        output_dir: 输出目录
        archive_name: 归档名称（压缩文件名称或分卷压缩包主名称）
        unique_suffix: 唯一后缀
    """
    if VERBOSE:
        print(f"  DEBUG: 应用file-content-with-folder策略")

    # 1. 查找file_content
    file_content = find_file_content(tmp_dir, VERBOSE)

    if not file_content['found']:
        if VERBOSE:
            print(f"  DEBUG: 未找到file_content，回退到separate策略")
        # 回退到separate策略
        apply_separate_policy_internal(tmp_dir, output_dir, archive_name, unique_suffix)
        return

    # 2. 创建content临时目录
    content_dir = f"content_{unique_suffix}"

    try:
        safe_makedirs(content_dir, debug=VERBOSE)

        if VERBOSE:
            print(f"  DEBUG: 创建content目录: {content_dir}")

        # 3. 移动file_content到content目录
        for item in file_content['items']:
            src_path = item['path']
            dst_path = os.path.join(content_dir, item['name'])

            if VERBOSE:
                print(f"  DEBUG: 移动file_content项目: {src_path} -> {dst_path}")

            safe_move(src_path, dst_path, VERBOSE)

        # 4. 确定deepest_folder_name
        # 如果父文件夹就是tmp文件夹，则认为父文件夹名称是archive_name
        # 如果父文件夹不是tmp文件夹，则使用file_content的父文件夹名称
        if file_content['parent_folder_path'] == tmp_dir:
            deepest_folder_name = archive_name
            if VERBOSE:
                print(f"  DEBUG: file_content的父文件夹是tmp目录，使用归档名称: {deepest_folder_name}")
        else:
            deepest_folder_name = file_content['parent_folder_name']
            if VERBOSE:
                print(f"  DEBUG: 使用file_content的父文件夹名称: {deepest_folder_name}")

        # 5. 创建最终输出目录（使用deepest_folder_name）
        final_archive_dir = os.path.join(output_dir, deepest_folder_name)
        final_archive_dir = ensure_unique_name(final_archive_dir, unique_suffix)
        safe_makedirs(final_archive_dir, debug=VERBOSE)

        # 6. 移动content到最终目录
        for item in os.listdir(content_dir):
            src_path = os.path.join(content_dir, item)
            dst_path = os.path.join(final_archive_dir, item)

            if VERBOSE:
                print(f"  DEBUG: 移动到最终目录: {src_path} -> {dst_path}")

            safe_move(src_path, dst_path, VERBOSE)

        print(f"  Extracted using file-content-with-folder policy to: {final_archive_dir}")

    finally:
        # 7. 清理content目录
        if safe_exists(content_dir, VERBOSE):
            safe_rmtree(content_dir, VERBOSE)


def apply_separate_policy_internal(tmp_dir, output_dir, archive_name, unique_suffix):
    """内部separate策略实现，供其他策略回退使用"""
    separate_dir = f"separate_{unique_suffix}"

    try:
        safe_makedirs(separate_dir, debug=VERBOSE)

        # Create archive folder in separate directory
        archive_folder = os.path.join(separate_dir, archive_name)
        archive_folder = ensure_unique_name(archive_folder, unique_suffix)
        safe_makedirs(archive_folder, debug=VERBOSE)

        # Move contents from tmp to archive folder
        try:
            for item in os.listdir(tmp_dir):
                src_item = os.path.join(tmp_dir, item)
                dest_item = os.path.join(archive_folder, item)
                safe_move(src_item, dest_item, VERBOSE)
        except Exception as e:
            if VERBOSE:
                print(f"  DEBUG: 移动内容失败: {e}")

        # Move archive folder to final destination
        final_archive_path = os.path.join(output_dir, archive_name)
        final_archive_path = ensure_unique_name(final_archive_path, unique_suffix)
        safe_move(archive_folder, final_archive_path, VERBOSE)

        print(f"  Extracted to: {final_archive_path}")

    finally:
        if safe_exists(separate_dir, VERBOSE):
            safe_rmtree(separate_dir, VERBOSE)


# ==================== 结束新增解压策略 ====================

# ==================== 新增RAR策略 ====================

def check_rar_available():
    """
    Check if rar command is available in PATH

    Returns:
        bool: True if rar command is available, False otherwise
    """
    try:
        if VERBOSE:
            print(f"  DEBUG: 检查rar命令可用性")

        # Try to run rar command to check if it's available
        result = safe_subprocess_run(['rar'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # rar command typically returns non-zero when run without arguments
        # but if it's found, we should get some output
        available = True  # If command runs without FileNotFoundError, it's available

        if VERBOSE:
            print(f"  DEBUG: rar命令{'可用' if available else '不可用'}")

        return available

    except FileNotFoundError:
        if VERBOSE:
            print(f"  DEBUG: rar命令未找到")
        return False
    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: 检查rar命令时出错: {e}")
        return False


def is_rar_format(archive_path):
    """
    判断文件是否为RAR格式或RAR分卷

    Args:
        archive_path: 归档文件路径

    Returns:
        bool: 如果是RAR格式或RAR分卷返回True，否则返回False
    """
    filename_lower = os.path.basename(archive_path).lower()

    if VERBOSE:
        print(f"  DEBUG: 检查是否为RAR格式: {archive_path}")

    # 检查文件扩展名
    if filename_lower.endswith('.rar'):
        if VERBOSE:
            print(f"  DEBUG: 检测到RAR文件（扩展名）")
        return True

    # 检查RAR分卷格式 (.part*.rar)
    if re.search(r'\.part\d+\.rar$', filename_lower):
        if VERBOSE:
            print(f"  DEBUG: 检测到RAR分卷文件（扩展名）")
        return True

    # 检查RAR老式分卷格式 (.r00, .r01, etc.)
    if re.search(r'\.r\d+$', filename_lower):
        if VERBOSE:
            print(f"  DEBUG: 检测到RAR老式分卷文件（扩展名）")
        return True

    # 检查文件魔术字节 (Rar! header)
    try:
        with open(archive_path, 'rb') as f:
            header = f.read(4)
            if header == b'Rar!':
                if VERBOSE:
                    print(f"  DEBUG: 通过魔术字节检测到RAR格式")
                return True
    except Exception as e:
        if VERBOSE:
            print(f"  DEBUG: 读取文件头失败: {e}")

    if VERBOSE:
        print(f"  DEBUG: 非RAR格式")
    return False


def should_use_rar_extractor(archive_path, enable_rar=False, sfx_detector=None):
    """
    判断是否应该使用RAR命令解压文件

    Args:
        archive_path: 归档文件路径
        enable_rar: 是否启用RAR解压器
        sfx_detector: SFXDetector实例，用于检测SFX文件

    Returns:
        bool: 如果应该使用RAR解压返回True，否则返回False
    """
    if not enable_rar:
        if VERBOSE:
            print(f"  DEBUG: RAR解压器未启用，使用7z")
        return False

    filename_lower = os.path.basename(archive_path).lower()

    if VERBOSE:
        print(f"  DEBUG: 判断是否使用RAR解压: {archive_path}")

    # 对于明显的RAR文件，直接返回True
    if is_rar_format(archive_path):
        if VERBOSE:
            print(f"  DEBUG: 检测到RAR格式，使用RAR解压")
        return True

    # 对于SFX文件（.exe），需要检测内部格式
    if filename_lower.endswith('.exe') and sfx_detector:
        if VERBOSE:
            print(f"  DEBUG: 检测SFX文件格式")

        # 使用详细的SFX检测
        sfx_result = sfx_detector.is_sfx(archive_path, detailed=True)

        if sfx_result and sfx_result.get('is_sfx', False):
            # 检查是否找到了RAR签名或RAR标记
            signature_info = sfx_result.get('signature', {})
            rar_marker = sfx_result.get('rar_marker', False)

            if signature_info.get('found', False) and signature_info.get('format') == 'RAR':
                if VERBOSE:
                    print(f"  DEBUG: SFX文件包含RAR签名，使用RAR解压")
                return True

            if rar_marker:
                if VERBOSE:
                    print(f"  DEBUG: SFX文件包含RAR标记，使用RAR解压")
                return True

            if VERBOSE:
                print(f"  DEBUG: SFX文件非RAR格式，使用7z解压")
        else:
            if VERBOSE:
                print(f"  DEBUG: 非SFX文件，使用7z解压")

    if VERBOSE:
        print(f"  DEBUG: 使用7z解压")
    return False


# ==================== 结束新增RAR策略 ====================

class ArchiveProcessor:
    """Handles archive processing with various policies."""

    def __init__(self, args):
        self.args = args
        self.sfx_detector = SFXDetector(verbose=args.verbose)
        self.failed_archives = []
        self.successful_archives = []
        self.skipped_archives = []

    def find_archives(self, search_path):
        """Find all archives to process in the given path."""
        archives = []

        if VERBOSE:
            print(f"  DEBUG: 查找归档文件: {search_path}")

        # 解析深度范围参数
        depth_range = None
        if hasattr(self.args, 'depth_range') and self.args.depth_range:
            try:
                depth_range = parse_depth_range(self.args.depth_range)
                if VERBOSE:
                    print(f"  DEBUG: 使用深度范围: {depth_range[0]}-{depth_range[1]}")
            except ValueError as e:
                print(f"Error: Invalid depth range: {e}")
                return []

        if safe_isfile(search_path, VERBOSE):
            # 处理单个文件的情况
            if depth_range is not None:
                # 单个文件被认为在深度0
                if not (depth_range[0] <= 0 <= depth_range[1]):
                    if VERBOSE:
                        print(f"  DEBUG: 跳过文件（深度0超出范围）: {search_path}")
                    self.skipped_archives.append(search_path)
                    return archives
            
            if is_main_volume(search_path):
                # 检查是否应该跳过
                should_skip, skip_reason = should_skip_archive(search_path, self.args, self.sfx_detector)
                if should_skip:
                    if VERBOSE:
                        print(f"  DEBUG: 跳过文件: {search_path} - {skip_reason}")
                    self.skipped_archives.append(search_path)
                else:
                    archives.append(search_path)
        else:
            # 处理目录的情况
            try:
                for root, dirs, files in safe_walk(search_path, VERBOSE):
                    # 计算当前目录相对于搜索路径的深度
                    try:
                        rel_path = os.path.relpath(root, search_path)
                        if rel_path == '.':
                            current_depth = 0
                        else:
                            # 计算路径段数量作为深度
                            path_parts = [p for p in rel_path.split(os.sep) if p and p != '.']
                            current_depth = len(path_parts)
                    except ValueError:
                        # 如果无法计算相对路径，跳过
                        if VERBOSE:
                            print(f"  DEBUG: 无法计算相对路径，跳过: {root}")
                        continue

                    # 检查当前深度是否在指定范围内
                    if depth_range is not None:
                        if not (depth_range[0] <= current_depth <= depth_range[1]):
                            if VERBOSE:
                                print(f"  DEBUG: 跳过深度{current_depth}的目录（超出范围）: {root}")
                            continue

                    if VERBOSE:
                        print(f"  DEBUG: 处理深度{current_depth}的目录: {root}")

                    for file in files:
                        filepath = os.path.join(root, file)

                        # Skip secondary volumes
                        if is_secondary_volume(filepath):
                            if VERBOSE:
                                print(f"  DEBUG: 跳过次卷: {filepath}")
                            continue

                        # Check if it's a main volume or potential archive
                        if is_main_volume(filepath):
                            # 首先检查是否应该跳过
                            should_skip, skip_reason = should_skip_archive(filepath, self.args, self.sfx_detector)
                            if should_skip:
                                if VERBOSE:
                                    print(f"  DEBUG: 跳过文件: {filepath} - {skip_reason}")
                                self.skipped_archives.append(filepath)
                                continue

                            # For .exe files, check if they're SFX
                            if filepath.lower().endswith('.exe'):
                                if self.sfx_detector.is_sfx(filepath):
                                    archives.append(filepath)
                                    if VERBOSE:
                                        print(f"  DEBUG: 找到SFX归档（深度{current_depth}）: {filepath}")
                                elif VERBOSE:
                                    print(f"  DEBUG: 非SFX可执行文件: {filepath}")
                            else:
                                archives.append(filepath)
                                if VERBOSE:
                                    print(f"  DEBUG: 找到归档（深度{current_depth}）: {filepath}")
            except Exception as e:
                if VERBOSE:
                    print(f"  DEBUG: 遍历目录失败: {e}")

        if VERBOSE:
            print(f"  DEBUG: 总共找到 {len(archives)} 个归档文件")
            print(f"  DEBUG: 跳过 {len(self.skipped_archives)} 个文件")

        return archives

    def find_correct_password(self, archive_path, password_candidates):
        """Find correct password from candidates using is_password_correct."""
        if not password_candidates:
            return ""

        if VERBOSE:
            print(f"  DEBUG: 测试 {len(password_candidates)} 个密码候选")

        for i, password in enumerate(password_candidates):
            if VERBOSE:
                print(f"  DEBUG: 测试密码 {i + 1}/{len(password_candidates)}")

            if is_password_correct(archive_path, password):
                if VERBOSE:
                    print(f"  DEBUG: 找到正确密码（第{i + 1}个）")
                return password

        return None

    def get_relative_path(self, file_path, base_path):
        """Get relative path from base path."""
        try:
            return os.path.relpath(os.path.dirname(file_path), base_path)
        except ValueError:
            return ""

    def move_volumes_with_structure(self, volumes, target_base):
        """Move volumes preserving directory structure."""
        safe_makedirs(target_base, debug=VERBOSE)

        base_path = self.args.path if safe_isdir(self.args.path, VERBOSE) else os.path.dirname(self.args.path)

        if VERBOSE:
            print(f"  DEBUG: Moving {len(volumes)} volumes to {target_base}")
            for vol in volumes:
                print(f"  DEBUG: Volume to move: {vol}")

        for volume in volumes:
            try:
                rel_path = self.get_relative_path(volume, base_path)
                target_dir = os.path.join(target_base, rel_path) if rel_path else target_base
                safe_makedirs(target_dir, debug=VERBOSE)

                target_file = os.path.join(target_dir, os.path.basename(volume))
                safe_move(volume, target_file, VERBOSE)
                print(f"  Moved: {volume} -> {target_file}")
            except Exception as e:
                print(f"  Warning: Could not move {volume}: {e}")

    def process_archive(self, archive_path):
        """Process a single archive following the exact specification."""
        print(f"Processing: {archive_path}")

        if self.args.dry_run:
            print(f"  [DRY RUN] Would process: {archive_path}")
            return True

        # Step 1: Determine if we need to test passwords
        # Following spec: only test passwords if -pf is provided
        need_password_testing = bool(self.args.password_file)

        if VERBOSE:
            print(f"  DEBUG: 需要密码测试: {need_password_testing}")

        # Step 2: Check encryption only if we need to test passwords
        is_encrypted = False
        if need_password_testing:
            encryption_status = check_encryption(archive_path)
            if encryption_status is True:
                is_encrypted = True
                if VERBOSE:
                    print(f"  DEBUG: 归档已加密")
            elif encryption_status is None:
                print(f"  Warning: Cannot determine if {archive_path} is an archive")
                self.skipped_archives.append(archive_path)
                return False
            elif VERBOSE:
                print(f"  DEBUG: 归档未加密")

        # Step 3: Prepare password candidates according to spec
        password_candidates = []
        correct_password = ""

        if need_password_testing and is_encrypted:
            # Build password candidate list: -p first, then -pf
            if self.args.password:
                password_candidates.append(self.args.password)
                if VERBOSE:
                    print(f"  DEBUG: 添加命令行密码")

            if self.args.password_file:
                try:
                    with open(self.args.password_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            password = line.strip()
                            if password and password not in password_candidates:
                                password_candidates.append(password)
                    if VERBOSE:
                        print(f"  DEBUG: 从密码文件读取 {len(password_candidates)} 个密码")
                except Exception as e:
                    print(f"  Warning: Cannot read password file: {e}")

            # Test passwords using is_password_correct
            correct_password = self.find_correct_password(archive_path, password_candidates)
            if correct_password is None:
                print(f"  Error: No correct password found for {archive_path}")
                # Apply fail policy before returning
                all_volumes = find_archive_volumes(archive_path)
                if self.args.fail_policy == 'move' and self.args.fail_to:
                    self.move_volumes_with_structure(all_volumes, self.args.fail_to)
                self.failed_archives.append(archive_path)
                return False
        else:
            # Not testing passwords - use provided password directly or empty
            correct_password = self.args.password if self.args.password else ""
            if VERBOSE:
                print(f"  DEBUG: 使用提供的密码（或空密码）")

        # Step 4: Create temporary directory with thread-safe unique name
        timestamp = str(int(time.time() * 1000))
        thread_id = threading.get_ident()
        unique_id = str(uuid.uuid4().hex[:8])  # 8-char random hex for extra safety
        unique_suffix = f"{timestamp}_{thread_id}_{unique_id}"
        tmp_dir = f"tmp_{unique_suffix}"

        if VERBOSE:
            print(f"  DEBUG: 创建临时目录: {tmp_dir}")

        try:
            # Step 5: Extract using try_extract function (with new parameters)
            zip_decode = getattr(self.args, 'zip_decode', None)
            enable_rar = getattr(self.args, 'enable_rar', False)

            # Check RAR availability if needed
            if enable_rar and not check_rar_available():
                print(f"  Warning: RAR command not available, falling back to 7z")
                enable_rar = False

            success = try_extract(archive_path, correct_password, tmp_dir, zip_decode, enable_rar, self.sfx_detector)

            # Step 6: Find all volumes for this archive
            all_volumes = find_archive_volumes(archive_path)

            if success:
                print(f"  Successfully extracted to temporary directory")

                # Step 7: Apply success policy BEFORE decompress policy
                if self.args.success_policy == 'delete':
                    if VERBOSE:
                        print(f"  DEBUG: 应用删除成功策略")
                    for volume in all_volumes:
                        try:
                            safe_remove(volume, VERBOSE)
                            print(f"  Deleted: {volume}")
                        except Exception as e:
                            print(f"  Warning: Could not delete {volume}: {e}")

                elif self.args.success_policy == 'move' and self.args.success_to:
                    if VERBOSE:
                        print(f"  DEBUG: 应用移动成功策略")
                    self.move_volumes_with_structure(all_volumes, self.args.success_to)

                # Step 8: Apply decompress policy
                self.apply_decompress_policy(archive_path, tmp_dir, unique_suffix)

                self.successful_archives.append(archive_path)
                return True

            else:
                print(f"  Failed to extract: {archive_path}")

                # Step 7: Apply fail policy BEFORE decompress policy cleanup
                if self.args.fail_policy == 'move' and self.args.fail_to:
                    if VERBOSE:
                        print(f"  DEBUG: 应用失败策略")
                    self.move_volumes_with_structure(all_volumes, self.args.fail_to)

                self.failed_archives.append(archive_path)
                return False

        finally:
            # Step 9: Clean up temporary directory
            clean_temp_dir(tmp_dir)

    def apply_decompress_policy(self, archive_path, tmp_dir, unique_suffix):
        """Apply the specified decompress policy following exact specification."""
        base_path = self.args.path if safe_isdir(self.args.path, VERBOSE) else os.path.dirname(self.args.path)
        rel_path = self.get_relative_path(archive_path, base_path)

        # Determine output directory
        if self.args.output:
            output_base = self.args.output
        else:
            output_base = base_path

        final_output_dir = os.path.join(output_base, rel_path) if rel_path else output_base
        safe_makedirs(final_output_dir, debug=VERBOSE)

        archive_base_name = get_archive_base_name(archive_path)

        if VERBOSE:
            print(f"  DEBUG: 应用解压策略: {self.args.decompress_policy}")
            print(f"  DEBUG: 归档基础名称: {archive_base_name}")
            print(f"  DEBUG: 输出目录: {final_output_dir}")

        if self.args.decompress_policy == 'separate':
            self.apply_separate_policy(tmp_dir, final_output_dir, archive_base_name, unique_suffix)

        elif self.args.decompress_policy == 'direct':
            self.apply_direct_policy(tmp_dir, final_output_dir, archive_base_name, unique_suffix)

        elif self.args.decompress_policy == 'only-file-content':
            apply_only_file_content_policy(tmp_dir, final_output_dir, archive_base_name, unique_suffix)

        elif self.args.decompress_policy == 'file-content-with-folder':
            apply_file_content_with_folder_policy(tmp_dir, final_output_dir, archive_base_name, unique_suffix)

        else:
            # N-collect policy
            threshold = int(self.args.decompress_policy.split('-')[0])
            self.apply_collect_policy(tmp_dir, final_output_dir, archive_base_name, threshold, unique_suffix)

    def apply_separate_policy(self, tmp_dir, output_dir, archive_name, unique_suffix):
        """Apply separate decompress policy following exact specification."""
        if VERBOSE:
            print(f"  DEBUG: 应用separate策略")

        apply_separate_policy_internal(tmp_dir, output_dir, archive_name, unique_suffix)

    def apply_direct_policy(self, tmp_dir, output_dir, archive_name, unique_suffix):
        """Apply direct decompress policy following exact specification."""
        if VERBOSE:
            print(f"  DEBUG: 应用direct策略")

        # Check for conflicts
        try:
            tmp_items = os.listdir(tmp_dir)
            conflicts = [item for item in tmp_items if safe_exists(os.path.join(output_dir, item), VERBOSE)]

            if VERBOSE:
                print(f"  DEBUG: 检查冲突 - tmp项目: {len(tmp_items)}, 冲突: {len(conflicts)}")

            if conflicts:
                # Create archive folder for conflicts
                archive_folder = os.path.join(output_dir, archive_name)
                archive_folder = ensure_unique_name(archive_folder, unique_suffix)
                safe_makedirs(archive_folder, debug=VERBOSE)

                # Move all items to archive folder
                for item in tmp_items:
                    src_item = os.path.join(tmp_dir, item)
                    dest_item = os.path.join(archive_folder, item)
                    safe_move(src_item, dest_item, VERBOSE)

                print(f"  Extracted to: {archive_folder} (conflicts detected)")
            else:
                # Move directly to output directory
                for item in tmp_items:
                    src_item = os.path.join(tmp_dir, item)
                    dest_item = os.path.join(output_dir, item)
                    safe_move(src_item, dest_item, VERBOSE)

                print(f"  Extracted to: {output_dir}")
        except Exception as e:
            if VERBOSE:
                print(f"  DEBUG: direct策略执行失败: {e}")
            # 回退到separate策略
            self.apply_separate_policy(tmp_dir, output_dir, archive_name, unique_suffix)

    def apply_collect_policy(self, tmp_dir, output_dir, archive_name, threshold, unique_suffix):
        """Apply N-collect decompress policy following exact specification."""
        if VERBOSE:
            print(f"  DEBUG: 应用{threshold}-collect策略")

        files, dirs = count_items_in_dir(tmp_dir)
        total_items = files + dirs

        if VERBOSE:
            print(f"  DEBUG: 统计项目 - 文件: {files}, 目录: {dirs}, 总计: {total_items}, 阈值: {threshold}")

        if total_items >= threshold:
            # Create archive folder
            archive_folder = os.path.join(output_dir, archive_name)
            archive_folder = ensure_unique_name(archive_folder, unique_suffix)
            safe_makedirs(archive_folder, debug=VERBOSE)

            # Move all items to archive folder
            try:
                for item in os.listdir(tmp_dir):
                    src_item = os.path.join(tmp_dir, item)
                    dest_item = os.path.join(archive_folder, item)
                    safe_move(src_item, dest_item, VERBOSE)
            except Exception as e:
                if VERBOSE:
                    print(f"  DEBUG: collect策略移动失败: {e}")

            print(f"  Extracted to: {archive_folder} ({total_items} items >= {threshold})")
        else:
            # Extract directly, handling conflicts like direct policy
            self.apply_direct_policy(tmp_dir, output_dir, archive_name, unique_suffix)
            print(f"  Extracted directly ({total_items} items < {threshold})")


def main():
    """Main function."""
    global VERBOSE

    # Setup UTF-8 environment early
    setup_windows_utf8()

    parser = argparse.ArgumentParser(
        description='Advanced archive decompressor supporting various formats and policies'
    )

    # Required argument
    parser.add_argument(
        'path',
        help='Path to file or folder to scan for archives'
    )

    # Optional arguments
    parser.add_argument(
        '-o', '--output',
        help='Output directory for extracted files'
    )

    parser.add_argument(
        '-p', '--password',
        help='Password for encrypted archives'
    )

    parser.add_argument(
        '-pf', '--password-file',
        help='Path to password file (one password per line)'
    )

    parser.add_argument(
        '-zd', '--zip-decode',
        type=int,
        help='Code page for ZIP file extraction (e.g., 932 for Shift-JIS). Only applies to ZIP files and ZIP volumes.'
    )

    parser.add_argument(
        '-er', '--enable-rar',
        action='store_true',
        help='Enable RAR command-line tool for extracting RAR archives and RAR SFX files. Falls back to 7z if RAR is not available.'
    )

    parser.add_argument(
        '-t', '--threads',
        type=int,
        default=1,
        help='Number of concurrent extraction tasks (default: 1)'
    )

    parser.add_argument(
        '-dp', '--decompress-policy',
        default='2-collect',
        help='Decompress policy: separate/direct/only-file-content/file-content-with-folder/N-collect (default: 2-collect)'
    )

    parser.add_argument(
        '-sp', '--success-policy',
        choices=['delete', 'asis', 'move'],
        default='asis',
        help='Policy for successful extractions (default: asis)'
    )

    parser.add_argument(
        '--success-to', '-st',  # 添加别名
        help='Directory to move successful archives (required with -sp move)'
    )

    parser.add_argument(
        '-fp', '--fail-policy',
        choices=['asis', 'move'],
        default='asis',
        help='Policy for failed extractions (default: asis)'
    )

    parser.add_argument(
        '--fail-to', '-ft',  # 添加别名
        help='Directory to move failed archives (required with -fp move)'
    )

    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help='Preview mode - do not actually extract'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    # Skip single archive format arguments
    parser.add_argument(
        '--skip-7z',
        action='store_true',
        help='Skip single .7z archive files'
    )

    parser.add_argument(
        '--skip-rar',
        action='store_true',
        help='Skip single .rar archive files'
    )

    parser.add_argument(
        '--skip-zip',
        action='store_true',
        help='Skip single .zip archive files'
    )

    parser.add_argument(
        '--skip-exe',
        action='store_true',
        help='Skip single .exe SFX archive files'
    )

    # Skip multi-volume archive format arguments
    parser.add_argument(
        '--skip-7z-multi',
        action='store_true',
        help='Skip multi-volume .7z archives (.7z.001, .7z.002, etc.)'
    )

    parser.add_argument(
        '--skip-rar-multi',
        action='store_true',
        help='Skip multi-volume RAR archives (.partN.rar, .rNN formats)'
    )

    parser.add_argument(
        '--skip-zip-multi',
        action='store_true',
        help='Skip multi-volume ZIP archives (.zip with .z01, .z02, etc.)'
    )

    parser.add_argument(
        '--skip-exe-multi',
        action='store_true',
        help='Skip multi-volume SFX archives (.partN.exe and related volumes)'
    )
    
    
    # Skip traditional encoding ZIP files (新增)
    parser.add_argument(
        '--skip-traditional-zip', '-stz',
        action='store_true',
        help='Skip ZIP files that use traditional encoding (non-UTF-8). Only applies to .zip files and main volumes of split ZIP archives.'
    )
    
    

    # 锁相关参数
    parser.add_argument(
        '--no-lock',
        action='store_true',
        help='不使用全局锁（谨慎使用）'
    )

    parser.add_argument(
        '--lock-timeout',
        type=int,
        default=30,
        help='锁定超时时间（最大重试次数）'
    )
    

    parser.add_argument(
        '-dr', '--depth-range',
        help='Depth range for recursive scanning. Format: "int1-int2" or "int". '
             'Controls which directory depths to scan for archives. '
             'Depth 0 means files directly in the root path, depth 1 means files in immediate subdirectories, etc. '
             'Examples: "0-1" (scan root and first level), "1" (only first level), "0" (only root level). '
             'If not specified, all depths are scanned.'
    )

    args = parser.parse_args()

    # Set global verbose flag
    VERBOSE = args.verbose

    # 设置信号处理器
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 获取锁（除非用户指定不使用锁）
        if not args.no_lock:
            if not acquire_lock(args.lock_timeout):
                print("无法获取全局锁，程序退出")
                return 1

        # Validate arguments
        if not safe_exists(args.path, VERBOSE):
            print(f"Error: Path does not exist: {args.path}")
            return 1

        if args.success_policy == 'move' and not args.success_to:
            print("Error: --success-to is required when using -sp move")
            return 1

        if args.fail_policy == 'move' and not args.fail_to:
            print("Error: --fail-to is required when using -fp move")
            return 1

        # Validate decompress policy
        if args.decompress_policy not in ['separate', 'direct', 'only-file-content', 'file-content-with-folder']:
            if not re.match(r'^\d+-collect$', args.decompress_policy):
                print(f"Error: Invalid decompress policy: {args.decompress_policy}")
                return 1
            else:
                # Validate N-collect threshold
                threshold = int(args.decompress_policy.split('-')[0])
                if threshold < 0:
                    print(f"Error: N-collect threshold must be >= 0")
                    return 1


        # Validate depth range parameter
        if args.depth_range:
            try:
                depth_range = parse_depth_range(args.depth_range)
                if VERBOSE:
                    print(f"  DEBUG: 验证深度范围: {depth_range[0]}-{depth_range[1]}")
            except ValueError as e:
                print(f"Error: {e}")
                return 1




        # Check if 7z is available
        try:
            safe_subprocess_run(['7z'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            print("Error: 7z command not found. Please install p7zip or 7-Zip.")
            return 1

        # Check if RAR is available when --enable-rar is used
        if args.enable_rar:
            if not check_rar_available():
                print("Warning: RAR command not found in PATH. Will fall back to 7z for all archives.")
                print("To use RAR extraction, please install WinRAR or RAR command-line tool.")
                # Don't return error, just warn and continue with 7z fallback

        # Create processor and find archives
        processor = ArchiveProcessor(args)
        archives = processor.find_archives(args.path)

        if not archives:
            print("No archives found to process.")
            return 0

        print(f"Found {len(archives)} archive(s) to process.")

        # Process archives
        if args.threads == 1:
            # Single-threaded processing
            for archive in archives:
                processor.process_archive(archive)
        else:
            # Multi-threaded processing
            with ThreadPoolExecutor(max_workers=args.threads) as executor:
                futures = {executor.submit(processor.process_archive, archive): archive
                           for archive in archives}

                for future in as_completed(futures):
                    archive = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"Error processing {archive}: {e}")
                        processor.failed_archives.append(archive)

        # Print summary
        print("\n" + "=" * 50)
        print("PROCESSING SUMMARY")
        print("=" * 50)
        print(f"Total archives found: {len(archives)}")
        print(f"Successfully processed: {len(processor.successful_archives)}")
        print(f"Failed to process: {len(processor.failed_archives)}")
        print(f"Skipped: {len(processor.skipped_archives)}")

        if processor.failed_archives:
            print("\nFailed archives:")
            for archive in processor.failed_archives:
                print(f"  - {archive}")

        if processor.skipped_archives:
            print("\nSkipped archives:")
            for archive in processor.skipped_archives:
                print(f"  - {archive}")

        return 0

    except KeyboardInterrupt:
        print("\n程序被用户中断")
        # 只有获取了锁的实例才释放锁
        if lock_owner:
            release_lock()
        return 1
    except Exception as e:
        print(f"\n程序异常退出: {e}")
        if VERBOSE:
            import traceback
            traceback.print_exc()
        # 只有获取了锁的实例才释放锁
        if lock_owner:
            release_lock()
        return 1
    finally:
        # 确保锁被释放
        if lock_owner:
            release_lock()

if __name__ == '__main__':
    sys.exit(main())
