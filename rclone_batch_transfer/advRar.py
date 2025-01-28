#!/usr/bin/env python3
import os
import sys
import shutil
import argparse
import platform
import subprocess
import logging
from pathlib import Path
from typing import List, Tuple

def setup_logging():
    """设置日志配置"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def validate_directory_structure(root_path: Path, logger: logging.Logger) -> Tuple[bool, List[str]]:
    """
    验证目录结构的合法性 - 只检查根目录下是否有文件
    返回 (是否合法, 警告消息列表)
    """
    warnings = []

    # 检查深度1是否存在文件
    for item in root_path.iterdir():
        if item.is_file():
            warnings.append(f"错误: 在根目录 {root_path} 下发现文件: {item.name}")

    return len(warnings) == 0, warnings

def create_rar_archive(folder_path: Path, output_rar: Path, logger: logging.Logger) -> bool:
    """使用rar创建加密压缩文件"""
    try:
        # 准备rar命令
        # -hp: 密码
        # -hen: 加密文件名
        # -rr5: 5%恢复记录
        # -htb: 使用BLAKE2算法
        # -m5: 最佳压缩
        # -s: 创建固实压缩包
        # -oi: 保存相同文件为引用
        # -md1g: 1GB字典大小
        # -r: 递归子目录
        
        # 切换到源文件夹目录
        current_dir = os.getcwd()
        os.chdir(str(folder_path))
        
        # 确保输出路径是绝对路径
        output_rar = output_rar.resolve()
        
        cmd = [
            'rar',
            'a',              # add
            '-hpsouth-plus',  # 设置密码
            '-rr5',           # 5%恢复记录
            '-htb',           # BLAKE2算法
            '-m5',            # 最佳压缩
            '-s',             # 固实压缩
            '-oi',            # 保存相同文件为引用
            '-md1g',          # 1GB字典大小
            '-r',             # 递归子目录
            str(output_rar),  # 输出文件
            '*'               # 压缩当前目录下所有内容
        ]

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
            logger.error(f'RAR命令执行失败，返回码: {returncode}')
            if stderr:
                logger.error(f'错误信息: {stderr}')
            return False

        return True

    except Exception as e:
        logger.error(f'执行RAR命令时发生错误: {str(e)}')
        return False
    finally:
        # 恢复原始工作目录
        os.chdir(current_dir)

def process_folders(root_path: str, delete_source: bool = True, do_check: bool = True):
    """处理指定路径下的文件夹"""
    logger = setup_logging()

    root_path = Path(root_path).resolve()  # 转换为绝对路径
    if not root_path.exists():
        logger.error(f'指定路径不存在: {root_path}')
        return

    # 是否执行预检
    if do_check:
        # 验证目录结构（只检查根目录下是否有文件）
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

    # 处理文件
    folders = [f for f in root_path.iterdir() if f.is_dir()]
    if not folders:
        logger.warning(f'在 {root_path} 中未找到文件夹')
        return

    success_count = 0
    for folder in folders:
        # 创建rar文件，确保它和源文件夹在同一层级
        rar_name = f"{folder.name}.rar"
        rar_path = root_path / rar_name

        logger.info(f'处理文件夹: {folder}')
        logger.info(f'输出rar文件: {rar_path}')

        if rar_path.exists():
            logger.info(f'删除已存在的rar文件: {rar_path}')
            rar_path.unlink()

        if create_rar_archive(folder, rar_path, logger):
            success_count += 1
            if delete_source:
                try:
                    shutil.rmtree(folder)
                    logger.info(f'已删除源文件夹: {folder}')
                except Exception as e:
                    logger.error(f'删除文件夹 {folder} 时发生错误: {str(e)}')
        else:
            logger.error(f'处理文件夹 {folder} 失败')

    logger.info(f'完成！成功处理 {success_count}/{len(folders)} 个文件夹')

def main():
    parser = argparse.ArgumentParser(description='批量将文件夹压缩为rar文件')
    parser.add_argument('path', help='要处理的根目录路径')
    parser.add_argument('-d', '--delete', type=lambda x: str(x).lower() != 'false',
                      default=True, help='压缩后是否删除源文件夹 (默认: true)')
    parser.add_argument('--check', type=lambda x: str(x).lower() != 'false',
                      default=True, help='是否执行预检逻辑 (默认: true)')

    args = parser.parse_args()
    process_folders(args.path, args.delete, args.check)

if __name__ == '__main__':
    main()