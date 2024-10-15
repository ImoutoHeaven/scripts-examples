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
    keywords = r'汉化|翻译|漢化|翻譯|渣翻|机翻|个人|個人|死兆修会|機翻|重嵌|Pixiv|無修正|中文|繁体|想舔羽月的jio组|换源|換源|賣水槍的小男孩|機翻|同人组|烤肉man|漫画の茜|忍殺團'
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
    
    # Rearrange tags according to the specified order
    name = rearrange_tags(name)
    
    return name

def rearrange_tags(name):
    # Define the category keywords
    category_keywords = {
        'source': ['Pixiv', 'Patreon', 'Fanbox', 'fanbox', 'pixiv', 'patreon', 'DL版'],
        'translator_group': ['汉化', '翻译', '漢化', '翻譯', '渣翻', '机翻', '个人', '個人', '死兆修会', '機翻', '中文', '繁体', '想舔羽月的jio组', '賣水槍的小男孩', '同人组', '烤肉man', '漫画の茜', '忍殺團'],
        'translation_version': ['重嵌', '無修正', '换源', '換源'],
        'version': ['v2', 'v3', 'v4'],
        'timestamp': None  # will handle separately
    }

    # Compile patterns
    category_patterns = {}
    for category, keywords in category_keywords.items():
        if keywords:
            pattern = re.compile(r'^(' + '|'.join(map(re.escape, keywords)) + r')$', re.IGNORECASE)
            category_patterns[category] = pattern
        else:
            # For timestamp, we define a pattern separately
            category_patterns['timestamp'] = re.compile(r'^(\d{6,8}|\d{6,8}\d{2})$')

    # Define the order
    category_order = ['source', 'translator_group', 'translation_version', 'version', 'timestamp']

    # Use re.finditer to find all []-bracketed tags
    bracket_tag_pattern = re.compile(r'\[([^\[\]]+)\]')
    matched_tag_positions = []
    category_tags = {category: [] for category in category_order}

    # Iterate over matches
    for match in re.finditer(bracket_tag_pattern, name):
        tag_content = match.group(1).strip()
        tag_start = match.start()
        tag_end = match.end()
        categorized = False
        for category in category_order:
            pattern = category_patterns[category]
            if pattern.match(tag_content):
                # Collect the tag into the category
                category_tags[category].append(tag_content)
                categorized = True
                break
        if categorized:
            # Record position to remove from name
            matched_tag_positions.append((tag_start, tag_end))

    # Remove matched tags from the name, starting from the end to avoid index shifting
    name_list = list(name)
    for start, end in sorted(matched_tag_positions, key=lambda x: -x[0]):  # reverse order
        del name_list[start:end]
    name_without_tags = ''.join(name_list).strip()

    # Reconstruct the tags in order
    rearranged_tags = []
    for category in category_order:
        tags = category_tags[category]
        if tags:
            tags.sort(key=str.lower)
            rearranged_tags.extend([f'[{tag}]' for tag in tags])

    # Now, reconstruct the final name
    # First, assemble the name without the matched tags
    final_name = name_without_tags.strip()

    # Append the rearranged tags
    if rearranged_tags:
        final_name = final_name + ' ' + ' '.join(rearranged_tags)

    # Clean up spaces
    final_name = re.sub(r'\s+', ' ', final_name).strip()

    return final_name

def process_filename(filename):
    if filename[0] == '.':
        return filename
    
    name, ext = (filename.rsplit('.', 1) + [''])[:2]
    name = process_name(name)
    ext = ext.strip()
    
    if len(ext) == 0:
        return name
    return name + '.' + ext

def parse_starting_tokens(name):
    tokens = []
    pos = 0
    length = len(name)
    while pos < length:
        # Skip any leading spaces
        while pos < length and name[pos] == ' ':
            pos += 1
        if pos >= length:
            break
        if name[pos] == '[':
            # Parse token enclosed in []
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
                # Unmatched '['
                break
        elif name[pos] == '(':
            # Parse token enclosed in ()
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
                # Unmatched '('
                break
        else:
            # Not a bracketed token, break
            break
    return tokens

def is_filename_compliant(name):
    tokens = parse_starting_tokens(name)
    # If no tokens parsed, check if the first character is not '[' or '(', warn
    if not tokens:
        # If the first non-space character is not '[' or '(', warn
        first_char = name.lstrip()[0] if name.lstrip() else ''
        if first_char not in ['[', '(']:
            return False
    else:
        token_types = [t[0] for t in tokens]
        if '[]' not in token_types:
            # No '[]' token, warn
            return False
        first_bracket_type = token_types[0]
        if first_bracket_type == '()':
            # Tokens start with '()'
            # Check if there are two or more '()' before any '[]'
            index_of_first_square = token_types.index('[]')
            num_paren_before_square = index_of_first_square
            if num_paren_before_square > 1:
                return False
        elif first_bracket_type == '[]':
            # Tokens start with '[]'
            # Check if there are multiple '[]' at the start
            num_initial_square = 1
            i = 1
            while i < len(token_types) and token_types[i] == '[]':
                num_initial_square += 1
                i += 1
            if num_initial_square > 1:
                return False
            # If next token is '()', warn
            if i < len(token_types) and token_types[i] == '()':
                return False
        else:
            # First token is neither '[]' nor '()', warn
            return False
    return True

def main(folder_path, dry_run):
    warnings = []
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
            else:
                new_name = item  # Name remains the same

            # Check for compliance
            name_only = os.path.splitext(new_name)[0]
            if not is_filename_compliant(name_only):
                warnings.append(new_name)

        # Output warnings
        if warnings:
            print("\nWARNING: The following files do not conform to the naming convention and require manual renaming:")
            for warning in warnings:
                print(warning)
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
