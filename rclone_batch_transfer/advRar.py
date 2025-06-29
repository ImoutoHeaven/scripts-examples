#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import argparse
import subprocess
import shutil
import platform
import time
import random
import atexit
import socket
import tempfile
import re

# 全局锁文件路径
if platform.system() == 'Windows':
    LOCK_FILE = os.path.join(os.environ.get('PROGRAMDATA', 'C:\\ProgramData'), 'rar_compress_lock')
else:
    LOCK_FILE = '/var/lock/rar_compress_lock'

# 全局变量保存锁文件句柄
lock_handle = None

def acquire_lock(max_attempts=30, min_wait=2, max_wait=10):
    """
    尝试获取全局锁，如果锁被占用则重试。
    此函数现在为Windows使用msvcrt，为Linux/Unix使用fcntl，以实现可靠的跨进程锁定。
    
    Args:
        max_attempts: 最大尝试次数
        min_wait: 重试最小等待时间（秒）
        max_wait: 重试最大等待时间（秒）
        
    Returns:
        bool: 是否成功获取锁
    """
    global lock_handle
    global LOCK_FILE
    
    # 确保锁文件目录存在
    lock_dir = os.path.dirname(LOCK_FILE)
    if lock_dir and not os.path.exists(lock_dir):
        try:
            os.makedirs(lock_dir, exist_ok=True)
        except PermissionError:
            # 如果无法创建指定目录，使用临时目录
            temp_dir = tempfile.gettempdir()
            LOCK_FILE = os.path.join(temp_dir, 'rar_compress_lock')
    
    attempt = 0
    
    while attempt < max_attempts:
        try:
            if platform.system() == 'Windows':
                import msvcrt
                # Windows实现 (修正版，使用msvcrt)
                try:
                    # 以写模式打开文件，如果不存在则创建
                    lock_handle = open(LOCK_FILE, 'w')
                    # 尝试以非阻塞方式获取文件锁
                    # 如果文件已被其他进程锁定，这将引发IOError
                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
                    
                    # 成功获取锁，写入进程信息
                    hostname = socket.gethostname()
                    pid = os.getpid()
                    lock_info = f"{hostname}:{pid}:{time.time()}"
                    lock_handle.write(lock_info)
                    lock_handle.flush()
                    
                    # 注册退出时的清理函数
                    atexit.register(release_lock)
                    return True
                except IOError:
                    # 文件已被锁定，关闭句柄并继续重试
                    if lock_handle:
                        lock_handle.close()
                        lock_handle = None
                    pass
            else:
                # Linux/Unix实现 (原始实现是正确的)
                import fcntl
                
                try:
                    # 尝试打开文件
                    lock_handle = open(LOCK_FILE, 'w+')
                    
                    # 尝试获取排他锁（非阻塞）
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    
                    # 写入进程信息
                    hostname = socket.gethostname()
                    pid = os.getpid()
                    lock_info = f"{hostname}:{pid}:{time.time()}"
                    lock_handle.write(lock_info)
                    lock_handle.flush()
                    
                    # 注册退出时的清理函数
                    atexit.register(release_lock)
                    return True
                except (IOError, BlockingIOError):
                    # 文件已被锁定
                    if lock_handle:
                        lock_handle.close()
                        lock_handle = None
        
        except Exception as e:
            print(f"获取锁时出错: {e}")
            # 出现异常情况，清理并重试
            if lock_handle:
                try:
                    lock_handle.close()
                except:
                    pass
                lock_handle = None
        
        # 随机等待时间后重试
        wait_time = random.uniform(min_wait, max_wait)
        print(f"锁被占用，将在 {wait_time:.2f} 秒后重试 (尝试 {attempt+1}/{max_attempts})")
        time.sleep(wait_time)
        attempt += 1
    
    print(f"无法获取锁，已达到最大重试次数 ({max_attempts})")
    return False

def release_lock():
    """释放全局锁"""
    global lock_handle
    
    if lock_handle:
        try:
            if platform.system() == 'Windows':
                import msvcrt
                # 在Windows上，先解锁文件
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                # Linux系统需要先解除fcntl锁
                import fcntl
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            
            # 关闭并删除锁文件
            lock_handle.close()
            
            # 尝试删除锁文件
            try:
                if os.path.exists(LOCK_FILE):
                    os.unlink(LOCK_FILE)
            except:
                pass
        except Exception as e:
            print(f"释放锁时出错: {e}")
        finally:
            lock_handle = None

def profile_type(value):
    """用于argparse的自定义类型，以验证profile参数"""
    if value in ['store', 'best']:
        return value
    
    match = re.match(r'^parted-(\d+)g$', value, re.IGNORECASE)
    if match:
        size = int(match.group(1))
        if size > 0:
            return value
    
    raise argparse.ArgumentTypeError(
        f"'{value}' 不是一个有效的配置。请选择 'store', 'best', 或者 'parted-XXg' (XX为正整数)。"
    )

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='RAR压缩工具')
    parser.add_argument('folder_path', help='要处理的文件夹路径')
    parser.add_argument('--dry-run', action='store_true', help='仅预览操作，不执行实际命令')
    parser.add_argument('--depth', type=int, default=0, help='压缩处理的深度级别 (0, 1, 2, ...)')
    parser.add_argument('-p', '--password', help='设置压缩包密码')
    parser.add_argument('-d', '--delete', action='store_true', help='压缩成功后删除原文件/文件夹')
    parser.add_argument(
        '--profile', 
        type=profile_type,  # 使用自定义验证函数
        default='best', 
        help="压缩配置文件: 'store', 'best', 或 'parted-XXg' (例如: 'parted-10g')"
    )
    parser.add_argument('--debug', action='store_true', help='显示调试信息')
    parser.add_argument('--no-lock', action='store_true', help='不使用全局锁（谨慎使用）')
    parser.add_argument('--lock-timeout', type=int, default=30, help='锁定超时时间（最大重试次数）')
    
    return parser.parse_args()

def is_windows():
    """检查当前操作系统是否为Windows"""
    return platform.system() == 'Windows'

def get_rar_command():
    """根据操作系统获取RAR命令"""
    # 尝试运行rar命令检查是否可用
    try:
        result = subprocess.run(['rar', '-?' if is_windows() else '--help'], 
                                stdout=subprocess.PIPE, 
                                stderr=subprocess.PIPE, 
                                shell=is_windows())
        if result.returncode in [0, 1, 7]:  # RAR命令可能返回这些代码
            return 'rar'
    except Exception:
        pass
    
    # 如果rar不可用，尝试使用winrar命令（仅限Windows）
    if is_windows():
        try:
            result = subprocess.run(['winrar', '-?'], 
                                    stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE, 
                                    shell=True)
            if result.returncode in [0, 1, 7]:
                return 'winrar'
        except Exception:
            pass
    
    # 如果都不可用，使用默认的rar命令，如果不存在会在执行时报错
    return 'rar'

def remove_directory(path, dry_run=False):
    """递归删除目录及其内容"""
    if dry_run:
        print(f"[DRY-RUN] 将删除目录: {path}")
        return True
    
    try:
        shutil.rmtree(path)
        return True
    except Exception as e:
        print(f"删除目录失败 {path}: {e}")
        return False

def get_items_at_depth(base_folder, target_depth):
    """获取指定深度的文件和文件夹列表"""
    items = {'files': [], 'folders': []}
    
    if target_depth == 0:
        # 深度0特殊处理：直接返回基础文件夹
        items['folders'].append(os.path.abspath(base_folder))
        return items
    
    # 对深度>0的情况，遍历文件系统
    for root, dirs, files in os.walk(base_folder):
        # 计算当前相对于基础文件夹的深度
        rel_path = os.path.relpath(root, base_folder)
        current_depth = 0 if rel_path == '.' else len(rel_path.split(os.sep))
        
        # 如果当前深度正好是目标深度-1，则其子项（文件和文件夹）就是目标深度的项
        if current_depth == target_depth - 1:
            # 收集当前层级的所有文件
            for file_name in files:
                full_path = os.path.join(root, file_name)
                items['files'].append(os.path.abspath(full_path))
            
            # 收集当前层级的所有文件夹
            for dir_name in dirs:
                full_path = os.path.join(root, dir_name)
                items['folders'].append(os.path.abspath(full_path))
    
    return items

def build_rar_switches(profile, password, delete_files=False):
    """构建RAR命令开关参数"""
    switches = []
    
    if delete_files:
        switches.append('-df')

    # 处理 'store' 和 'parted-XXg' 配置
    if profile.startswith('parted-') or profile == 'store':
        switches.extend([
            '-m0',        # 仅存储
            '-md32m',     # 字典大小：32MB
            '-s-',        # 不使用固实压缩
            '-htb',       # 使用blake2s校验和
            '-qo+',       # 为所有文件添加快速打开记录
            '-oi:1',      # 相同文件保存为引用
            '-rr5p',      # 添加5%恢复记录
            '-ma5'        # RAR5格式
        ])
        # 如果是分卷模式，添加分卷大小参数
        if profile.startswith('parted-'):
            match = re.match(r'^parted-(\d+)g$', profile, re.IGNORECASE)
            if match:
                size = match.group(1)
                switches.append(f'-v{size}g')
    # 处理 'best' 配置
    else:  # best
        switches.extend([
            '-m5',        # 最佳压缩
            '-md256m',    # 字典大小：256MB
            '-s',         # 固实压缩
            '-htb',       # 使用blake2s校验和
            '-qo+',       # 为所有文件添加快速打开记录
            '-oi:1',      # 相同文件保存为引用
            '-rr5p',      # 添加5%恢复记录
            '-ma5'        # RAR5格式
        ])
    
    # 添加密码参数
    if password:
        switches.extend([f'-p{password}', '-hp']) # -hp选项加密文件头
    
    return switches

def process_file(file_path, args):
    """处理单个文件的压缩操作"""
    # 获取文件名（不含扩展名）
    file_dir = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    name_without_ext = os.path.splitext(file_name)[0]
    
    # 构建RAR文件路径（在同一目录中）
    final_rar_file = os.path.join(file_dir, f"{name_without_ext}.rar")
    
    # 临时文件名
    temp_rar_name = f"temp_{name_without_ext}.rar"
    temp_rar_path = os.path.join(file_dir, temp_rar_name)
    
    # 保存当前工作目录
    original_cwd = os.getcwd()
    
    try:
        # 切换到文件所在目录
        os.chdir(file_dir)
        
        # 获取RAR命令开关
        rar_switches = build_rar_switches(args.profile, args.password, args.delete)
        
        # 构建RAR命令
        rar_cmd = [get_rar_command(), 'a']
        rar_cmd.extend(rar_switches)
        
        # 添加输出路径（当前目录的临时文件）
        if ' ' in temp_rar_name or any(c in temp_rar_name for c in '*?[]()^!'):
            rar_cmd.append(f'"{temp_rar_name}"')
        else:
            rar_cmd.append(temp_rar_name)
        
        # 添加输入文件（只使用文件名，不包含路径）
        if ' ' in file_name or any(c in file_name for c in '*?[]()^!'):
            rar_cmd.append(f'"{file_name}"')
        else:
            rar_cmd.append(file_name)
        
        # 将命令列表转换为字符串用于打印
        cmd_str = ' '.join(rar_cmd)
        
        # 调试输出
        if args.debug:
            print("=" * 50)
            print("调试信息 (文件):")
            print(f"- 原始文件路径: {file_path}")
            print(f"- 文件名: {file_name}")
            print(f"- 临时RAR文件: {temp_rar_name}")
            print(f"- 最终目标RAR文件: {final_rar_file}")
            print(f"- 当前工作目录: {os.getcwd()}")
            print(f"- 命令列表: {rar_cmd}")
            print("=" * 50)
        
        if args.dry_run:
            print(f"[DRY-RUN] 将执行: {cmd_str}")
            return
        
        print(f"执行: {cmd_str}")
        
        # 执行RAR命令
        try:
            use_shell = is_windows()
            
            if use_shell:
                result = subprocess.run(cmd_str, shell=True, check=False, capture_output=True, text=True)
            else:
                # 对于非Windows系统，移除命令中的引号
                cleaned_cmd = [arg.strip('"\'') for arg in rar_cmd]
                result = subprocess.run(cleaned_cmd, shell=False, check=False, capture_output=True, text=True)
            
            # 输出详细的执行结果（如果开启了调试模式）
            if args.debug:
                print("命令执行结果:")
                print(f"- 返回码: {result.returncode}")
                print(f"- 标准输出: {result.stdout}")
                print(f"- 错误输出: {result.stderr}")
            
            # 检查命令执行结果
            if result.returncode == 0:
                print(f"成功创建临时RAR文件: {temp_rar_path}")
                
                # 切换回原始工作目录
                os.chdir(original_cwd)
                
                # 如果存在同名文件，先删除
                if os.path.exists(final_rar_file) and temp_rar_path != final_rar_file:
                    try:
                        os.remove(final_rar_file)
                        if args.debug:
                            print(f"已删除已存在的RAR文件: {final_rar_file}")
                    except Exception as e:
                        print(f"删除已存在的RAR文件失败: {e}")
                        return
                
                # 重命名临时RAR文件到最终位置
                try:
                    shutil.move(temp_rar_path, final_rar_file)
                    print(f"已将临时RAR文件移动到最终位置: {final_rar_file}")
                except Exception as e:
                    print(f"移动临时RAR文件时出错: {e}")
                    if args.debug:
                        import traceback
                        traceback.print_exc()
            else:
                print(f"创建RAR文件失败，返回码: {result.returncode}")
                print(f"错误输出: {result.stderr}")
        except Exception as e:
            print(f"执行RAR命令时出错: {e}")
            if args.debug:
                import traceback
                traceback.print_exc()
    finally:
        # 确保无论如何都会切换回原始工作目录
        try:
            os.chdir(original_cwd)
        except Exception as e:
            print(f"切换回原始工作目录时出错: {e}")

def process_folder(folder_path, args):
    """处理单个文件夹的压缩操作"""
    # 获取文件夹名称
    folder_name = os.path.basename(folder_path)
    parent_dir = os.path.dirname(folder_path)
    
    # 构建RAR文件路径（在父目录中）
    final_rar_file = os.path.join(parent_dir, f"{folder_name}.rar")
    
    # 临时文件名，直接放在上级目录
    temp_rar_name = "temp_archive.rar"
    temp_rar_path = os.path.join(parent_dir, temp_rar_name)
    
    # 保存当前工作目录
    original_cwd = os.getcwd()
    
    try:
        # 切换到目标文件夹
        os.chdir(folder_path)
        
        # 获取RAR命令开关，对于文件夹需要添加-r选项
        rar_switches = build_rar_switches(args.profile, args.password, args.delete)
        rar_switches.insert(0, '-r')  # 在开头添加递归选项
        
        # 构建RAR命令
        rar_cmd = [get_rar_command(), 'a']
        rar_cmd.extend(rar_switches)
        
        # 添加输出路径（上级目录中的临时文件）
        if ' ' in temp_rar_name or any(c in temp_rar_name for c in '*?[]()^!'):
            rar_cmd.append(f'"../{temp_rar_name}"')
        else:
            rar_cmd.append(f"../{temp_rar_name}")
        
        # 添加输入通配符，表示当前目录下的所有文件
        rar_cmd.append('*')
        
        # 将命令列表转换为字符串用于打印
        cmd_str = ' '.join(rar_cmd)
        
        # 调试输出
        if args.debug:
            print("=" * 50)
            print("调试信息 (文件夹):")
            print(f"- 原始文件夹路径: {folder_path}")
            print(f"- 临时RAR文件: {temp_rar_path}")
            print(f"- 最终目标RAR文件: {final_rar_file}")
            print(f"- 当前工作目录: {os.getcwd()}")
            print(f"- 命令列表: {rar_cmd}")
            print("=" * 50)
        
        if args.dry_run:
            print(f"[DRY-RUN] 将执行: {cmd_str}")
            return
        
        print(f"执行: {cmd_str}")
        
        # 执行RAR命令
        try:
            use_shell = is_windows()
            
            if use_shell:
                result = subprocess.run(cmd_str, shell=True, check=False, capture_output=True, text=True)
            else:
                # 对于非Windows系统，移除命令中的引号
                cleaned_cmd = [arg.strip('"\'') for arg in rar_cmd]
                result = subprocess.run(cleaned_cmd, shell=False, check=False, capture_output=True, text=True)
            
            # 输出详细的执行结果（如果开启了调试模式）
            if args.debug:
                print("命令执行结果:")
                print(f"- 返回码: {result.returncode}")
                print(f"- 标准输出: {result.stdout}")
                print(f"- 错误输出: {result.stderr}")
            
            # 检查命令执行结果
            if result.returncode == 0:
                print(f"成功创建临时RAR文件: {temp_rar_path}")
                
                # 切换回原始工作目录
                os.chdir(original_cwd)
                
                # 如果存在同名文件，先删除
                if os.path.exists(final_rar_file) and temp_rar_path != final_rar_file:
                    try:
                        os.remove(final_rar_file)
                        if args.debug:
                            print(f"已删除已存在的RAR文件: {final_rar_file}")
                    except Exception as e:
                        print(f"删除已存在的RAR文件失败: {e}")
                        return
                
                # 重命名临时RAR文件到最终位置
                try:
                    # 对于Windows长路径，使用特殊的移动方法
                    if is_windows() and (len(final_rar_file) > 250 or len(temp_rar_path) > 250):
                        import ctypes
                        from ctypes import wintypes
                        
                        # 定义必要的函数和常量
                        MOVEFILE_REPLACE_EXISTING = 0x1
                        MoveFileExW = windll.kernel32.MoveFileExW
                        MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
                        MoveFileExW.restype = wintypes.BOOL
                        
                        # 准备完整路径（使用\\?\前缀）
                        src_path = f"\\\\?\\{os.path.abspath(temp_rar_path)}"
                        dst_path = f"\\\\?\\{os.path.abspath(final_rar_file)}"
                        
                        if args.debug:
                            print(f"使用Windows API移动文件:")
                            print(f"- 源路径: {src_path}")
                            print(f"- 目标路径: {dst_path}")
                        
                        # 调用Windows API移动文件
                        result = MoveFileExW(src_path, dst_path, MOVEFILE_REPLACE_EXISTING)
                        if not result:
                            error_code = ctypes.GetLastError()
                            print(f"移动文件失败，错误码: {error_code}")
                            return
                    else:
                        # 对于正常长度的路径，使用标准方法
                        shutil.move(temp_rar_path, final_rar_file)
                    
                    print(f"已将临时RAR文件移动到最终位置: {final_rar_file}")
                    
                    # 如果指定了删除选项，则尝试删除可能剩余的空文件夹
                    # 由于文件已经由RAR的-df选项删除，这里只需尝试删除文件夹结构
                    if args.delete:
                        try:
                            # 尝试删除文件夹（应该只剩下空结构）
                            os.rmdir(folder_path)
                            print(f"已删除原始文件夹: {folder_path}")
                        except Exception as e:
                            print(f"无法删除原始文件夹（可能不为空）: {folder_path}")
                            if args.debug:
                                print(f"删除错误: {e}")
                except Exception as e:
                    print(f"移动临时RAR文件时出错: {e}")
                    if args.debug:
                        import traceback
                        traceback.print_exc()
            else:
                print(f"创建RAR文件失败，返回码: {result.returncode}")
                print(f"错误输出: {result.stderr}")
        except Exception as e:
            print(f"执行RAR命令时出错: {e}")
            if args.debug:
                import traceback
                traceback.print_exc()
    finally:
        # 确保无论如何都会切换回原始工作目录
        try:
            os.chdir(original_cwd)
        except Exception as e:
            print(f"切换回原始工作目录时出错: {e}")

def main():
    """主函数"""
    args = parse_arguments()
    
    # 验证目标路径
    if not os.path.exists(args.folder_path):
        print(f"错误: 路径不存在 - {args.folder_path}")
        sys.exit(1)
    
    if not os.path.isdir(args.folder_path):
        print(f"错误: 不是一个目录 - {args.folder_path}")
        sys.exit(1)
    
    # 尝试获取全局锁（除非指定了--no-lock选项）
    if not args.no_lock:
        if not acquire_lock(max_attempts=args.lock_timeout):
            print("无法获取全局锁，退出程序")
            sys.exit(2)
        print(f"成功获取全局锁: {LOCK_FILE}")
    
    try:
        # 在Windows系统上启用长路径支持
        if is_windows():
            # 尝试启用Windows长路径支持
            try:
                import ctypes
                # 使用UTF-8模式以更好地支持非英文字符
                if hasattr(ctypes.windll.kernel32, 'SetConsoleCP'):
                    ctypes.windll.kernel32.SetConsoleCP(65001)
                    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
                # 设置处理文件API的行为，启用长路径支持
                if hasattr(ctypes.windll.kernel32, 'SetProcessAffinityMask'):
                    ctypes.windll.kernel32.SetProcessAffinityMask(
                        ctypes.windll.kernel32.GetCurrentProcess(),
                        0x00400000  # PROCESS_LONG_PATH_AWARE
                    )
                if args.debug:
                    print("已尝试启用Windows长路径支持")
            except Exception as e:
                if args.debug:
                    print(f"启用Windows长路径支持时出错: {e}")
        
        # 获取指定深度的文件和文件夹列表
        items = get_items_at_depth(args.folder_path, args.depth)
        
        if args.debug:
            print(f"找到以下符合深度 {args.depth} 的项目:")
            print(f"文件数量: {len(items['files'])}")
            print(f"文件夹数量: {len(items['folders'])}")
            if len(items['files']) > 0:
                print("文件列表（前10个）:")
                for path in items['files'][:10]:
                    print(f"- {path}")
                if len(items['files']) > 10:
                    print(f"... 还有 {len(items['files']) - 10} 个文件")
            if len(items['folders']) > 0:
                print("文件夹列表（前10个）:")
                for path in items['folders'][:10]:
                    print(f"- {path}")
                if len(items['folders']) > 10:
                    print(f"... 还有 {len(items['folders']) - 10} 个文件夹")
        
        total_items = len(items['files']) + len(items['folders'])
        if total_items == 0:
            print(f"警告: 在深度 {args.depth} 没有找到任何文件或文件夹")
            sys.exit(0)
        
        print(f"准备处理 {total_items} 个项目（{len(items['files'])} 个文件，{len(items['folders'])} 个文件夹）")
        
        # 处理每个找到的文件
        for i, file_path in enumerate(items['files'], 1):
            print(f"\n[{i}/{len(items['files'])}] 处理文件: {file_path}")
            process_file(file_path, args)
        
        # 处理每个找到的文件夹
        for i, folder_path in enumerate(items['folders'], 1):
            print(f"\n[{i}/{len(items['folders'])}] 处理文件夹: {folder_path}")
            process_folder(folder_path, args)
            
    finally:
        # 确保释放锁（如果已获取）
        if not args.no_lock:
            release_lock()
            print("\n已释放全局锁")

if __name__ == "__main__":
    main()
