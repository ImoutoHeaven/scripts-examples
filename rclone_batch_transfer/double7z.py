#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import shutil
import argparse

def main():
    parser = argparse.ArgumentParser(description="Use 7z to twice-compress each subfolder.")
    parser.add_argument("root_folder", help="Path to the root folder")
    parser.add_argument("-p", "--password", required=True, help="Password for 7z encryption")
    args = parser.parse_args()

    root_folder = os.path.abspath(args.root_folder)
    password = args.password

    # 2.2(1) 预检: root_folder 深度1下只存在文件夹, 不存在文件
    if not os.path.isdir(root_folder):
        print(f"错误: {root_folder} 并不是一个有效文件夹路径。")
        sys.exit(1)

    # 获取 root_folder 下的内容
    root_contents = os.listdir(root_folder)
    if not root_contents:
        print(f"错误: {root_folder} 为空。")
        sys.exit(1)

    # 检查 root_folder 下是否存在任何文件（只允许文件夹）
    for item in root_contents:
        item_path = os.path.join(root_folder, item)
        if os.path.isfile(item_path):
            print("错误: 根目录下存在文件，请确保根目录下只有文件夹而没有文件。")
            sys.exit(1)

    # 2.2(2) 预检: 所有子文件夹内只存在文件而不存在更深的子文件夹
    subfolders = []
    for item in root_contents:
        item_path = os.path.join(root_folder, item)
        if os.path.isdir(item_path):
            subfolders.append(item_path)
            # 检查子文件夹内是否存在子文件夹
            for subitem in os.listdir(item_path):
                subitem_path = os.path.join(item_path, subitem)
                if os.path.isdir(subitem_path):
                    print(f"错误: 子文件夹 {item_path} 下存在文件夹 {subitem_path}，请确保子文件夹内只有文件。")
                    sys.exit(1)

    # 如果所有检查都通过，就进行下一步处理
    # 2.4 对每个子文件夹，用7z压缩为 *.7z，删除原文件夹
    for folder_path in subfolders:
        folder_name = os.path.basename(folder_path)
        # 输出 7z 文件名: folder_name.7z
        first_7z_filename = folder_name + ".7z"
        first_7z_path = os.path.join(root_folder, first_7z_filename)

        # 7z 命令示例: 7z a -p"xxx" -mhe=on -y -mx=0 -ms=off folder_name.7z folder_name
        cmd_compress_1 = [
            "7z", "a",
            f"-p{password}",
            "-mhe=on",
            "-y",          # 自动回答 yes
            "-mx=0",       # 压缩级别为仅存储
            "-ms=off",     # 非固实
            first_7z_path,
            folder_path
        ]
        print(f"执行命令: {' '.join(cmd_compress_1)}")
        ret = subprocess.run(cmd_compress_1)
        if ret.returncode != 0:
            print(f"错误: 无法压缩文件夹 {folder_path}")
            sys.exit(1)

        # 删除原文件夹
        shutil.rmtree(folder_path)

    # 2.5 在上一步完成后, root folder 内应该存在对应数量的7z文件
    # 2.6 对每个7z文件, 再次使用7z进行分卷压缩（4G/卷），加密header，并改名
    seven_z_files = [
        f for f in os.listdir(root_folder)
        if f.endswith(".7z") and os.path.isfile(os.path.join(root_folder, f))
    ]

    for f7z in seven_z_files:
        original_7z_path = os.path.join(root_folder, f7z)
        # 原文件名去掉 .7z 后缀(保留)
        # 比如 folder1.7z -> folder1.7z 作为“基名”
        base_name = f7z  # e.g. "folder1.7z"

        # 为了避免 7z 二次压缩时生成的文件名与原文件冲突，我们先使用一个临时文件名
        # 例如 temp_compress.7z，再进行重命名
        temp_compress = "temp_compress.7z"  # 临时输出文件名
        temp_compress_path = os.path.join(root_folder, temp_compress)

        # 二次 7z 分卷压缩命令
        cmd_compress_2 = [
            "7z", "a",
            f"-p{password}",
            "-mhe=on",
            "-v4g",    # 4GB 一卷
            "-y",
            "-mx=0",   # 仅存储
            "-ms=off", # 非固实
            temp_compress_path,
            original_7z_path
        ]
        print(f"执行命令: {' '.join(cmd_compress_2)}")
        ret = subprocess.run(cmd_compress_2)
        if ret.returncode != 0:
            print(f"错误: 无法二次压缩文件 {original_7z_path}")
            sys.exit(1)

        # 删除第一次压缩的.7z文件
        os.remove(original_7z_path)

        # 检查临时文件命名情况：
        #  - 如果分卷只有一个，则 7z 可能只生成 temp_compress.7z
        #  - 如果分卷多于一个，则会有 temp_compress.7z.001, temp_compress.7z.002, ...
        # 我们需要重命名它们为 base_name.001, base_name.002, ...
        # 注意：base_name = folder1.7z，目标是 folder1.7z.001 ...
        # 所以最终文件应形如 folder1.7z.001, folder1.7z.002, ...
        # 如果只有一个分卷，则把 temp_compress.7z -> folder1.7z.001

        # step1: 遍历 root_folder 下所有文件, 找到 temp_compress.7z* 开头的文件
        volume_files = []
        for volume_candidate in os.listdir(root_folder):
            if volume_candidate.startswith(temp_compress):  # temp_compress.7z  or temp_compress.7z.001 ...
                volume_files.append(volume_candidate)

        # 如果分卷只有一个, 7z 可能直接生成 temp_compress.7z
        if len(volume_files) == 1 and volume_files[0] == "temp_compress.7z":
            # 把 temp_compress.7z -> base_name.001
            single_volume_old = os.path.join(root_folder, "temp_compress.7z")
            single_volume_new = os.path.join(root_folder, base_name + ".001")
            os.rename(single_volume_old, single_volume_new)
        else:
            # 多个分卷: temp_compress.7z.001, temp_compress.7z.002, ...
            for vf in volume_files:
                old_path = os.path.join(root_folder, vf)
                # vf 形如: temp_compress.7z.001
                # 我们只需要把 temp_compress.7z 部分替换成 base_name
                # 在严格情况下可用字符串切割，但这里简单处理
                suffix_part = vf.replace(temp_compress, "")
                # suffix_part 例如 ".7z.001" 或者 ".7z.002"
                new_name = base_name + suffix_part
                new_path = os.path.join(root_folder, new_name)
                os.rename(old_path, new_path)

    print("全部压缩与分卷操作完成。")

if __name__ == "__main__":
    main()
