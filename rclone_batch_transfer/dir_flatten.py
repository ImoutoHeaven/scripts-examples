#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil

def flatten_shell(folder, depth=0):
    """
    扁平化移除“无意义的外壳”目录。
    :param folder: 要处理的目录
    :param depth: 当前目录相对于“游戏顶层目录”的深度。
                  depth=0 => folder是root_dir下的直接子目录（一个游戏/文件集的顶层）。
                  depth>0 => folder是更深一层的嵌套目录（潜在的无意义壳）。
    """
    items = os.listdir(folder)

    # 如果此目录包含 >=2 个条目 => 视为“内容目录”，停止扁平化
    if len(items) >= 2:
        return

    # 如果此目录为空
    if len(items) == 0:
        # 对于“深层壳”可直接删除
        if depth > 0:
            try:
                os.rmdir(folder)
                print(f"[删除空目录] {folder}")
            except OSError as e:
                print(f"[删除空目录失败] {folder}, 原因: {e}")
        else:
            # depth=0 => 顶层目录且为空，通常不动它，防止误删可能还要用的文件夹
            pass
        return

    # 现在只剩下 len(items) == 1 的情况
    only_item = items[0]
    only_item_path = os.path.join(folder, only_item)

    # 如果唯一条目是“文件”
    if os.path.isfile(only_item_path):
        if depth > 0:
            # 将此唯一文件“上移”到父目录
            parent_folder = os.path.dirname(folder)
            try:
                shutil.move(only_item_path, parent_folder)
                print(f"[上移文件] {only_item_path} => {parent_folder}")
                # 移动后若 folder 为空，可删
                try:
                    os.rmdir(folder)
                    print(f"[删除外壳目录] {folder}")
                except OSError as e:
                    print(f"[删除外壳目录失败] {folder}, 原因: {e}")
            except Exception as e:
                print(f"[移动文件时出现错误] {only_item_path} => {parent_folder}, 错误: {e}")
        else:
            # depth=0 => 顶层目录只有一个文件，不要把它扔到 root_dir
            # 这个场景下就保持不动，防止把所有单文件都直接丢进root_dir。
            pass
        return

    # 如果唯一条目是“目录”
    if os.path.isdir(only_item_path):
        # 这里不再判断它是否是“内容目录”，只要父目录只有它一个子目录，我们就把它的内容上移
        # 这样就能把“subFolder2”中的多个文件 1.jpg,2.jpg,3.jpg 移到“subFolder1”。
        for c in os.listdir(only_item_path):
            src = os.path.join(only_item_path, c)
            dst = os.path.join(folder, c)
            try:
                shutil.move(src, dst)
                print(f"[上移内容] {src} => {dst}")
            except Exception as e:
                print(f"[移动内容时出现错误] {src} => {dst}, 错误: {e}")

        # 搬空后，尝试删除 only_item_path
        try:
            os.rmdir(only_item_path)
            print(f"[删除空目录] {only_item_path}")
        except OSError:
            pass

        # 现在 folder 里已经多了刚刚上移的内容 -> 重新判断一次
        flatten_shell(folder, depth)
        return


def process_root_dir(root_dir):
    """
    对 root_dir 下的所有“游戏顶层目录”进行扁平化处理。
    注：不会把“游戏内容”直接移到 root_dir，以防多个游戏/文件集混杂。
    """
    for entry in os.listdir(root_dir):
        sub_path = os.path.join(root_dir, entry)
        if os.path.isdir(sub_path):
            flatten_shell(sub_path, depth=0)
            # 若你担心一次 flatten_shell 不够彻底，可再重复调用一次或多次
            # flatten_shell(sub_path, depth=0)


def main():
    if len(sys.argv) != 2:
        print(f"用法：python {sys.argv[0]} /path/to/root_dir")
        sys.exit(1)

    root_dir = sys.argv[1]
    if not os.path.isdir(root_dir):
        print(f"[错误] {root_dir} 不是一个有效目录")
        sys.exit(1)

    process_root_dir(root_dir)
    print("处理完成。可以多次运行脚本查看是否还有可移除的外壳。")


if __name__ == "__main__":
    main()
