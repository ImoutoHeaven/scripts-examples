import os
import sys
import re
import shutil
from datetime import datetime

def clean_empty_brackets(s: str) -> str:
    """
    清理字符串中形如 [] 或 [   ] 的空方括号
    以及 () 或 (   ) 的空圆括号。
    多次匹配，直到再也没有空括号出现为止。
    """
    prev = None
    result = s
    pattern_empty_square = re.compile(r'\[\s*\]')
    pattern_empty_paren = re.compile(r'\(\s*\)')
    while prev != result:
        prev = result
        # 先去除空的[]
        result = pattern_empty_square.sub('', result)
        # 再去除空的()
        result = pattern_empty_paren.sub('', result)
        # 如果有连续的空格，因为去掉括号后可能产生多余空格，这里顺手处理一下
        result = re.sub(r'\s+', ' ', result).strip()
    return result


def light_bracket_fix(s: str) -> str:
    """
    尝试轻度修复: 
    1) 如果连续出现 '[['，且比 ']]' 多一次，就替换最左的 '[[' -> '['
    2) 如果连续出现 ']]'，且比 '[[' 多一次，就替换最左的 ']]' -> ']'
    3) 同理对圆括号 '((' 或 '))'
    只做一次修复后返回，不做多轮循环。
    """
    cnt_open_sq = s.count('[')
    cnt_close_sq = s.count(']')
    cnt_open_par = s.count('(')
    cnt_close_par = s.count(')')

    # 修复方括号
    if cnt_open_sq == cnt_close_sq + 1:
        s = re.sub(r'\[\[', '[', s, count=1)
    elif cnt_close_sq == cnt_open_sq + 1:
        s = re.sub(r'\]\]', ']', s, count=1)

    # 修复圆括号
    if cnt_open_par == cnt_close_par + 1:
        s = re.sub(r'\(\(', '(', s, count=1)
    elif cnt_close_par == cnt_open_par + 1:
        s = re.sub(r'\)\)', ')', s, count=1)

    return s


def check_brackets(s):
    """
    检查 s 中圆括号() 和方括号[] 是否匹配。
    如果不匹配则抛出 ValueError。
    """
    bracket_pairs = {'[': ']', '(': ')'}
    for opening, closing in bracket_pairs.items():
        depth = 0
        for i, c in enumerate(s):
            if c == opening:
                depth += 1
            elif c == closing:
                depth -= 1
                if depth < 0:
                    raise ValueError(
                        f"Unmatched closing '{closing}' in '{s}'. Please handle manually."
                    )
        if depth != 0:
            raise ValueError(
                f"Unmatched opening '{opening}' in '{s}'. Please handle manually."
            )
    return True


# ---------------------------------------------------------------------------
# 这里只维护一个 category_keywords，
# 括号替换时只用到其中的 part_keys = ('source','translator_group','translation_version')。
# 标签重排时会用到全部类别。
# ---------------------------------------------------------------------------
category_keywords = {
    'source': [
        'Pixiv', 'Patreon', 'Fanbox', 'fanbox', 'pixiv', 'patreon', 'DL版'
    ],
    'translator_group': [
        '汉化','翻译','漢化','翻譯','渣翻','机翻','个人','個人','死兆修会','機翻','中文',
        '繁体','想舔羽月的jio组','賣水槍的小男孩','同人组','烤肉man','漫画の茜','忍殺團','今泉紅太狼','悠月工房','个汉','個漢','同好会'
    ],
    'translation_version': [
        '重嵌', '無修正', '换源', '換源', '去码', '水印', '渣嵌'
    ],
    'version': [
        'v2','v3','v4','v5','v6','v7','v8','v9','v10','v11','v12'
    ],
    # 如果你不需要 timestamp，可以设置为 [] 或 None
    'timestamp': None  
}

# 括号替换时 只用这几个 key:
part_keys_for_parentheses = ('source','translator_group','translation_version')

def gather_bracket_keywords(cat_dict, keys):
    """
    从 category_keywords 中抽取指定 keys(如 source, translator_group, translation_version)
    合并到一个大列表中返回，用于() -> []替换。
    """
    all_kw = []
    for k in keys:
        vals = cat_dict.get(k)
        if vals:
            all_kw.extend(vals)
    # 去重并保持顺序
    return list(dict.fromkeys(all_kw))


def replace_paren_with_bracket_on_keywords(name: str, keywords_list) -> str:
    """
    将字符串中所有 '(...)' 内只要含有 keywords_list 里任何一个关键词，就替换成 '[...]'。
    """
    pattern_keywords = '|'.join(map(re.escape, keywords_list))
    # 若想忽略大小写 => 加 re.IGNORECASE
    pattern_paren = re.compile(r'\([^)]*(?:' + pattern_keywords + r')[^)]*\)', re.IGNORECASE)

    def _replace(m):
        content = m.group(0)
        # 去掉首尾圆括号
        inner = content[1:-1]
        return "[" + inner + "]"

    return pattern_paren.sub(_replace, name)


def process_name(name):
    """
    对文件(或文件夹)名进行重命名逻辑：
    1. 全角 -> 半角
    2. 轻度修复、检查配对
    3. 去除 (同人誌)
    4. () -> []（只要括号内包含关键词；仅限 source, translator_group, translation_version）
    5. v+数字 -> [v数字]（排除类似Rev3等）
    6. 移动最前 [关键字] -> 后面
    7. 替换下划线、加空格、精简空格
    8. 重新排序标签 rearrange_tags
    9. 最后再次清理空括号
    """

    name = clean_empty_brackets(name)

    # 1. 替换全角括号 -> 半角括号
    name = re.sub(r'[【［]', '[', name)
    name = re.sub(r'[】］]', ']', name)
    name = name.replace('（', '(').replace('）', ')')

    # 轻度修复一次、清理空括号
    name = light_bracket_fix(name)
    name = clean_empty_brackets(name)

    # 2. 检查配对，如不配对，再修一次
    try:
        check_brackets(name)
    except ValueError:
        name = light_bracket_fix(name)
        name = clean_empty_brackets(name)
        check_brackets(name)  # 若仍出错则抛异常

    # 3. 去除 (同人誌)
    name = name.replace('(同人誌)', '')
    name = clean_empty_brackets(name)

    # 4. 将括号内含有关键词的 () -> []
    bracket_keywords = gather_bracket_keywords(category_keywords, part_keys_for_parentheses)
    name = replace_paren_with_bracket_on_keywords(name, bracket_keywords)
    name = clean_empty_brackets(name)

    # 5. 将 v+数字 => [v数字] (排除 Rev3 / v3Anthor 等)
    pattern_ver = re.compile(r'(?<![A-Za-z0-9])v(\d+)(?![A-Za-z0-9])', re.IGNORECASE)
    def replace_version(m):
        return f"[v{m.group(1)}]"
    name = pattern_ver.sub(replace_version, name)
    name = clean_empty_brackets(name)

    # 6. 移动最前 [xxx] -> 后面 (如果含 keyword)
    #    用同样的 bracket_keywords 做判断即可，也可以合并 version/translation_version
    move_keywords = '|'.join(map(re.escape, bracket_keywords))
    match = re.match(r'^(\[[^\[\]]*(?:' + move_keywords + r')[^\[\]]*\])\s*(.*)', name, flags=re.IGNORECASE)
    if match:
        bracket_to_move = match.group(1)
        rest_of_name = match.group(2)
        name = rest_of_name.strip() + ' ' + bracket_to_move
    name = clean_empty_brackets(name)

    # 7. 替换下划线 -> 空格, 美化空格
    name = name.replace('_', ' ')
    name = name.replace('[', ' [').replace(']', '] ').replace('(', ' (').replace(')', ') ')
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'\) \]', ')]', name)
    name = re.sub(r'\[ ', '[', name)
    name = re.sub(r' \]', ']', name)
    name = clean_empty_brackets(name)

    # 8. 重新排序标签
    name = rearrange_tags(name)
    name = clean_empty_brackets(name)

    return name


def rearrange_tags(name):
    """
    对 [Pixiv] [汉化] [v2] 等标签按特定顺序重新排列到后面。
    在返回前会再次清理空的[]标签。
    """
    # 我们直接复用同一个 category_keywords，按照自己想要的顺序排列
    category_order = ['source', 'translator_group', 'translation_version', 'version', 'timestamp']

    # 构建每个类别对应的匹配模式
    category_patterns = {}
    for category, words in category_keywords.items():
        if words:
            # 仅匹配完整标签(不匹配空)
            pattern = re.compile(r'^(' + '|'.join(map(re.escape, words)) + r')$', re.IGNORECASE)
            category_patterns[category] = pattern
        else:
            # 举例: timestamp 可能是正则判断某些数字格式
            if category == 'timestamp':
                category_patterns['timestamp'] = re.compile(r'^(\d{6,8}|\d{6,8}\d{2})$')

    bracket_tag_pattern = re.compile(r'\[([^\[\]]+)\]')
    matched_tag_positions = []
    category_tags = {cat: [] for cat in category_order}

    # 找到所有 [xxx] 标签，判断分类
    for match in re.finditer(bracket_tag_pattern, name):
        tag_content = match.group(1).strip()
        tag_start = match.start()
        tag_end = match.end()
        categorized = False

        for category in category_order:
            ptn = category_patterns.get(category)
            if ptn and ptn.match(tag_content):
                category_tags[category].append(tag_content)
                categorized = True
                break

        if categorized:
            matched_tag_positions.append((tag_start, tag_end))

    # 从后往前删掉原标签
    name_list = list(name)
    for start, end in sorted(matched_tag_positions, key=lambda x: -x[0]):
        del name_list[start:end]
    name_without_tags = ''.join(name_list).strip()

    # 按顺序拼装
    rearranged_tags = []
    for category in category_order:
        tags = category_tags[category]
        if tags:
            # 如果需要对标签做进一步排序，也可在这里 sort
            tags.sort(key=str.lower)
            rearranged_tags.extend(f'[{tag}]' for tag in tags)

    final_name = name_without_tags
    if rearranged_tags:
        final_name = final_name + ' ' + ' '.join(rearranged_tags)

    # 去掉多余空格
    final_name = re.sub(r'\s+', ' ', final_name).strip()

    # 再清理一下空 bracket
    final_name = clean_empty_brackets(final_name)
    return final_name


def process_filename(filename):
    """
    对单个文件名做重命名处理(若有后缀则保留)。
    """
    if filename.startswith('.'):  # 忽略隐藏文件或 .xxx 开头的文件
        return filename

    parts = filename.rsplit('.', 1)
    if len(parts) == 2:
        name, ext = parts
    else:
        name, ext = filename, ''

    name = process_name(name)
    ext = ext.strip()
    if ext:
        return name + '.' + ext
    else:
        return name


def parse_starting_tokens(name):
    """
    检测文件名开头的 [] 或 () 用来判断是否符合某些规范。
    """
    tokens = []
    pos = 0
    length = len(name)
    while pos < length:
        while pos < length and name[pos] == ' ':
            pos += 1
        if pos >= length:
            break
        if name[pos] == '[':
            start = pos
            pos += 1
            depth = 1
            while pos < length and depth > 0:
                if name[pos] == '[':
                    depth += 1
                elif name[pos] == ']':
                    depth -= 1
                pos += 1
            if depth == 0:
                token = name[start:pos]
                tokens.append(('[]', token))
            else:
                break
        elif name[pos] == '(':
            start = pos
            pos += 1
            depth = 1
            while pos < length and depth > 0:
                if name[pos] == '(':
                    depth += 1
                elif name[pos] == ')':
                    depth -= 1
                pos += 1
            if depth == 0:
                token = name[start:pos]
                tokens.append(('()', token))
            else:
                break
        else:
            break
    return tokens


def is_filename_compliant(name):
    """
    原作者定义的合规检测逻辑。
    """
    tokens = parse_starting_tokens(name)
    if not tokens:
        first_char = name.lstrip()[0] if name.lstrip() else ''
        if first_char not in ['[', '(']:
            return False
    else:
        token_types = [t[0] for t in tokens]
        if '[]' not in token_types:
            return False
        first_bracket_type = token_types[0]
        if first_bracket_type == '()':
            index_of_first_square = token_types.index('[]')
            num_paren_before_square = index_of_first_square
            if num_paren_before_square > 1:
                return False
        elif first_bracket_type == '[]':
            num_initial_square = 1
            i = 1
            while i < len(token_types) and token_types[i] == '[]':
                num_initial_square += 1
                i += 1
            if num_initial_square > 1:
                return False
            if i < len(token_types) and token_types[i] == '()':
                return False
        else:
            return False
    return True


def compare_files(file1, file2):
    """
    命名冲突时，比较修改时间和大小，返回需要移动的那个文件。
    """
    stat1 = os.stat(file1)
    stat2 = os.stat(file2)

    if stat1.st_mtime != stat2.st_mtime:
        return file1 if stat1.st_mtime < stat2.st_mtime else file2

    if stat1.st_size != stat2.st_size:
        return file1 if stat1.st_size < stat2.st_size else file2

    return file1


def ensure_temp_dir(folder_path):
    """
    必要时创建 temp 文件夹。
    """
    temp_dir = os.path.join(folder_path, 'temp')
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    return temp_dir


def main(folder_path, dry_run):
    """
    主逻辑：遍历 folder_path 下的所有文件和文件夹，处理名称，若冲突则移动到 temp。
    """
    warnings = []
    temp_dir = None

    try:
        for item in os.listdir(folder_path):
            if item == 'temp':
                continue

            item_path = os.path.join(folder_path, item)
            if os.path.isdir(item_path):
                new_name = process_name(item)
            else:
                new_name = process_filename(item)

            new_path = os.path.join(folder_path, new_name)

            if item_path != new_path:
                if dry_run:
                    print(f"Would rename: {item_path} -> {new_path}")
                else:
                    try:
                        os.rename(item_path, new_path)
                        print(f"Renamed: {item_path} -> {new_path}")
                    except OSError as e:
                        # Windows下： [WinError 183] 当目标已存在
                        if hasattr(e, 'winerror') and e.winerror == 183:
                            if temp_dir is None:
                                temp_dir = ensure_temp_dir(folder_path)
                            file_to_move = compare_files(item_path, new_path)
                            temp_path = os.path.join(temp_dir, os.path.basename(file_to_move))
                            counter = 1
                            base, ext = os.path.splitext(temp_path)
                            while os.path.exists(temp_path):
                                temp_path = f"{base}_{counter}{ext}"
                                counter += 1
                            shutil.move(file_to_move, temp_path)
                            print(f"Conflict resolved: Moved {file_to_move} to {temp_path}")
                            if file_to_move == item_path:
                                continue
                        else:
                            print(f"Error renaming {item_path}: {str(e)}")
            else:
                new_name = item  # 无变化

            # 检测是否符合命名规范
            name_only = os.path.splitext(new_name)[0]
            if not is_filename_compliant(name_only):
                warnings.append(new_name)

        if warnings:
            print("\nWARNING: The following files do not conform to the naming convention and require manual renaming:")
            for warning in warnings:
                print(warning)

    except ValueError as ve:
        print(f"Error: {ve}")
        print("Please handle the issue manually. No changes have been made.")
        sys.exit(1)


if __name__ == '__main__':
    # 若要批量处理文件夹，命令行运行:
    # python script.py /path/to/folder --dry-run
    if len(sys.argv) >= 2:
        folder_path = sys.argv[1]
        dry_run = '--dry-run' in sys.argv
        main(folder_path, dry_run)
