#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import logging

# 配置日志输出
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def merge_directory(src, dst):
    """
    将 src 目录的所有内容合并到 dst 目录中。
    """
    logger.info(f"开始合并目录: {src} -> {dst}")
    
    if not os.path.exists(dst):
        logger.info(f"目标目录不存在，直接移动: {src} -> {dst}")
        shutil.move(src, dst)
        return

    if not os.path.isdir(dst):
        logger.warning(f"目标已存在且是文件，跳过合并: {dst}")
        return

    # dst 是已存在的目录 => 逐项合并
    logger.info(f"目标是已存在的目录，开始逐项合并: {dst}")
    for item in os.listdir(src):
        src_item = os.path.join(src, item)
        dst_item = os.path.join(dst, item)

        if os.path.isdir(src_item):
            if os.path.exists(dst_item):
                if os.path.isdir(dst_item):
                    logger.info(f"发现同名目录，进行递归合并: {dst_item}")
                    merge_directory(src_item, dst_item)
                else:
                    logger.warning(f"同名文件已存在，跳过目录合并: {dst_item}")
            else:
                logger.info(f"移动目录: {src_item} -> {dst_item}")
                shutil.move(src_item, dst_item)
        else:
            if os.path.exists(dst_item):
                logger.warning(f"同名文件已存在，跳过: {dst_item}")
            else:
                logger.info(f"移动文件: {src_item} -> {dst_item}")
                shutil.move(src_item, dst_item)

    # 如果 src 现在空了，删掉
    try:
        os.rmdir(src)
        logger.info(f"删除空源目录: {src}")
    except OSError:
        logger.debug(f"源目录非空或已删除: {src}")


def flatten_shell(folder, depth=0):
    """
    扁平化移除"无意义外壳"。
    """
    logger.info(f"开始处理目录 (深度={depth}): {folder}")
    changed = False
    items = os.listdir(folder)

    # 1) 若 >=2 个条目 => 内容目录，不动
    if len(items) >= 2:
        logger.info(f"目录包含多个项目，保持不变: {folder}")
        return False

    # 2) 若目录为空
    if len(items) == 0:
        if depth > 0:
            try:
                os.rmdir(folder)
                logger.info(f"删除空目录: {folder}")
                changed = True
            except OSError:
                logger.error(f"删除空目录失败: {folder}")
        return changed

    # 3) 只有 1 个条目
    only_item = items[0]
    only_item_path = os.path.join(folder, only_item)
    logger.info(f"发现单个项目: {only_item_path}")

    # 3a) 若唯一条目是文件
    if os.path.isfile(only_item_path):
        if depth > 0:
            parent_folder = os.path.dirname(folder)
            target_file = os.path.join(parent_folder, only_item)
            
            if os.path.exists(target_file):
                logger.warning(f"上移文件时发生冲突，跳过: {target_file}")
            else:
                try:
                    logger.info(f"上移文件: {only_item_path} -> {parent_folder}")
                    shutil.move(only_item_path, parent_folder)
                    changed = True
                except Exception as e:
                    logger.error(f"移动文件失败: {only_item_path} -> {parent_folder}, 错误: {e}")

            try:
                os.rmdir(folder)
                logger.info(f"删除空壳目录: {folder}")
                changed = True
            except OSError:
                logger.debug(f"目录非空或已删除: {folder}")
        return changed

    # 3b) 若唯一条目是目录 => 将其内容上移到当前 folder
    if os.path.isdir(only_item_path):
        logger.info(f"处理单个子目录: {only_item_path}")
        moved_any = False

        for sub in os.listdir(only_item_path):
            src = os.path.join(only_item_path, sub)
            dst = os.path.join(folder, sub)

            if os.path.exists(dst):
                if os.path.isdir(src) and os.path.isdir(dst):
                    logger.info(f"合并同名目录: {src} -> {dst}")
                    merge_directory(src, dst)
                    moved_any = True
                elif os.path.isdir(src) and not os.path.isdir(dst):
                    logger.warning(f"同名文件已存在，跳过目录合并: {dst}")
                elif not os.path.isdir(src) and os.path.isdir(dst):
                    logger.warning(f"同名目录已存在，跳过文件: {dst}")
                else:
                    logger.warning(f"同名文件已存在，跳过: {dst}")
            else:
                logger.info(f"移动项目: {src} -> {dst}")
                shutil.move(src, dst)
                moved_any = True

        try:
            os.rmdir(only_item_path)
            logger.info(f"删除已清空的子目录: {only_item_path}")
            moved_any = True
        except OSError:
            logger.debug(f"子目录非空或已删除: {only_item_path}")

        changed = changed or moved_any

        if moved_any:
            logger.info(f"重新检查目录是否可以继续扁平化: {folder}")
            again = flatten_shell(folder, depth)
            changed = changed or again

        return changed

    return changed


def process_root_dir(root_dir):
    """
    处理根目录下的所有子目录。
    """
    logger.info(f"开始处理根目录: {root_dir}")
    
    for entry in os.listdir(root_dir):
        sub_path = os.path.join(root_dir, entry)
        if os.path.isdir(sub_path):
            logger.info(f"处理子目录: {sub_path}")
            iteration = 1
            while True:
                logger.info(f"开始第 {iteration} 次扁平化尝试: {sub_path}")
                if not flatten_shell(sub_path, depth=0):
                    logger.info(f"目录 {sub_path} 已完成扁平化")
                    break
                iteration += 1


def main():
    if len(sys.argv) != 2:
        logger.error(f"用法: python {sys.argv[0]} /path/to/root_dir")
        sys.exit(1)

    root_dir = sys.argv[1]
    if not os.path.isdir(root_dir):
        logger.error(f"{root_dir} 不是有效目录")
        sys.exit(1)

    logger.info("=== 目录扁平化工具启动 ===")
    logger.info(f"目标根目录: {root_dir}")
    
    process_root_dir(root_dir)
    
    logger.info("=== 处理完成 ===")


if __name__ == "__main__":
    main()
