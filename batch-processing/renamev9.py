import os
import sys
import re

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
                    raise ValueError(f"Unmatched closing '{closing}' in '{s}'. Please handle manually.")
        if depth != 0:
            raise ValueError(f"Unmatched opening '{opening}' in '{s}'. Please handle manually.")
    return True

def process_name(name):
    # Check for unmatched brackets and parentheses
    check_brackets(name)
    
    # Replace 【】（） with []()
    name = re.sub(r'[【［]', '[', name)
    name = re.sub(r'[】］]', ']', name)
    name = name.replace('（', '(').replace('）', ')')
    
    # New step: Remove '(同人誌)'
    name = name.replace('(同人誌)', '')
    
    # New step: Replace () with [] for specific keywords
    keywords = r'汉化|翻译|漢化|翻譯|渣翻|机翻|个人|個人|死兆修会|機翻|重嵌|Pixiv|無修正|中文|繁体|想舔羽月的jio组|换源|換源'
    name = re.sub(fr'\(({keywords})\)', r'[\1]', name)
    
    # Check for keywords in parentheses at the beginning of the name
    if name.startswith('(') and ')' in name:
        start, rest = name.split(')', 1)
        if re.search(keywords, start, re.IGNORECASE):
            name = '[' + start[1:] + ']' + rest
    
    # Move keyword bracket at the start to the end
    match = re.match(r'^(\[[^\[\]]*(?:' + keywords + r')[^\[\]]*\])\s*(.*)', name)
    if match:
        bracket_to_move = match.group(1)
        rest_of_name = match.group(2)
        name = rest_of_name.strip() + ' ' + bracket_to_move

    # Replace v2/v3/v4 with [v2]/[v3]/[v4] if not already inside []
    pattern = re.compile(r'\b(v[2-4])\b', re.IGNORECASE)
    matches = list(pattern.finditer(name))

    # Collect ranges of positions inside square brackets
    def get_bracket_ranges(s):
        stack = []
        ranges = []
        for i, c in enumerate(s):
            if c == '[':
                stack.append(i)
            elif c == ']':
                if stack:
                    start = stack.pop()
                    ranges.append((start, i))
                else:
                    # Unmatched closing bracket detected
                    raise ValueError(f"Unmatched closing ']' in '{s}'. Please handle manually.")
        if stack:
            # Unmatched opening brackets remain
            raise ValueError(f"Unmatched opening '[' in '{s}'. Please handle manually.")
        return ranges

    bracket_ranges = get_bracket_ranges(name)

    # Collect replacements
    replacements = []
    for match in matches:
        inside_bracket = False
        for start, end in bracket_ranges:
            if start <= match.start() <= end:
                inside_bracket = True
                break
        if not inside_bracket:
            replacements.append((match.start(), match.end(), f'[{match.group(1)}]'))

    # Apply replacements from end to start to avoid index shifting
    for start, end, replacement in reversed(replacements):
        name = name[:start] + replacement + name[end:]

    # Replace underscores with spaces
    name = name.replace('_', ' ')
    
    # Add spaces around brackets
    name = name.replace('[', ' [').replace(']', '] ').replace('(', ' (').replace(')', ') ')
    
    # Normalize and replace consecutive whitespaces
    name = re.sub(r'[\s_]+', ' ', name).strip()
    
    # Replace ") ]" with ")]"
    name = re.sub(r'\) \]', ')]', name)
    
    return name

def process_filename(filename):
    if filename[0] == '.':
        return filename
    
    name, ext = (filename.rsplit('.', 1) + [''])[:2]
    name = process_name(name)
    ext = ext.strip()
    
    if len(ext) == 0:
        return name
    return name + '.' + ext

def main(folder_path, dry_run):
    try:
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            
            # Process name (for both files and folders)
            if os.path.isdir(item_path):
                new_name = process_name(item)
            else:
                new_name = process_filename(item)
            new_path = os.path.join(folder_path, new_name)
            
            if item_path != new_path:
                if dry_run:
                    print(f"Rename: {item_path} -> {new_path}")
                else:
                    try:
                        os.rename(item_path, new_path)
                        print(f"Renamed: {item_path} -> {new_path}")
                    except OSError as e:
                        print(f"Error renaming {item_path}: {str(e)}")
    except ValueError as ve:
        print(f"Error: {ve}")
        print("Please handle the issue manually. No changes have been made.")
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python script.py /path/to/folder [--dry-run]")
        sys.exit(1)
    
    folder_path = sys.argv[1]
    dry_run = '--dry-run' in sys.argv
    
    main(folder_path, dry_run)
