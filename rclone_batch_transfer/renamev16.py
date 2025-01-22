import os
import sys
import re
import shutil
from datetime import datetime
from typing import Dict, List

############################
# 分类关键词 & 配置
############################

category_keywords = {
    'source': [
        'Pixiv', 'Patreon', 'Fanbox', 'fanbox', 'pixiv', 'patreon', 'DL版', '赞助'
    ],
    'translator_group': [
        '汉化','翻译','漢化','翻譯','渣翻','机翻','个人','個人','死兆修会',
        '機翻','中文','繁体','想舔羽月的jio组','賣水槍的小男孩','同人组',
        '烤肉man','漫画の茜','忍殺團','今泉紅太狼','悠月工房','个汉','個漢',
        '同好会','翻訳','是小狐狸哦'
    ],
    'translation_version': [
        '重嵌', '無修正', '无修正', '换源', '換源', '去码', '水印', '渣嵌'
    ],
    'version': [
        'v2','v3','v4','v5','v6','v7','v8','v9','v10','v11','v12'
    ],
    'timestamp': None
}

# 用来做 ( ... ) => [ ... ] 的关键字
part_keys_for_parentheses = ('source', 'translator_group', 'translation_version')

# 分类顺序，注意在里面新增了一个 'misc' 用来容纳不匹配任何关键词的 []
category_order = [
    'misc',
    'translator_group',
    'translation_version',
    'source',
    'version',
    'timestamp'
]

############################
# 全局辅助：动态控制 trace/debug 输出
############################

def trace_print(trace_mode, *args):
    """
    打印trace级别日志，只有当 trace_mode = True 时才会输出。
    """
    if trace_mode:
        print("[TRACE]", *args)

def debug_print(debug_mode, *args):
    """
    打印debug级别日志，只有当 debug_mode = True 时才会输出。
    """
    if debug_mode:
        print("[DEBUG]", *args)

############################
# 一系列辅助函数 (带可选 debug/trace)
############################

def clean_empty_brackets(s: str, debug=False, trace=False) -> str:
    """移除空的()和[]，并去除多余空格。"""
    prev = None
    result = s
    pattern_empty_square = re.compile(r'\[\s*\]')
    pattern_empty_paren = re.compile(r'\(\s*\)')

    while prev != result:
        prev = result
        before_sub = result
        result = pattern_empty_square.sub('', result)
        result = pattern_empty_paren.sub('', result)
        result = re.sub(r'\s+', ' ', result).strip()
        if trace and before_sub != result:
            trace_print(trace, f"clean_empty_brackets: '{before_sub}' => '{result}'")

    return result

def light_bracket_fix(s: str, debug=False, trace=False) -> str:
    """如果检测到多余/缺失方括号或圆括号，做一次轻量的修正。"""
    before = s
    cnt_open_sq = s.count('[')
    cnt_close_sq = s.count(']')
    cnt_open_par = s.count('(')
    cnt_close_par = s.count(')')

    if cnt_open_sq == cnt_close_sq + 1:
        s2 = re.sub(r'\[\[', '[', s, count=1)
        if s2 != s and trace:
            trace_print(trace, "light_bracket_fix: fix '[[' => '['")
        s = s2
    elif cnt_close_sq == cnt_open_sq + 1:
        s2 = re.sub(r'\]\]', ']', s, count=1)
        if s2 != s and trace:
            trace_print(trace, "light_bracket_fix: fix ']]' => ']'")
        s = s2

    if cnt_open_par == cnt_close_par + 1:
        s2 = re.sub(r'\(\(', '(', s, count=1)
        if s2 != s and trace:
            trace_print(trace, "light_bracket_fix: fix '((' => '('")
        s = s2
    elif cnt_close_par == cnt_open_par + 1:
        s2 = re.sub(r'\)\)', ')', s, count=1)
        if s2 != s and trace:
            trace_print(trace, "light_bracket_fix: fix '))' => ')'")
        s = s2

    if trace and s != before:
        trace_print(trace, f"light_bracket_fix: '{before}' => '{s}'")
    return s

def check_brackets(s: str, debug=False, trace=False):
    """检查括号是否匹配，不匹配则抛出 ValueError。"""
    bracket_pairs = {'[': ']', '(': ')'}
    for opening, closing in bracket_pairs.items():
        depth = 0
        for i, c in enumerate(s):
            if c == opening:
                depth += 1
            elif c == closing:
                depth -= 1
                if depth < 0:
                    debug_print(debug, f"check_brackets: Unmatched closing '{closing}' found at index {i}.")
                    raise ValueError(f"Unmatched closing '{closing}' in '{s}'. Please handle manually.")
        if depth != 0:
            debug_print(debug, f"check_brackets: Unmatched opening '{opening}' found, depth != 0.")
            raise ValueError(f"Unmatched opening '{opening}' in '{s}'. Please handle manually.")
    return True

def gather_bracket_keywords(cat_dict, keys, debug=False, trace=False):
    """汇总部分分类关键词，如 translator_group、source 等。"""
    all_kw = []
    for k in keys:
        vals = cat_dict.get(k)
        if vals:
            all_kw.extend(vals)
    # 去重且保留顺序
    unique_list = list(dict.fromkeys(all_kw))
    debug_print(debug, f"gather_bracket_keywords => {unique_list}")
    return unique_list

def replace_paren_with_bracket_on_keywords(name: str, keywords_list, debug=False, trace=False) -> str:
    """
    若 (xxx) 内含有指定关键词之一，则把它改成 [xxx]。
    """
    pattern_keywords = '|'.join(map(re.escape, keywords_list))
    debug_print(debug, f"replace_paren_with_bracket_on_keywords => pattern_keywords: {pattern_keywords}")
    pattern_paren = re.compile(r'\([^)]*(?:' + pattern_keywords + r')[^)]*\)', re.IGNORECASE)

    def _replace(m):
        content = m.group(0)
        trace_print(trace, f"matched paren content: {content}")
        inner = content[1:-1]
        return "[" + inner + "]"

    before_sub = name
    new_name = pattern_paren.sub(_replace, name)
    if debug and new_name != before_sub:
        debug_print(debug, f"replace_paren_with_bracket_on_keywords: '{before_sub}' => '{new_name}'")
    return new_name

def create_category_pattern(category, words, debug=False, trace=False):
    """根据category与对应keywords生成一个用于匹配方括号内容的正则表达式。"""
    if category == 'translator_group':
        keywords = '|'.join(map(re.escape, words))
        return re.compile(r'\[[^\]]*(?:' + keywords + r')[^\]]*\]', re.IGNORECASE)
    elif category in ('source', 'translation_version'):
        keywords = '|'.join(map(re.escape, words))
        return re.compile(r'\[[^\]]*(?:' + keywords + r')[^\]]*\]', re.IGNORECASE)
    elif category in ('version', 'timestamp'):
        keywords = '|'.join(map(re.escape, words))
        return re.compile(r'^(' + '|'.join(map(re.escape, words)) + r')$', re.IGNORECASE)
    else:
        return None

def standardize_timestamp(timestamp_str, debug=False, trace=False):
    """把 YYMMDD => YYYYMMDD, 或 YYYYMMDDxx => YYYYMMDD。"""
    if not timestamp_str:
        return None
    
    digits = ''.join(filter(str.isdigit, timestamp_str))
    before = timestamp_str
    after = None
    if len(digits) == 6:  # YYMMDD -> YYYYMMDD
        after = f"20{digits}"
    elif len(digits) == 8:  # YYYYMMDD
        after = digits
    elif len(digits) == 10:  # YYYYMMDDvv
        after = digits[:8]

    if trace and after and after != before:
        trace_print(trace, f"standardize_timestamp: '{before}' => '{after}'")
    return after

def process_version_tag(name, debug=False, trace=False):
    """把 v2 之类的标记补成 [v2]"""
    before = name
    pattern_bracketed = re.compile(r'\[+v(\d+(?:\.\d+)?)\]+', re.IGNORECASE)
    name = pattern_bracketed.sub(lambda m: f'[v{m.group(1)}]', name)
    
    pattern = re.compile(r'(?<![A-Za-z0-9\[\]])v(\d+(?:\.\d+)?)(?![A-Za-z0-9\[\]])', re.IGNORECASE)
    name = pattern.sub(lambda m: f'[v{m.group(1)}]', name)
    
    if debug and name != before:
        debug_print(debug, f"process_version_tag: '{before}' => '{name}'")
    return name

def rearrange_tags(name, debug=False, trace=False):
    """
    把文件名里所有 [分类] 取出来，根据 translator_group -> translation_version -> source -> misc -> version -> timestamp 顺序进行重组。
    """
    debug_print(debug, f"rearrange_tags: input => '{name}'")

    # 准备分类正则
    category_patterns = {}
    for category, words in category_keywords.items():
        if words:
            category_patterns[category] = create_category_pattern(category, words, debug=debug, trace=trace)
        else:
            if category == 'timestamp':
                category_patterns['timestamp'] = re.compile(r'^(\d{6}|\d{8}|\d{10})$')

    bracket_tag_pattern = re.compile(r'\[([^\[\]]+)\]')
    matched_tag_positions = []
    category_tags = {cat: [] for cat in category_order}

    # 搜索所有 [xxx]
    for match in re.finditer(bracket_tag_pattern, name):
        tag_content = match.group(1).strip()
        tag_start = match.start()
        tag_end = match.end()
        trace_print(trace, f" Found bracket tag => [{tag_content}] (pos {tag_start}-{tag_end})")
        categorized = False

        # 如果是时间戳
        if category_patterns['timestamp'].match(tag_content):
            std_timestamp = standardize_timestamp(tag_content, debug=debug, trace=trace)
            if std_timestamp:
                category_tags['timestamp'].append(std_timestamp)
                trace_print(trace, f"  => recognized as timestamp => {std_timestamp}")
                categorized = True
                matched_tag_positions.append((tag_start, tag_end))
                continue

        # 检查其他分类
        for category in category_order:
            if category in ('timestamp', 'misc'):
                continue
            ptn = category_patterns.get(category)
            if ptn and ptn.match(f'[{tag_content}]'):
                category_tags[category].append(tag_content)
                trace_print(trace, f"  => recognized as '{category}' => {tag_content}")
                categorized = True
                matched_tag_positions.append((tag_start, tag_end))
                break

        # 如果都没匹配到 => 先不放到 misc，在 reorder_suffix 或别的地方再处理
        # 也可以选择这里直接放 misc
        if not categorized:
            trace_print(trace, f"  => not matched => not removed yet (will handle later)")

    # 从后往前删除匹配到的标签
    name_list = list(name)
    for start, end in sorted(matched_tag_positions, key=lambda x: -x[0]):
        del name_list[start:end]
    name_without_tags = ''.join(name_list).strip()

    # 打印分类收集结果
    for cat in category_order:
        if category_tags[cat]:
            trace_print(trace, f"  category_tags['{cat}'] => {category_tags[cat]}")

    # 按顺序重组
    rearranged_tags = []
    for category in category_order:
        tags = category_tags[category]
        if tags:
            # 同类内做个排序
            tags.sort(key=str.lower)
            # 追加到总列表
            for t in tags:
                rearranged_tags.append(f'[{t}]')
                trace_print(trace, f"   => after sorting: appended '{t}' to final")

    final_name = name_without_tags
    if rearranged_tags:
        final_name = final_name + ' ' + ' '.join(rearranged_tags)

    final_name = re.sub(r'\s+', ' ', final_name).strip()
    final_name = clean_empty_brackets(final_name, debug=debug, trace=trace)
    
    debug_print(debug, f"rearrange_tags: output => '{final_name}'")
    return final_name

def convert_naked_timestamp_to_bracket(name: str, debug=False, trace=False) -> str:
    """
    将文件名中裸奔的 6/8/10/11 位数字（疑似时间戳）加上方括号。
    """
    pattern = re.compile(r'\b(\d{6}|\d{8}|\d{10}|\d{11})\b')

    def _replace(m):
        digits = m.group(1)
        return f'[{digits}]'

    new_name = pattern.sub(_replace, name)
    if trace and new_name != name:
        trace_print(trace, f"convert_naked_timestamp_to_bracket: '{name}' => '{new_name}'")
    return new_name

############################
# detect_category_for_bracket (暂时未用到，可留作调试)
############################

def detect_category_for_bracket(tag_content, debug=False, trace=False):
    """
    根据已有的 category_keywords 来判断属于哪个分类，若都不匹配则归入 'misc'。
    """
    # 先检查是否是时间戳
    if re.match(r'^(?:\d{6}|\d{8}|\d{10})$', tag_content):
        trace_print(trace, f"detect_category_for_bracket: '{tag_content}' => 'timestamp'")
        return 'timestamp'
    
    # 再检查其他分类
    for cat, keywords in category_keywords.items():
        if cat == 'timestamp':
            continue
        if keywords:
            for kw in keywords:
                if kw.lower() in tag_content.lower():
                    trace_print(trace, f"detect_category_for_bracket: '{tag_content}' => '{cat}' (matched '{kw}')")
                    return cat

    trace_print(trace, f"detect_category_for_bracket: '{tag_content}' => 'misc'")
    return 'misc'

############################
# reorder_suffix
############################

def reorder_suffix(name_without_ext, debug=False, trace=False):
    """
    对名字(不带扩展名)进行后缀重排：
      1) 检测并提取最左侧单一前缀 prefix
      2) 对其余文本做 convert_naked_timestamp_to_bracket + rearrange_tags
      3) 拼回 prefix + rest
    """
    debug_print(debug, f"reorder_suffix: input => '{name_without_ext}'")

    raw = name_without_ext.strip()
    prefix = ""
    prefix_end = 0

    if raw.startswith("(") or raw.startswith("["):
        if raw.startswith("("):
            depth = 0
            i = 0
            found_paren = False
            while i < len(raw):
                if raw[i] == '(':
                    depth += 1
                elif raw[i] == ')':
                    depth -= 1
                    if depth == 0:
                        i += 1
                        found_paren = True
                        break
                i += 1
            if found_paren:
                prefix = raw[:i].strip()
                prefix_end = i
        elif raw.startswith("["):
            depth = 0
            i = 0
            found_bracket = False
            while i < len(raw):
                if raw[i] == '[':
                    depth += 1
                elif raw[i] == ']':
                    depth -= 1
                    if depth == 0:
                        i += 1
                        found_bracket = True
                        break
                i += 1
            if found_bracket:
                prefix = raw[:i].strip()
                prefix_end = i

    rest = raw[prefix_end:].strip()
    debug_print(debug, f"reorder_suffix => prefix: '{prefix}', rest: '{rest}'")

    rest = process_version_tag(rest, debug=debug, trace=trace)
    rest = convert_naked_timestamp_to_bracket(rest, debug=debug, trace=trace)
    rest = rearrange_tags(rest, debug=debug, trace=trace)

    if prefix:
        new_name = prefix + " " + rest
    else:
        new_name = rest

    new_name = re.sub(r'\s+', ' ', new_name).strip()
    new_name = clean_empty_brackets(new_name, debug=debug, trace=trace)

    debug_print(debug, f"reorder_suffix: final => '{new_name}'")
    return new_name

############################
# process_name/process_filename
############################

def process_name(name, debug=False, trace=False):
    """对去掉拓展名的文件名进行一系列处理，返回处理后的名字。"""
    debug_print(debug, f"process_name: Original => '{name}'")

    name = clean_empty_brackets(name, debug=debug, trace=trace)
    
    before_sub = name
    name = re.sub(r'[【［]', '[', name)
    name = re.sub(r'[】］]', ']', name)
    name = name.replace('（', '(').replace('）', ')')
    if debug and name != before_sub:
        debug_print(debug, f"unify brackets: '{before_sub}' => '{name}'")

    name = light_bracket_fix(name, debug=debug, trace=trace)
    name = clean_empty_brackets(name, debug=debug, trace=trace)

    # check brackets
    try:
        check_brackets(name, debug=debug, trace=trace)
    except ValueError:
        debug_print(debug, f"check_brackets raised ValueError, trying light_bracket_fix again")
        name = light_bracket_fix(name, debug=debug, trace=trace)
        name = clean_empty_brackets(name, debug=debug, trace=trace)
        check_brackets(name, debug=debug, trace=trace)

    # remove (同人誌)
    before_sub = name
    name = name.replace('(同人誌)', '')
    name = clean_empty_brackets(name, debug=debug, trace=trace)
    if debug and name != before_sub:
        debug_print(debug, f"remove '(同人誌)': '{before_sub}' => '{name}'")

    # 替换含关键词的(...) => [...]
    bracket_keywords = gather_bracket_keywords(category_keywords, part_keys_for_parentheses, debug=debug, trace=trace)
    name = replace_paren_with_bracket_on_keywords(name, bracket_keywords, debug=debug, trace=trace)
    name = clean_empty_brackets(name, debug=debug, trace=trace)

    # [v2] 标记处理
    name = process_version_tag(name, debug=debug, trace=trace)
    name = clean_empty_brackets(name, debug=debug, trace=trace)

    # 如果最开头是某些组别关键字 [xxx]，挪到后面
    move_keywords_pattern = '|'.join(map(re.escape, bracket_keywords))
    match = re.match(r'^(\[[^\[\]]*(?:' + move_keywords_pattern + r')[^\[\]]*\])\s*(.*)', name, flags=re.IGNORECASE)
    if match:
        bracket_to_move = match.group(1)
        rest_of_name = match.group(2)
        old_name = name
        name = rest_of_name.strip() + ' ' + bracket_to_move
        name = clean_empty_brackets(name, debug=debug, trace=trace)
        if debug and old_name != name:
            debug_print(debug, f"move bracket from start to end: '{old_name}' => '{name}'")

    # 替换下划线 => 空格
    before_sub = name
    name = name.replace('_', ' ')
    # 处理括号与文字之间的空格
    name = name.replace('[', ' [').replace(']', '] ').replace('(', ' (').replace(')', ') ')
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'\) \]', ')]', name)
    name = re.sub(r'\[ ', '[', name)
    name = re.sub(r' \]', ']', name)
    name = clean_empty_brackets(name, debug=debug, trace=trace)
    if debug and name != before_sub:
        debug_print(debug, f"spacing brackets: '{before_sub}' => '{name}'")

    old_name = name
    name = convert_naked_timestamp_to_bracket(name, debug=debug, trace=trace)
    name = rearrange_tags(name, debug=debug, trace=trace)
    if debug and name != old_name:
        debug_print(debug, f"rearrange_tags => '{old_name}' => '{name}'")

    debug_print(debug, f"process_name: Final => '{name}'")
    return name

def process_filename(filename, debug=False, trace=False):
    """
    对单个文件名进行处理，包含对扩展名的拆分和拼装。
    最终会调用 reorder_suffix() 做标签重排。
    """
    if filename.startswith('.'):
        debug_print(debug, f"process_filename: skip hidden => '{filename}'")
        return filename

    parts = filename.rsplit('.', 1)
    if len(parts) == 2:
        name, ext = parts
    else:
        name, ext = filename, ''

    # 第一步: process_name
    new_name_no_ext = process_name(name, debug=debug, trace=trace)
    # 第二步: reorder_suffix
    final_name_no_ext = reorder_suffix(new_name_no_ext, debug=debug, trace=trace)

    ext = ext.strip()
    if ext:
        new_name = final_name_no_ext + '.' + ext
    else:
        new_name = final_name_no_ext

    debug_print(debug, f"process_filename: final => '{new_name}'")
    return new_name

############################################
# is_filename_compliant
############################################

def is_filename_compliant(name, debug=False, trace=False):
    """
    对你的特定合规需求做检查，用于脚本末尾发出警告。
    """
    name_stripped = name.strip()
    debug_print(debug, f"is_filename_compliant: checking => '{name_stripped}'")

    if not name_stripped:
        debug_print(debug, " => not compliant (empty)")
        return False

    if '[' not in name_stripped:
        debug_print(debug, " => not compliant (no '[' found)")
        return False

    system_keywords = set()
    for k, vals in category_keywords.items():
        if vals:
            for v in vals:
                system_keywords.add(v.lower())

    def is_timestamp_like(s):
        return re.match(r'^(?:\d{6}|\d{8}|\d{10})$', s)

    pos = 0
    length = len(name_stripped)

    if name_stripped.startswith('('):
        start = pos
        depth = 0
        while pos < length:
            if name_stripped[pos] == '(':
                depth += 1
            elif name_stripped[pos] == ')':
                depth -= 1
                if depth == 0:
                    pos += 1
                    paren_content = name_stripped[start+1:pos-1].strip()
                    if not paren_content:
                        debug_print(debug, " => not compliant (empty parentheses)")
                        return False
                    if paren_content.lower() in system_keywords:
                        debug_print(debug, " => not compliant (paren_content is system keyword)")
                        return False
                    if is_timestamp_like(paren_content):
                        debug_print(debug, " => not compliant (paren_content is timestamp)")
                        return False
                    break
            pos += 1
        if depth != 0:
            debug_print(debug, " => not compliant (unmatched '(')")
            return False

    while pos < length and name_stripped[pos].isspace():
        pos += 1

    if pos >= length or name_stripped[pos] != '[':
        debug_print(debug, " => not compliant ([ not found after optional paren)")
        return False

    bracket_start = pos
    pos += 1
    depth = 1
    while pos < length and depth > 0:
        if name_stripped[pos] == '[':
            depth += 1
        elif name_stripped[pos] == ']':
            depth -= 1
        pos += 1

    if depth != 0:
        debug_print(debug, " => not compliant (unmatched '[')")
        return False

    bracket_end = pos
    bracket_content = name_stripped[bracket_start+1:bracket_end-1].strip()
    if not bracket_content:
        debug_print(debug, " => not compliant (empty bracket)")
        return False
    if bracket_content.lower() in system_keywords:
        debug_print(debug, " => not compliant (bracket_content is system keyword)")
        return False
    if is_timestamp_like(bracket_content):
        debug_print(debug, " => not compliant (bracket_content is timestamp)")
        return False

    while pos < length and name_stripped[pos].isspace():
        pos += 1
    if pos < length and name_stripped[pos] in ['(', '[', '{']:
        debug_print(debug, " => not compliant (immediately '(' or '[' or '{' after bracket)")
        return False

    # 检查 [vX] & [YYYYMMDD] 顺序
    tags = re.findall(r'\[([^\]]+)\]', name_stripped)
    if not tags:
        debug_print(debug, " => not compliant (no [tags] found at all)")
        return False

    version_tag = None
    timestamp_tag = None
    for tag in tags:
        if re.search(r'^v\d+(?:\.\d+)?$', tag, re.IGNORECASE):
            version_tag = tag
        elif re.match(r'^(?:\d{6}|\d{8}|\d{10})$', tag):
            timestamp_tag = tag

    if version_tag and timestamp_tag:
        version_pos = name_stripped.rindex(f'[{version_tag}]')
        timestamp_pos = name_stripped.rindex(f'[{timestamp_tag}]')
        if version_pos > timestamp_pos:
            debug_print(debug, " => not compliant ([vX] is after [timestamp])")
            return False

    debug_print(debug, " => compliant!")
    return True

############################
# OS 相关处理 (核心功能同原版，只是多加 trace)
############################

def compare_files(file1, file2, debug=False, trace=False):
    """比较两个文件的修改时间和大小，返回保留哪个。"""
    stat1 = os.stat(file1)
    stat2 = os.stat(file2)
    debug_print(debug, f"compare_files => file1='{file1}', file2='{file2}'")
    trace_print(trace, f"   st_mtime => {stat1.st_mtime} vs {stat2.st_mtime}")
    trace_print(trace, f"   st_size  => {stat1.st_size} vs {stat2.st_size}")

    if stat1.st_mtime != stat2.st_mtime:
        return file1 if stat1.st_mtime < stat2.st_mtime else file2

    if stat1.st_size != stat2.st_size:
        return file1 if stat1.st_size < stat2.st_size else file2

    return file1

def ensure_temp_dir(folder_path, debug=False, trace=False):
    temp_dir = os.path.join(folder_path, 'temp')
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        debug_print(debug, f"ensure_temp_dir => created '{temp_dir}'")
    return temp_dir

def main(folder_path, dry_run=False, debug=False, trace=False):
    """
    改进后的主函数, 额外增加 trace 输出.
    """
    # 阶段1: 括号匹配预检
    unmatched_bracket_files = []
    try:
        items = os.listdir(folder_path)
    except FileNotFoundError:
        print(f"Error: Path '{folder_path}' does not exist.")
        return

    if 'temp' in items:
        items.remove('temp')

    for item in items:
        if item.startswith('.'):
            continue
        item_path = os.path.join(folder_path, item)

        if os.path.isfile(item_path):
            base_no_ext, _ = os.path.splitext(item)
            try:
                _ = process_name(base_no_ext, debug=debug, trace=trace)
            except ValueError:
                unmatched_bracket_files.append(base_no_ext)
        elif os.path.isdir(item_path):
            try:
                _ = process_name(item, debug=debug, trace=trace)
            except ValueError:
                unmatched_bracket_files.append(item)

    if unmatched_bracket_files:
        print("检测到以下名称存在括号不匹配，请修正后再运行脚本：")
        for fname in unmatched_bracket_files:
            print(fname)
        return

    # 阶段2: 正式改名处理
    warnings = []
    temp_dir = None
    rename_logs = []

    items = os.listdir(folder_path)
    if 'temp' in items:
        items.remove('temp')

    for item in items:
        if item.startswith('.'):
            continue

        item_path = os.path.join(folder_path, item)

        # 文件处理
        if os.path.isfile(item_path):
            old_name_no_ext, old_ext = os.path.splitext(item)
            original_basename = old_name_no_ext

            processed_fullname = process_filename(item, debug=debug, trace=trace)
            processed_base_no_ext, processed_ext = os.path.splitext(processed_fullname)

            # 合规检查
            if is_filename_compliant(processed_base_no_ext, debug=debug, trace=trace):
                reordered_base_no_ext = reorder_suffix(processed_base_no_ext, debug=debug, trace=trace)
            else:
                reordered_base_no_ext = processed_base_no_ext
                warnings.append((processed_base_no_ext, "Does not conform to naming convention"))

            final_fullname = reordered_base_no_ext + processed_ext

            if final_fullname != item:
                final_path = os.path.join(folder_path, final_fullname)
                if not dry_run:
                    try:
                        os.rename(item_path, final_path)
                    except OSError as e:
                        # 冲突
                        if hasattr(e, 'winerror') and e.winerror == 183:
                            if temp_dir is None:
                                temp_dir = ensure_temp_dir(folder_path, debug=debug, trace=trace)
                            file_to_move = compare_files(item_path, final_path, debug=debug, trace=trace)
                            temp_path = os.path.join(temp_dir, os.path.basename(file_to_move))
                            counter = 1
                            base, ext_ = os.path.splitext(temp_path)
                            while os.path.exists(temp_path):
                                temp_path = f"{base}_{counter}{ext_}"
                                counter += 1
                            shutil.move(file_to_move, temp_path)
                            if file_to_move == item_path:
                                continue
                        else:
                            warnings.append((processed_base_no_ext, str(e)))
                    else:
                        rename_logs.append((original_basename, reordered_base_no_ext))
                else:
                    rename_logs.append((original_basename, reordered_base_no_ext))

        # 目录处理
        elif os.path.isdir(item_path):
            old_dir_name = item
            original_basename = old_dir_name
            processed_dir_name = process_name(old_dir_name, debug=debug, trace=trace)

            if is_filename_compliant(processed_dir_name, debug=debug, trace=trace):
                reordered_dir_name = reorder_suffix(processed_dir_name, debug=debug, trace=trace)
            else:
                reordered_dir_name = processed_dir_name
                warnings.append((processed_dir_name, "Does not conform to naming convention"))

            final_dir_name = reordered_dir_name
            if final_dir_name != old_dir_name:
                final_path = os.path.join(folder_path, final_dir_name)
                if not dry_run:
                    try:
                        os.rename(item_path, final_path)
                    except OSError as e:
                        if hasattr(e, 'winerror') and e.winerror == 183:
                            if temp_dir is None:
                                temp_dir = ensure_temp_dir(folder_path, debug=debug, trace=trace)
                            file_to_move = compare_files(item_path, final_path, debug=debug, trace=trace)
                            temp_path = os.path.join(temp_dir, os.path.basename(file_to_move))
                            counter = 1
                            base, ext_ = os.path.splitext(temp_path)
                            while os.path.exists(temp_path):
                                temp_path = f"{base}_{counter}{ext_}"
                                counter += 1
                            shutil.move(file_to_move, temp_path)
                            if file_to_move == item_path:
                                continue
                        else:
                            warnings.append((processed_dir_name, str(e)))
                    else:
                        rename_logs.append((original_basename, reordered_dir_name))
                else:
                    rename_logs.append((original_basename, reordered_dir_name))

    # 打印改名日志
    if rename_logs:
        for i, (old_no_ext, new_no_ext) in enumerate(rename_logs, start=1):
            if old_no_ext != new_no_ext:
                print(f"--- file {i}/{len(rename_logs)} ---")
                print(f"{old_no_ext} ==>")
                print(f"{new_no_ext}")

    # 打印警告
    if warnings:
        print("\nWARNING: The following items had issues:")
        shown_set = set()
        for (w_name, w_err) in warnings:
            if w_name not in shown_set:
                print(w_name)
                shown_set.add(w_name)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python script.py /path/to/folder [--dry-run] [--debug] [--trace]")
        sys.exit(1)
        
    folder_path = sys.argv[1]
    dry_run = '--dry-run' in sys.argv
    debug_mode = '--debug' in sys.argv
    trace_mode = '--trace' in sys.argv

    if not os.path.exists(folder_path):
        print(f"Error: Path '{folder_path}' does not exist.")
        sys.exit(1)

    if dry_run:
        print("Running in dry-run mode - no actual changes will be made")
    if debug_mode:
        print("Running in debug mode - verbose logs enabled")
    if trace_mode:
        print("Running in trace mode - extremely verbose logs")

    main(folder_path, dry_run=dry_run, debug=debug_mode, trace=trace_mode)
