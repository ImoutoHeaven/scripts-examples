#!/usr/bin/env python3
import os
import sys
import shutil
import argparse
import subprocess
import logging
import time
import tempfile
from pathlib import Path
from typing import List, Tuple

def setup_logging():
    """设置日志配置"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger(__name__)

def acquire_lock(lock_file: Path, logger: logging.Logger, wait_interval: int = 1):
    """尝试获取锁；如果锁文件存在则等待，直到锁被释放"""
    while True:
        try:
            # 使用 O_EXCL 和 O_CREAT 确保原子性创建锁文件
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            logger.info(f"成功获取锁: {lock_file}")
            break
        except FileExistsError:
            logger.info(f"检测到锁 {lock_file} 存在，等待 {wait_interval} 秒...")
            time.sleep(wait_interval)

def release_lock(lock_file: Path, logger: logging.Logger):
    """释放锁文件"""
    try:
        if lock_file.exists():
            lock_file.unlink()
            logger.info(f"已释放锁: {lock_file}")
    except Exception as e:
        logger.error(f"释放锁 {lock_file} 时出错: {str(e)}")

def validate_directory_structure(root_path: Path, logger: logging.Logger) -> Tuple[bool, List[str]]:
    """
    验证目录结构的合法性 - 只检查根目录下是否有文件
    返回 (是否合法, 警告消息列表)
    """
    warnings = []
    for item in root_path.iterdir():
        if item.is_file():
            warnings.append(f"错误: 在根目录 {root_path} 下发现文件: {item.name}")
    return len(warnings) == 0, warnings

def normalize_md(md: str) -> str:
    """
    将用户输入的字典大小参数归一化为 RAR 可识别的格式  
    例如："32mb" 转换为 "32m", "1gb" 转换为 "1g"
    """
    md = md.lower().strip()
    if md.endswith("mb"):
        md = md[:-2] + "m"
    elif md.endswith("gb"):
        md = md[:-2] + "g"
    return md

def create_rar_archive(folder_path: Path, output_rar: Path, logger: logging.Logger,
                       delete_source: bool = False, 
                       password: str = "south-plus",
                       ignore_password: bool = False,
                       plain_metadata: bool = False,
                       comment: str = None,
                       lock: bool = False,
                       rr: int = 5, 
                       m: int = 5, 
                       solid: bool = True, 
                       md: str = "1g") -> bool:
    """
    使用 RAR 创建加密压缩文件。
    
    参数：
      folder_path: 要压缩的子文件夹（压缩时会切换到该目录下）
      output_rar: 生成的 .rar 文件的绝对路径
      delete_source: 如果为 True，则使用 RAR 的 -df 参数在压缩后删除源文件内容
                     （注意：该参数仅删除文件，目录需要额外删除）
      password: 压缩密码 (默认: "south-plus")
      ignore_password: 如果为 True，则不加密文件
      plain_metadata: 如果为 True 且未忽略密码，则不加密文件头 (使用 -p 而非 -hp)
      comment: 如果不为 None，则添加注释到压缩文件中
      lock: 如果为 True，则锁定压缩文件（添加 -ol 参数），默认不锁定
      rr: 恢复记录百分比 (对应 -rr 参数，默认: 5；若为 0 则不添加该参数)
      m: 压缩级别 (对应 -m 参数，默认: 5；注：m 0 表示仅存储，不进行压缩)
      solid: 是否启用固实压缩 (对应 -s 参数，默认: True，即启用固实压缩)
      md: 字典大小 (对应 -md 参数，默认: "1g", 可选如 "32mb", "128mb", "1g/1gb" 等)
    """
    comment_temp_file = None  # 用于存放注释内容的临时文件
    try:
        # 保存当前工作目录，并切换到源文件夹下（便于使用通配符压缩当前目录下所有内容）
        current_dir = os.getcwd()
        os.chdir(str(folder_path))
        output_rar = output_rar.resolve()

        normalized_md = normalize_md(md)

        # 构造 RAR 命令列表
        cmd = ['rar', 'a']

        # 1. 密码相关设置：如果未指定忽略密码，则加入密码选项
        if not ignore_password:
            if plain_metadata:
                # -p 表示仅加密文件内容，不加密文件头
                cmd.append(f"-p{password}")
            else:
                # -hp 表示同时加密文件数据和文件头
                cmd.append(f"-hp{password}")

        # 2. 恢复记录：仅当 rr > 0 时添加该参数
        if rr > 0:
            cmd.append(f"-rr{rr}")

        # 3. 固定参数：BLAKE2 算法
        cmd.append('-htb')

        # 4. 压缩级别
        cmd.append(f"-m{m}")  # 注：m=0 表示仅存储，不进行压缩

        # 5. 固实压缩：仅当 solid 为 True 时添加 -s 参数
        if solid:
            cmd.append('-s')

        # 6. 保存相同文件为引用
        cmd.append('-oi')

        # 7. 字典大小
        cmd.append(f"-md{normalized_md}")

        # 8. 如果要求删除源文件，则在压缩后删除文件内容
        if delete_source:
            cmd.append('-df')

        # 9. 如果需要锁定压缩文件，则添加 -ol 参数
        if lock:
            cmd.append('-ol')

        # 10. 如果需要添加注释，则先将注释写入临时文件，并添加 -z 参数
        if comment:
            comment_temp_file = tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="utf-8", suffix=".txt")
            comment_temp_file.write(comment)
            comment_temp_file.close()
            cmd.append(f"-z{comment_temp_file.name}")

        # 11. 递归子目录、输出文件路径、以及压缩当前目录下所有内容
        cmd.extend([
            '-r',             # 递归子目录
            str(output_rar),  # 输出 .rar 文件路径
            '*'               # 压缩当前目录下所有内容
        ])

        logger.info(f'执行命令: {" ".join(cmd)}')

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                logger.info(output.strip())

        returncode = process.poll()
        _, stderr = process.communicate()

        if returncode != 0:
            logger.error(f'RAR 命令执行失败，返回码: {returncode}')
            if stderr:
                logger.error(f'错误信息: {stderr}')
            return False

        return True

    except Exception as e:
        logger.error(f'执行 RAR 命令时发生错误: {str(e)}')
        return False
    finally:
        # 恢复原来的工作目录
        os.chdir(current_dir)
        # 删除临时的注释文件（如果存在）
        if comment_temp_file is not None:
            try:
                os.remove(comment_temp_file.name)
            except Exception as e:
                logger.error(f'删除临时注释文件 {comment_temp_file.name} 时发生错误: {str(e)}')

def process_folders(root_path: str, delete_source: bool = True, do_check: bool = True,
                    logger: logging.Logger = None, 
                    password: str = "south-plus",
                    ignore_password: bool = False,
                    plain_metadata: bool = False,
                    comment: str = None,
                    lock: bool = False,
                    rr: int = 5, 
                    m: int = 5, 
                    solid: bool = True, 
                    md: str = "1g"):
    """处理指定路径下的子文件夹，将每个文件夹压缩为 .rar 文件，并根据设置删除源文件夹"""
    if logger is None:
        logger = setup_logging()

    root_path = Path(root_path).resolve()
    if not root_path.exists():
        logger.error(f'指定路径不存在: {root_path}')
        return

    if do_check:
        logger.info("开始验证目录结构...")
        is_valid, warnings = validate_directory_structure(root_path, logger)
        if not is_valid:
            logger.error("发现以下问题:")
            for warning in warnings:
                logger.error(warning)
            logger.error("请处理以上问题后再次运行脚本")
            return
        logger.info("目录结构验证通过，开始处理文件...")
    else:
        logger.info("跳过预检，直接开始处理文件...")

    folders = [f for f in root_path.iterdir() if f.is_dir()]
    if not folders:
        logger.warning(f'在 {root_path} 中未找到文件夹')
        return

    success_count = 0
    for folder in folders:
        rar_name = f"{folder.name}.rar"
        rar_path = root_path / rar_name

        logger.info(f'处理文件夹: {folder}')
        logger.info(f'输出 rar 文件: {rar_path}')

        if rar_path.exists():
            logger.info(f'删除已存在的 rar 文件: {rar_path}')
            rar_path.unlink()

        if create_rar_archive(folder, rar_path, logger, delete_source=delete_source,
                              password=password,
                              ignore_password=ignore_password,
                              plain_metadata=plain_metadata,
                              comment=comment,
                              lock=lock,
                              rr=rr, m=m, solid=solid, md=md):
            success_count += 1
            if delete_source:
                try:
                    # RAR 的 -df 参数仅删除文件内容，若该文件夹为空则删除该空文件夹
                    if not any(folder.iterdir()):
                        folder.rmdir()
                        logger.info(f'已删除空源文件夹: {folder}')
                    else:
                        logger.warning(f'文件夹 {folder} 仍不为空，未删除')
                except Exception as e:
                    logger.error(f'删除空文件夹 {folder} 时发生错误: {str(e)}')
        else:
            logger.error(f'处理文件夹 {folder} 失败')

    logger.info(f'完成！成功处理 {success_count}/{len(folders)} 个文件夹')

def main():
    parser = argparse.ArgumentParser(description='批量将文件夹压缩为 RAR 文件')
    parser.add_argument('path', help='要处理的根目录路径')
    parser.add_argument('-d', '--delete', type=lambda x: str(x).lower() != 'false',
                        default=True, help='压缩后是否删除源文件夹 (默认: true)')
    parser.add_argument('--check', type=lambda x: str(x).lower() != 'false',
                        default=True, help='是否执行预检逻辑 (默认: true)')

    # 以下参数用于自定义 RAR 压缩选项
    parser.add_argument('--password', default="south-plus",
                        help='设置压缩密码 (默认: south-plus)')
    parser.add_argument('--ignore-password', action="store_true",
                        help='如果指定则不对文件加密')
    parser.add_argument('--plain-metadata', action="store_true",
                        help='如果指定则仅加密文件内容，不加密文件头 (使用 -p 而非 -hp)')
    parser.add_argument('--comment', type=str, default=None,
                        help='添加注释到压缩文件 (支持任意字符串)')
    parser.add_argument('--lock', action="store_true", default=False,
                        help='如果指定则锁定压缩文件 (默认不锁定)')
    parser.add_argument('--rr', type=int, default=5,
                        help='恢复记录百分比 (默认: 5，若为 0 则不添加恢复记录)')
    parser.add_argument('--m', type=int, default=5,
                        help='压缩级别 0-5 (默认: 5；注意: m=0 表示仅存储，不进行压缩)')
    parser.add_argument('--solid', type=lambda x: str(x).lower() != 'false',
                        default=True, help='是否使用固实压缩 (默认: true)')
    parser.add_argument('--md', default="1g",
                        help='字典大小 (默认: 1g, 可选如 32mb, 128mb, 1g/1gb 等)')

    args = parser.parse_args()
    logger = setup_logging()

    # 锁文件放置在系统临时目录下，保证跨平台
    lock_file = Path(tempfile.gettempdir()) / "rar_script.lock"
    acquire_lock(lock_file, logger)

    try:
        process_folders(args.path,
                        delete_source=args.delete,
                        do_check=args.check,
                        logger=logger,
                        password=args.password,
                        ignore_password=args.ignore_password,
                        plain_metadata=args.plain_metadata,
                        comment=args.comment,
                        lock=args.lock,
                        rr=args.rr,
                        m=args.m,
                        solid=args.solid,
                        md=args.md)
    finally:
        release_lock(lock_file, logger)

if __name__ == '__main__':
    main()
