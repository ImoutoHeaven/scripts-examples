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

    # dst 已存在并且是目录 => 逐项合并
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


def rename_folder_with_childname(parent_folder, child_name):
    """
    将父目录 parent_folder 重命名为 parent_folder + " " + child_name
    但如果发现 child_name 已经包含在 parent_folder 名中（作为整词），则跳过。
    如重名或出错，也跳过并发出警告或错误日志。

    返回重命名后的新路径；失败或跳过则返回原路径。
    """
    parent_parent = os.path.dirname(parent_folder)
    base_parent = os.path.basename(parent_folder)

    # 为了“整词匹配”做简单处理：在前后都加空格，再检查子目录名
    spaced_parent = f" {base_parent} "
    spaced_child = f" {child_name} "

    # 若已包含子目录名，则跳过追加
    if spaced_child in spaced_parent:
        logger.info(f"检测到目录名 '{child_name}' 已包含在 '{base_parent}' 中，跳过追加。")
        new_name = base_parent
    else:
        new_name = base_parent + " " + child_name

    new_path = os.path.join(parent_parent, new_name)

    # 若新路径已存在，则跳过重命名
    if os.path.exists(new_path):
        logger.warning(f"目标名称已存在，跳过重命名: {new_path}")
        return parent_folder

    # 尝试进行重命名
    try:
        os.rename(parent_folder, new_path)
        logger.info(f"将目录 {parent_folder} 重命名为 {new_path}")
        return new_path
    except Exception as e:
        logger.error(f"重命名失败: {parent_folder} -> {new_path}, 错误: {e}")
        return parent_folder


def flatten_shell(folder, depth=0, keep_name=False):
    """
    扁平化“无意义外壳”。
      - 当只包含1个子目录时，会把子目录的所有内容上移到父目录，然后(可选)对父目录重命名（去重）。
      - 当文件或目录名冲突时，跳过移动。
      - 当目录为空时，若非最外层 (depth>0)，自动删除。
      - 若 keep_name=True，则对每层目录名做去重拼接。

    返回 (final_folder_path, changed):
      final_folder_path: 可能被重命名后的真实目录路径
      changed: 是否在本次调用中对结构作了更改 (bool)
    """
    logger.info(f"开始处理目录 (深度={depth}): {folder}")

    # 若 folder 不存在(可能前面已被删除/重命名)，就直接返回
    if not os.path.exists(folder):
        logger.warning(f"目录不存在或已被删除: {folder}")
        return folder, False

    items = os.listdir(folder)
    changed = False

    # (1) 若 >=2 个条目 => 视为内容目录，不动
    if len(items) >= 2:
        logger.info(f"目录包含多个项目，保持不变: {folder}")
        return folder, False

    # (2) 若目录为空
    if len(items) == 0:
        if depth > 0:
            try:
                os.rmdir(folder)
                logger.info(f"删除空目录: {folder}")
                return folder, True
            except OSError:
                logger.error(f"删除空目录失败: {folder}")
        return folder, False

    # (3) 只有 1 个条目
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

            # 尝试删除空的父目录(因为把唯一文件上移后，这里就空了)
            try:
                os.rmdir(folder)
                logger.info(f"删除空壳目录: {folder}")
                changed = True
            except OSError:
                logger.debug(f"目录非空或已删除: {folder}")

        return folder, changed

    # 3b) 若唯一条目是目录 => 将其内容上移到当前 folder
    if os.path.isdir(only_item_path):
        logger.info(f"处理单个子目录: {only_item_path}")
        moved_any = False

        for sub in os.listdir(only_item_path):
            src = os.path.join(only_item_path, sub)
            dst = os.path.join(folder, sub)
            if os.path.exists(dst):
                # 若 dst 存在且都是目录，则合并
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

        old_folder_path = folder
        new_folder_path = folder

        # **先尝试删除空的子目录**，防止在父目录重命名后，这个子目录找不到路径
        try:
            os.rmdir(only_item_path)
            logger.info(f"删除已清空的子目录: {only_item_path}")
            moved_any = True
        except OSError:
            logger.debug(f"子目录非空或已删除: {only_item_path}")

        # 若需要保留子目录名称，并且确实移动了内容 => 重命名父目录
        if keep_name and moved_any:
            tmp_folder = rename_folder_with_childname(old_folder_path, only_item)
            if tmp_folder != old_folder_path:
                changed = True
                new_folder_path = tmp_folder
                folder = tmp_folder

        changed = changed or moved_any

        # 如果确实有移动/合并/重命名 => 可能还能继续扁平化
        if moved_any:
            logger.info(f"重新检查目录是否可以继续扁平化: {new_folder_path}")
            final_path, sub_changed = flatten_shell(new_folder_path, depth, keep_name=keep_name)
            changed = changed or sub_changed
            return final_path, changed

        return new_folder_path, changed

    # 如果唯一条目既不是文件也不是文件夹(极少情况，如符号链接等)，则不动
    return folder, changed


def process_root_dir(root_dir, keep_name=False):
    """
    处理根目录下的所有子目录。
    多次调用 flatten_shell，直至目录不再变化。
    """
    logger.info(f"开始处理根目录: {root_dir}")

    for entry in os.listdir(root_dir):
        sub_path = os.path.join(root_dir, entry)
        if os.path.isdir(sub_path):
            logger.info(f"处理子目录: {sub_path}")
            iteration = 1
            while True:
                logger.info(f"开始第 {iteration} 次扁平化尝试: {sub_path}")
                new_sub_path, changed = flatten_shell(sub_path, depth=0, keep_name=keep_name)

                if changed:
                    sub_path = new_sub_path
                    iteration += 1
                else:
                    logger.info(f"目录 {sub_path} 已完成扁平化")
                    break


def main():
    """
    命令行用法示例:
      python script.py C:/TestRoot --keep-name=true
    """
    if len(sys.argv) < 2:
        logger.error(f"用法: python {sys.argv[0]} /path/to/root_dir [--keep-name=true/false]")
        sys.exit(1)

    root_dir = None
    keep_name = False

    for arg in sys.argv[1:]:
        if arg.startswith("--keep-name"):
            kv = arg.split("=")
            if len(kv) == 2:
                val = kv[1].lower().strip()
                if val == "true":
                    keep_name = True
                elif val == "false":
                    keep_name = False
        else:
            if root_dir is None:
                root_dir = arg

    if not root_dir:
        logger.error(f"用法: python {sys.argv[0]} /path/to/root_dir [--keep-name=true/false]")
        sys.exit(1)

    if not os.path.isdir(root_dir):
        logger.error(f"{root_dir} 不是有效目录")
        sys.exit(1)

    logger.info("=== 目录扁平化工具启动 ===")
    logger.info(f"目标根目录: {root_dir}")
    logger.info(f"keep_name 参数: {keep_name}")

    process_root_dir(root_dir, keep_name=keep_name)

    logger.info("=== 处理完成 ===")


if __name__ == "__main__":
    main()
