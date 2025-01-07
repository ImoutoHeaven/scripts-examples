#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import shutil

################################################################
# 配置区域：定义要识别的标签关键字
# 如有需要可在这里补充更多 translator_group / source / translation_version 关键词
################################################################
category_keywords = {
    'source': [
        'Pixiv', 'Patreon', 'Fanbox', 'fanbox', 'pixiv', 'patreon', 'DL版'
    ],
    'translator_group': [
        '汉化','翻译','漢化','翻譯','渣翻','机翻','个人','個人','死兆修会',
        '機翻','中文','繁体','想舔羽月的jio组','賣水槍的小男孩','同人组',
        '烤肉man','漫画の茜','忍殺團','今泉紅太狼','悠月工房','个汉','個漢','同好会','中国翻訳'
    ],
    'translation_version': [
        '重嵌','無修正','无修正','换源','換源','去码','水印','渣嵌'
    ]
    # 如果还有其他类别需求，可自行添加
}

################################################################
# 公共函数：计算相似度 (LCS)、提取版本号、时间戳、续作等
################################################################

def lcs_length(s1, s2):
    """
    计算字符串 s1 和 s2 的最长公共子序列长度（严格保持顺序）。
    """
    len1, len2 = len(s1), len(s2)
    dp = [[0]*(len2+1) for _ in range(len1+1)]
    for i in range(1, len1+1):
        for j in range(1, len2+1):
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
    从文件名中搜集所有版本号标签, 返回列表(字符串形式).
    例如: "[v2]" "[v10.1]" 等，不区分大小写。
    """
    pattern = re.compile(r'\[v(\d+(?:\.\d+)?)\]', re.IGNORECASE)
    return pattern.findall(name)

def parse_timestamp_tags(name):
    """
    匹配形如 [20240102], [2024010201] 等 6~10位数字
    """
    pattern = re.compile(r'\[(\d{6,10})\]')
    return pattern.findall(name)

def extract_extension(name):
    """
    提取扩展名（不含 '.'），如果是文件夹则返回空字符串。
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
    检测结尾纯数字 => 续作编号
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

################################################################
# 从文件名中解析 bracket_tags（可能含多个translator_group等）
################################################################

def parse_bracket_tags(name):
    """
    捕捉所有 [xxx] 内容，针对每个 cat (source, translator_group, translation_version)
    检测其关键词是否出现在此 [xxx] 内，只要出现则把原tag_content放进对应 set.
    
    返回:
    {
      'source': set([...]),
      'translator_group': set([...]),
      'translation_version': set([...])
    }
    """
    bracket_pattern = re.compile(r'\[([^]]+)\]')  # 匹配 [xxx] 内部
    found_tags = bracket_pattern.findall(name)

    result = {
        'source': set(),
        'translator_group': set(),
        'translation_version': set()
    }

    for tag_content in found_tags:
        lower_tag = tag_content.lower()
        for cat, kw_list in category_keywords.items():
            for kw in kw_list:
                if kw.lower() in lower_tag:
                    # 命中后，将“原始的tag_content”加入对应集合
                    result[cat].add(tag_content.strip())
                    # 不 break，这样如果一个tag_content中包含多个关键词也可合并
                    # 如果想匹配到第一个就停，则加break
    return result

################################################################
# 用于相似度比对的名称
################################################################

def get_simplified_name_for_similarity(name):
    """
    用于相似度比对:
      - 去扩展名
      - 去方括号和圆括号
      - 去空格
    """
    ext = extract_extension(name)
    if ext:
        dot_index = name.rfind('.' + ext)
        if dot_index != -1:
            name = name[:dot_index]

    name = remove_brackets_content(name)
    name = re.sub(r'\s+', '', name)
    return name

################################################################
# 构建主信息 parse_item_info
################################################################

def parse_item_info(full_path):
    """
    解析文件/文件夹信息:
     - versions: [2.0, ...]
     - timestamps: ['20240102', ...]
     - bracket_tags: { 'source':set(), 'translator_group':set(), 'translation_version':set() }
     - sequel_num: 末尾续作号 (int 或 None)
     - similarity_name: 用于分组时计算相似度(去除末尾续作数字)
    """
    base_name = os.path.basename(full_path)
    is_dir = os.path.isdir(full_path)

    # 提取版本号、时间戳
    vs_str = parse_version_tags(base_name)     # e.g. ["2", "10.1"]
    ts_str = parse_timestamp_tags(base_name)   # e.g. ["20240102"]
    def to_float(x):
        try:
            return float(x)
        except:
            return 0.0
    versions = [to_float(v) for v in vs_str]

    # 解析方括号标签 => 可能包含多个
    bracket_info = parse_bracket_tags(base_name)

    # 原始可比对名称
    raw_for_similarity = get_simplified_name_for_similarity(base_name)
    # 续作号
    sequel_num = parse_sequel_number(raw_for_similarity)
    similarity_name = raw_for_similarity
    if sequel_num is not None:
        similarity_name = re.sub(r'\d+$', '', similarity_name).strip()

    info = {
        "full_path": full_path,
        "root_dir": os.path.dirname(full_path),
        "name": base_name,
        "is_dir": is_dir,
        "versions": versions,
        "timestamps": ts_str,
        "bracket_tags": bracket_info,  # 各分类是 set
        "sequel_num": sequel_num,
        "similarity_name": similarity_name
    }
    return info

################################################################
# 判断两个 item 是否为“同一作品的不同版本”
# 1) 三类标签集合都相等
# 2) sequel_num 相同
# 3) similarity_name >= threshold
################################################################

def same_bracket_tags(itemA, itemB):
    """
    对比 translator_group, source, translation_version 这三类标签是否完全一致(集合相等).
    """
    for cat in ['translator_group', 'source', 'translation_version']:
        setA = itemA["bracket_tags"][cat]
        setB = itemB["bracket_tags"][cat]
        if setA != setB:
            return False
    return True

def are_same_root_work(itemA, itemB, threshold=0.85):
    """
    判定是否“同一作品的不同版本”：
      1) translator_group / source / translation_version 三类标签(集合)相同
      2) sequel_num 相同
      3) similarity_name 相似度 >= threshold
    """
    # (1) 比较三类标签
    if not same_bracket_tags(itemA, itemB):
        return False

    # (2) 续作号
    if itemA["sequel_num"] != itemB["sequel_num"]:
        return False

    # (3) 标题相似度
    sim = similarity_ratio(itemA["similarity_name"], itemB["similarity_name"])
    return (sim >= threshold)

################################################################
# 分组逻辑：只有当三类标签相同+续作号相同+标题相似度>=阈值才进同一组
################################################################

def build_groups(items, threshold=0.85):
    visited = [False]*len(items)
    groups = []
    for i in range(len(items)):
        if visited[i]:
            continue
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

################################################################
# 同组内移动逻辑：旧版本进 temp/
################################################################

def pick_and_move_in_group(item_indices, items, warnings):
    """
    与之前类似逻辑：
      1) 全部带版本号, 无时间戳 -> 保留最高版本, 其余移到temp/
      2) 全部带时间戳, 无版本号 -> 若时间戳长度一致, 保留最新, 否则警告
      3) 混合：有些有版本号, 有些无版本/时间戳 -> 无版本号视为v1, 选最大
      4) 其他复杂情况 => 警告
    """
    group_items = [items[idx] for idx in item_indices]

    has_version = [(len(it["versions"]) > 0) for it in group_items]
    has_timestamp = [(len(it["timestamps"]) > 0) for it in group_items]

    all_have_version = all(has_version)
    all_have_timestamp = all(has_timestamp)
    none_have_version = not any(has_version)
    none_have_timestamp = not any(has_timestamp)

    if all_have_version and none_have_timestamp:
        move_by_version(group_items, warnings)

    elif all_have_timestamp and none_have_version:
        # 检测时间戳长度
        ts_list = [it["timestamps"][0] for it in group_items]  # 简化假设
        same_len = len(set(len(ts) for ts in ts_list)) == 1
        if not same_len:
            msg = "时间戳长度不一致, 无法自动处理: " + ", ".join(it["name"] for it in group_items)
            print("WARNING:", msg)
            warnings.append(msg)
        else:
            move_by_timestamp(group_items, warnings)

    elif any(has_version) and any((not v) and (not t) for v,t in zip(has_version, has_timestamp)):
        # 有些是vX，有些啥都没 => 当作v1
        move_by_version_treat_missing_as_v1(group_items, warnings)

    else:
        msg = "复杂混合版本/时间戳, 请手动处理:\n  " + "\n  ".join(it["name"] for it in group_items)
        print("WARNING:", msg)
        warnings.append(msg)

def move_by_version(group_items, warnings):
    max_version = -1.0
    best_item = None
    for it in group_items:
        local_max = max(it["versions"])
        if local_max > max_version:
            max_version = local_max
            best_item = it
    if best_item:
        for it in group_items:
            if it is best_item:
                continue
            do_move_to_temp(it, warnings)

def move_by_timestamp(group_items, warnings):
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
    version_list = []
    for it in group_items:
        if len(it["versions"])>0:
            local_max = max(it["versions"])
        else:
            local_max = 1.0  # 无版本视作v1
        version_list.append((it, local_max))

    best = max(version_list, key=lambda x: x[1])
    best_item = best[0]
    for it, _v in version_list:
        if it is best_item:
            continue
        do_move_to_temp(it, warnings)

def do_move_to_temp(item_info, warnings):
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

################################################################
# main: 入口
################################################################

def main(folder_path):
    if not os.path.exists(folder_path):
        print(f"Error: Path '{folder_path}' does not exist.")
        sys.exit(1)

    items = []
    # 如果只想处理当前目录，不递归子文件夹，可保留此判断
    for root, dirs, files in os.walk(folder_path):
        if root != folder_path:
            continue

        for d in dirs:
            full_path = os.path.join(root, d)
            info = parse_item_info(full_path)
            items.append(info)

        for f in files:
            full_path = os.path.join(root, f)
            info = parse_item_info(full_path)
            items.append(info)

    if not items:
        print("No files or directories found in:", folder_path)
        return

    # 分组: 只有三类标签、续作号、标题相似度都满足时 => 同一组
    groups = build_groups(items, threshold=0.85)

    warnings = []
    for g in groups:
        if len(g) < 2:
            continue  # 组内只有一个文件/文件夹，不用动
        pick_and_move_in_group(g, items, warnings)

    if warnings:
        print("\n===== WARNINGS =====")
        for w in warnings:
            print(w)

################################################################
# 命令行入口
################################################################

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 this.py /path/to/folder")
        sys.exit(1)

    folder_path = sys.argv[1]
    main(folder_path)
