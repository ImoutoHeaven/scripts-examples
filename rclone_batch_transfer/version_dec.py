#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import shutil

def lcs_length(s1, s2):
    """
    计算字符串 s1 和 s2 的最长公共子序列长度（严格保持顺序）。
    """
    len1, len2 = len(s1), len(s2)
    dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            if s1[i-1] == s2[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
            else:
                dp[i][j] = max(dp[i-1][j], dp[i][j-1])
    return dp[len1][len2]

def similarity_ratio(s1, s2):
    """
    用 LCS 算法计算 s1, s2 的相似度，范围 [0,1].
    similarity = LCS_len / max(len(s1), len(s2))
    """
    if not s1 or not s2:
        return 0.0
    lcs_len = lcs_length(s1, s2)
    return lcs_len / max(len(s1), len(s2))

def parse_version_tags(name):
    """
    从文件名中搜集所有版本号标签, 返回列表.
    例如: "[v2]" "[v10.1]" 等，不区分大小写。
    """
    # 匹配形如 [v2], [v10], [v10.1], [v1.99] 等
    pattern = re.compile(r'\[v(\d+(?:\.\d+)?)\]', re.IGNORECASE)
    return pattern.findall(name)

def parse_timestamp_tags(name):
    """
    从文件名中搜集所有时间戳标签, 返回列表.
    支持形如 [20240102] [2024010201] 等 6~10位数字的情况
    （主要是 8 位 YYYYMMDD 或 10 位 YYYYMMDDHH）。
    """
    pattern = re.compile(r'\[(\d{6,10})\]')
    return pattern.findall(name)

def extract_extension(name):
    """
    提取文件扩展名（不含 '.'），如果是文件夹则返回空字符串。
    这里简单通过是否含 '.' 且不在最前面来判断，可按需改进。
    """
    if '.' in name and not name.startswith('.'):
        return name.rsplit('.', 1)[-1]
    return ''

def remove_brackets_content(name):
    """
    去除方括号 [xxx] 及圆括号 (xxx) 的所有内容。
    """
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    return name

def parse_sequel_number(clean_title):
    """
    尝试解析“末尾续作编号”(整数)，若存在则返回 int，否则返回 None。
    示例:
      '女子快乐调教挠痒开发2' => sequel_num = 2
      '女子快乐调教挠痒开发' => sequel_num = None
    这里仅用最简单的逻辑：结尾若是纯数字则提取。
    """
    clean_title = clean_title.strip()
    match = re.search(r'(\d+)$', clean_title)
    if match:
        s = match.group(1)
        try:
            return int(s)
        except:
            pass
    return None

def get_simplified_name_for_similarity(name):
    """
    取得最原始的“去方括号、去圆括号、去扩展名、去空格”的名称，用于后续判断。
    不考虑续作数字处理，先把所有可能干扰的移除。
    """
    ext = extract_extension(name)
    if ext:
        dot_index = name.rfind('.' + ext)
        if dot_index != -1:
            name = name[:dot_index]

    # 去除方括号和圆括号
    name = remove_brackets_content(name)
    # 去除所有空格
    name = re.sub(r'\s+', '', name)
    return name

def parse_item_info(full_path, root_folder):
    """
    解析一个项目（文件或文件夹）信息。
    返回字典:
    {
      "full_path": 项目绝对路径,
      "root_dir": 该项目所在目录,
      "name": 项目的原始名称,
      "is_dir": 是否是文件夹,
      "versions": list of float,  # 可能有多个
      "timestamps": list of str,  # 可能有多个
      "similarity_name": 用于分组时计算相似度的字符串(已去括号内容及扩展名, 但不含末尾续作数字),
      "sequel_num": 末尾续作数字(若有则int, 否则None),
      "file_size": 文件大小(若为文件则为 int, 若为文件夹则为 None)
    }
    """
    base_name = os.path.basename(full_path)
    is_dir = os.path.isdir(full_path)

    # 1) 版本号和时间戳
    vs_str = parse_version_tags(base_name)  # ["2", "10.1", ...]
    ts_str = parse_timestamp_tags(base_name)  # ["20240102", "20231230", ...]

    # 转化版本号字符串为 float，便于比较
    def to_float(x):
        try:
            return float(x)
        except:
            return 0.0
    versions = [to_float(v) for v in vs_str]

    # 2) 用于相似度比对的字符串
    raw_for_similarity = get_simplified_name_for_similarity(base_name)

    # 3) 分析末尾续作数字
    sequel_num = parse_sequel_number(raw_for_similarity)
    similarity_name = raw_for_similarity
    if sequel_num is not None:
        similarity_name = re.sub(r'\d+$', '', similarity_name).strip()

    # 4) 文件大小（文件夹则为 None）
    file_size = None
    if not is_dir:
        try:
            file_size = os.path.getsize(full_path)
        except:
            file_size = None

    info = {
        "full_path": full_path,
        "root_dir": os.path.dirname(full_path),
        "name": base_name,
        "is_dir": is_dir,
        "versions": versions,
        "timestamps": ts_str,
        "similarity_name": similarity_name,
        "sequel_num": sequel_num,
        "file_size": file_size
    }
    return info

def are_same_root_work(itemA, itemB, threshold=0.85):
    """
    判断两个item是否为“同一作品的不同版本”，而非“续作”。
    规则：
      1) 如果 sequel_num 不同，则视为不同作品（前作/续作） => 返回 False
      2) 否则比较 similarity_name 的相似度 >= threshold => True
    """
    # 若续作号不同，则不归入同一组
    if itemA["sequel_num"] != itemB["sequel_num"]:
        return False

    s1 = itemA["similarity_name"]
    s2 = itemB["similarity_name"]
    sim = similarity_ratio(s1, s2)
    if sim >= threshold:
        return True
    return False

def build_groups(items, threshold=0.85):
    """
    将 items 根据 are_same_root_work(...) 进行分组 (BFS)。
    即：只有当 sequel_num 一致 且 similarity_name 的相似度>=阈值 才会被分入同一组。
    """
    visited = [False] * len(items)
    groups = []

    for i in range(len(items)):
        if visited[i]:
            continue
        # BFS
        queue = [i]
        visited[i] = True
        group = [i]
        while queue:
            cur = queue.pop(0)
            for j in range(len(items)):
                if not visited[j]:
                    if are_same_root_work(items[cur], items[j], threshold=threshold):
                        visited[j] = True
                        queue.append(j)
                        group.append(j)
        groups.append(group)

    return groups

def move_by_version(group_items, warnings):
    """
    在全都有版本号、无时间戳的组里，选出最大版本文件保留，其余移动到temp/
    """
    max_version = -1.0
    best_item = None
    for it in group_items:
        local_max = max(it["versions"])  # 若有多个版本标签，取其中最大的
        if local_max > max_version:
            max_version = local_max
            best_item = it

    if best_item:
        for it in group_items:
            if it is best_item:
                continue
            do_move_to_temp(it, warnings)

def move_by_timestamp(group_items, warnings):
    """
    在全都有时间戳、无版本号的组里，选出最新时间戳(数值越大越新)保留，其余移到temp/
    """
    max_ts = -1
    best_item = None
    for it in group_items:
        try:
            val = int(it["timestamps"][0])
        except:
            val = -1
        if val > max_ts:
            max_ts = val
            best_item = it

    if best_item:
        for it in group_items:
            if it is best_item:
                continue
            do_move_to_temp(it, warnings)

def move_by_version_treat_missing_as_v1(group_items, warnings):
    """
    有些有版本号, 有些完全没版本号没时间戳 -> 没有版本号的当作 v1
    最终比较所有版本号，选出最大者保留，其余移到temp/
    """
    version_list = []
    for it in group_items:
        if len(it["versions"]) > 0:
            local_max = max(it["versions"])
        else:
            local_max = 1.0  # 没版本号 => 视为 v1
        version_list.append((it, local_max))

    best = max(version_list, key=lambda x: x[1])
    best_item = best[0]
    for it, _v in version_list:
        if it is best_item:
            continue
        do_move_to_temp(it, warnings)

def do_move_to_temp(item_info, warnings):
    """
    将某个文件/文件夹移动到同级目录下的 temp/ 文件夹中。
    若目标重名，追加 "_1" "_2" 避免覆盖。
    """
    src = item_info["full_path"]
    dst_dir = os.path.join(item_info["root_dir"], "temp")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, item_info["name"])

    final_dst = dst
    counter = 1
    base, ext = os.path.splitext(dst)
    while os.path.exists(final_dst):
        final_dst = f"{base}_{counter}{ext}"
        counter += 1

    try:
        shutil.move(src, final_dst)
        print(f"MOVED: {src} -> {final_dst}")
    except Exception as e:
        msg = f"移动文件时出错: {src} -> {final_dst}, error={e}"
        print("WARNING:", msg)
        warnings.append(msg)

def pick_and_move_in_group(item_indices, items, warnings):
    """
    对同组的 item，按照以下规则进行处理：
      1) 全部带版本号, 无时间戳 -> 保留最高版本, 其余移动到temp/
      2) 全部带时间戳, 无版本号 -> 若时间戳长度一致, 保留最新, 否则警告
      3) 混合：有些有版本号, 有些完全无版本号无时间戳 -> 无版本号视为v1, 保留最高, 其余移到temp/
      4) 其他复杂情况 -> (新增逻辑) 如果组里只有两个文件且它们的大小差在 2KB 以内，则移动较小者；若大小完全一致则移动文件名较短者；否则警告。
    """
    group_items = [items[idx] for idx in item_indices]

    has_version = []
    has_timestamp = []
    for it in group_items:
        has_ver = (len(it["versions"]) > 0)
        has_ts = (len(it["timestamps"]) > 0)
        has_version.append(has_ver)
        has_timestamp.append(has_ts)

    all_have_version = all(has_version)
    all_have_timestamp = all(has_timestamp)
    none_have_version = not any(has_version)
    none_have_timestamp = not any(has_timestamp)

    # (1) 全部有版本号, 全部无时间戳
    if all_have_version and none_have_timestamp:
        move_by_version(group_items, warnings)

    # (2) 全部有时间戳, 全部无版本号
    elif all_have_timestamp and none_have_version:
        ts_list = [it["timestamps"][0] for it in group_items]  # 简化：仅取第一个时间戳
        same_len = len(set(len(ts) for ts in ts_list)) == 1
        if not same_len:
            msg = "时间戳长度不一致, 无法自动处理: " + ", ".join(it["name"] for it in group_items)
            print("WARNING:", msg)
            warnings.append(msg)
        else:
            move_by_timestamp(group_items, warnings)

    # (3) 有些有版本号, 有些完全没版本号没时间戳
    elif any(has_version) and any((not v) and (not t) for v, t in zip(has_version, has_timestamp)):
        move_by_version_treat_missing_as_v1(group_items, warnings)

    # (4) 其他复杂混合
    else:
        # 新增逻辑：若组内恰好有两个文件，并且都是文件(非文件夹)，检查它们的大小差是否在 2KB 内。
        if len(group_items) == 2 and (not group_items[0]["is_dir"]) and (not group_items[1]["is_dir"]):
            size0 = group_items[0]["file_size"]
            size1 = group_items[1]["file_size"]
            # 只有在都能获取到 file_size 时才可比较
            if size0 is not None and size1 is not None:
                diff = abs(size0 - size1)
                if diff < 2048:  # 小于 2KB
                    # 如果大小不一致，则移动体积较小的文件到 temp
                    if size0 < size1:
                        do_move_to_temp(group_items[0], warnings)
                    elif size1 < size0:
                        do_move_to_temp(group_items[1], warnings)
                    else:
                        # 若大小完全一致，则移动文件名较短的那个
                        if len(group_items[0]["name"]) < len(group_items[1]["name"]):
                            do_move_to_temp(group_items[0], warnings)
                        else:
                            do_move_to_temp(group_items[1], warnings)
                    # 这里处理完就不再追加警告了，直接返回
                    return

        # 如果不满足上述 2KB 以内的条件或文件数不为 2，维持原逻辑：打印警告，不做任何自动处理
        msg = "复杂混合版本/时间戳, 请手动处理:\n  " + "\n  ".join(it["name"] for it in group_items)
        print("WARNING:", msg)
        warnings.append(msg)

def main(folder_path):
    if not os.path.exists(folder_path):
        print(f"Error: Path '{folder_path}' does not exist.")
        sys.exit(1)

    items = []
    # 仅处理“当前文件夹”，如果要包含子文件夹，可去除下面的 if 判断
    for root, dirs, files in os.walk(folder_path):
        if root != folder_path:
            continue

        for d in dirs:
            full_path = os.path.join(root, d)
            info = parse_item_info(full_path, folder_path)
            items.append(info)

        for f in files:
            full_path = os.path.join(root, f)
            info = parse_item_info(full_path, folder_path)
            items.append(info)

    if not items:
        print("No files or directories found in:", folder_path)
        return

    # 分组：相同 sequel_num + similarity_name>=阈值 => 同一组
    groups = build_groups(items, threshold=0.85)

    warnings = []
    # 对每组执行移动逻辑
    for g in groups:
        if len(g) < 2:
            # 单一文件/文件夹，不需要移动
            continue
        pick_and_move_in_group(g, items, warnings)

    # 如果有警告，最后集中输出
    if warnings:
        print("\n===== WARNINGS =====")
        for w in warnings:
            print(w)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 this.py /path/to/folder")
        sys.exit(1)

    folder_path = sys.argv[1]
    main(folder_path)
