import os
import sys
import re
import shutil
from datetime import datetime

def clean_empty_brackets(s: str) -> str:
    prev = None
    result = s
    pattern_empty_square = re.compile(r'\[\s*\]')
    pattern_empty_paren = re.compile(r'\(\s*\)')
    while prev != result:
        prev = result
        result = pattern_empty_square.sub('', result)
        result = pattern_empty_paren.sub('', result)
        result = re.sub(r'\s+', ' ', result).strip()
    return result

def light_bracket_fix(s: str) -> str:
    cnt_open_sq = s.count('[')
    cnt_close_sq = s.count(']')
    cnt_open_par = s.count('(')
    cnt_close_par = s.count(')')

    if cnt_open_sq == cnt_close_sq + 1:
        s = re.sub(r'\[\[', '[', s, count=1)
    elif cnt_close_sq == cnt_open_sq + 1:
        s = re.sub(r'\]\]', ']', s, count=1)

    if cnt_open_par == cnt_close_par + 1:
        s = re.sub(r'\(\(', '(', s, count=1)
    elif cnt_close_par == cnt_open_par + 1:
        s = re.sub(r'\)\)', ')', s, count=1)

    return s

def check_brackets(s):
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

category_keywords = {
    'source': [
        'Pixiv', 'Patreon', 'Fanbox', 'fanbox', 'pixiv', 'patreon', 'DL版'
    ],
    'translator_group': [
        '汉化','翻译','漢化','翻譯','渣翻','机翻','个人','個人','死兆修会',
        '機翻','中文','繁体','想舔羽月的jio组','賣水槍的小男孩','同人组',
        '烤肉man','漫画の茜','忍殺團','今泉紅太狼','悠月工房','个汉','個漢','同好会'
    ],
    'translation_version': [
        '重嵌', '無修正', '无修正', '换源', '換源', '去码', '水印', '渣嵌'
    ],
    'version': [
        'v2','v3','v4','v5','v6','v7','v8','v9','v10','v11','v12'
    ],
    'timestamp': None
}

part_keys_for_parentheses = ('source', 'translator_group', 'translation_version')

category_order = [
    'translator_group',    # [汉化组名]
    'translation_version', # [无修正]等版本类别
    'source',              # [DL版]等来源标记
    'version',            # [v2]等版本号
    'timestamp'           # 时间戳放最后
]

def gather_bracket_keywords(cat_dict, keys):
    all_kw = []
    for k in keys:
        vals = cat_dict.get(k)
        if vals:
            all_kw.extend(vals)
    return list(dict.fromkeys(all_kw))

def replace_paren_with_bracket_on_keywords(name: str, keywords_list) -> str:
    pattern_keywords = '|'.join(map(re.escape, keywords_list))
    pattern_paren = re.compile(r'\([^)]*(?:' + pattern_keywords + r')[^)]*\)', re.IGNORECASE)

    def _replace(m):
        content = m.group(0)
        inner = content[1:-1]
        return "[" + inner + "]"

    return pattern_paren.sub(_replace, name)

def create_category_pattern(category, words):
    if category == 'translator_group':
        keywords = '|'.join(map(re.escape, words))
        return re.compile(r'\[[^\]]*(?:' + keywords + r')[^\]]*\]', re.IGNORECASE)
    elif category in ('source', 'translation_version'):
        keywords = '|'.join(map(re.escape, words))
        return re.compile(r'\[[^\]]*(?:' + keywords + r')[^\]]*\]', re.IGNORECASE)
    elif category in ('version', 'timestamp'):
        return re.compile(r'^(' + '|'.join(map(re.escape, words)) + r')$', re.IGNORECASE)
    else:
        return None

def standardize_timestamp(timestamp_str):
    if not timestamp_str:
        return None
        
    digits = ''.join(filter(str.isdigit, timestamp_str))
    
    if len(digits) == 6:  # YYMMDD -> YYYYMMDD
        return f"20{digits}"
    elif len(digits) == 8:  # YYYYMMDD
        return digits
    elif len(digits) == 10:  # YYYYMMDDvv
        return digits[:8]
    return None

def process_version_tag(name):
    """处理版本号标签，确保是单层方括号"""
    # 先处理已经在方括号中的版本号，确保只有一层方括号
    pattern_bracketed = re.compile(r'\[+v(\d+(?:\.\d+)?)\]+', re.IGNORECASE)
    name = pattern_bracketed.sub(lambda m: f'[v{m.group(1)}]', name)
    
    # 再处理没有方括号的版本号
    pattern = re.compile(r'(?<![A-Za-z0-9\[\]])v(\d+(?:\.\d+)?)(?![A-Za-z0-9\[\]])', re.IGNORECASE)
    name = pattern.sub(lambda m: f'[v{m.group(1)}]', name)
    
    return name

def rearrange_tags(name):
    category_patterns = {}
    for category, words in category_keywords.items():
        if words:
            pattern = create_category_pattern(category, words)
            category_patterns[category] = pattern
        else:
            if category == 'timestamp':
                category_patterns['timestamp'] = re.compile(r'^(\d{6}|\d{8}|\d{10})$')

    bracket_tag_pattern = re.compile(r'\[([^\[\]]+)\]')
    matched_tag_positions = []
    category_tags = {cat: [] for cat in category_order}

    for match in re.finditer(bracket_tag_pattern, name):
        tag_content = match.group(1).strip()
        tag_start = match.start()
        tag_end = match.end()
        categorized = False

        if category_patterns['timestamp'].match(tag_content):
            std_timestamp = standardize_timestamp(tag_content)
            if std_timestamp:
                category_tags['timestamp'].append(std_timestamp)
                categorized = True
                matched_tag_positions.append((tag_start, tag_end))
                continue

        for category in category_order:
            if category == 'timestamp':
                continue
            ptn = category_patterns.get(category)
            if ptn and ptn.match(f'[{tag_content}]'):
                category_tags[category].append(tag_content)
                categorized = True
                matched_tag_positions.append((tag_start, tag_end))
                break

    name_list = list(name)
    for start, end in sorted(matched_tag_positions, key=lambda x: -x[0]):
        del name_list[start:end]
    name_without_tags = ''.join(name_list).strip()

    rearranged_tags = []
    for category in category_order:
        tags = category_tags[category]
        if tags:
            tags.sort(key=str.lower)
            rearranged_tags.extend(f'[{tag}]' for tag in tags)

    final_name = name_without_tags
    if rearranged_tags:
        final_name = final_name + ' ' + ' '.join(rearranged_tags)

    final_name = re.sub(r'\s+', ' ', final_name).strip()
    final_name = clean_empty_brackets(final_name)
    return final_name

def process_name(name):
    name = clean_empty_brackets(name)

    name = re.sub(r'[【［]', '[', name)
    name = re.sub(r'[】］]', ']', name)
    name = name.replace('（', '(').replace('）', ')')

    name = light_bracket_fix(name)
    name = clean_empty_brackets(name)

    try:
        check_brackets(name)
    except ValueError:
        name = light_bracket_fix(name)
        name = clean_empty_brackets(name)
        check_brackets(name)

    name = name.replace('(同人誌)', '')
    name = clean_empty_brackets(name)

    bracket_keywords = gather_bracket_keywords(category_keywords, part_keys_for_parentheses)
    name = replace_paren_with_bracket_on_keywords(name, bracket_keywords)
    name = clean_empty_brackets(name)

    name = process_version_tag(name)
    name = clean_empty_brackets(name)

    move_keywords = '|'.join(map(re.escape, bracket_keywords))
    match = re.match(r'^(\[[^\[\]]*(?:' + move_keywords + r')[^\[\]]*\])\s*(.*)', name, flags=re.IGNORECASE)
    if match:
        bracket_to_move = match.group(1)
        rest_of_name = match.group(2)
        name = rest_of_name.strip() + ' ' + bracket_to_move
    name = clean_empty_brackets(name)

    name = name.replace('_', ' ')
    name = name.replace('[', ' [').replace(']', '] ').replace('(', ' (').replace(')', ') ')
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'\) \]', ')]', name)
    name = re.sub(r'\[ ', '[', name)
    name = re.sub(r' \]', ']', name)
    name = clean_empty_brackets(name)

    name = rearrange_tags(name)
    name = clean_empty_brackets(name)

    return name

def process_filename(filename):
    if filename.startswith('.'):
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

def is_filename_compliant(name):
    if not re.search(r'\[[^\]]+\]', name):
        return False
        
    tags = re.findall(r'\[[^\]]+\]', name)
    if not tags:
        return False
        
    version_tag = None
    timestamp_tag = None
    
    for tag in tags:
        if re.search(r'\[v\d+(?:\.\d+)?\]', tag, re.IGNORECASE):
            version_tag = tag
        elif re.search(r'\[(?:\d{6}|\d{8}|\d{10})\]', tag):
            timestamp_tag = tag
            
    if version_tag and timestamp_tag:
        version_pos = name.rindex(version_tag)
        timestamp_pos = name.rindex(timestamp_tag)
        if version_pos > timestamp_pos:
            return False
            
    return True

def parse_starting_tokens(name):
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

def compare_files(file1, file2):
    stat1 = os.stat(file1)
    stat2 = os.stat(file2)

    if stat1.st_mtime != stat2.st_mtime:
        return file1 if stat1.st_mtime < stat2.st_mtime else file2

    if stat1.st_size != stat2.st_size:
        return file1 if stat1.st_size < stat2.st_size else file2

    return file1

def ensure_temp_dir(folder_path):
    temp_dir = os.path.join(folder_path, 'temp')
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    return temp_dir

def main(folder_path, dry_run):
    warnings = []
    temp_dir = None
    total_files = 0
    processed_files = 0

    try:
        for _, _, files in os.walk(folder_path):
            total_files += len(files)

        for root, dirs, files in os.walk(folder_path):
            if 'temp' in dirs:
                dirs.remove('temp')
                
            for item in files:
                item_path = os.path.join(root, item)
                processed_files += 1
                
                print(f"\rProcessing {processed_files}/{total_files} files...", end="")

                try:
                    new_name = process_filename(item)
                    new_path = os.path.join(root, new_name)

                    if item_path != new_path:
                        if dry_run:
                            print(f"\nWould rename: {item_path} -> {new_path}")
                        else:
                            try:
                                os.rename(item_path, new_path)
                                print(f"\nRenamed: {item_path} -> {new_path}")
                            except OSError as e:
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
                                    print(f"\nConflict resolved: Moved {file_to_move} to {temp_path}")
                                    if file_to_move == item_path:
                                        continue
                                else:
                                    print(f"\nError renaming {item_path}: {str(e)}")
                                    warnings.append((item_path, str(e)))

                    name_only = os.path.splitext(new_name)[0]
                    if not is_filename_compliant(name_only):
                        warnings.append((new_path, "Does not conform to naming convention"))

                except Exception as e:
                    print(f"\nError processing {item_path}: {str(e)}")
                    warnings.append((item_path, str(e)))

        print("\nProcessing complete!")

        if warnings:
            print("\nWARNING: The following files had issues:")
            for file_path, error in warnings:
                print(f"{file_path}: {error}")

    except Exception as e:
        print(f"\nError: {e}")
        print("Please handle the issue manually. No changes have been made.")
        sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python script.py /path/to/folder [--dry-run]")
        sys.exit(1)
        
    folder_path = sys.argv[1]
    dry_run = '--dry-run' in sys.argv
    
    if not os.path.exists(folder_path):
        print(f"Error: Path '{folder_path}' does not exist.")
        sys.exit(1)
        
    if dry_run:
        print("Running in dry-run mode - no actual changes will be made")
        
    main(folder_path, dry_run)
