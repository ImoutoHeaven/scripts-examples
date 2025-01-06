import os
import sys
import re
import shutil
from datetime import datetime

def normalize_brackets(s):
    """
    First normalize all brackets to half-width form.
    """
    s = re.sub(r'[【［]', '[', s)
    s = re.sub(r'[】］]', ']', s)
    s = s.replace('（', '(').replace('）', ')')
    return s

def attempt_auto_fix_brackets(s):
    """
    Attempt to auto-fix simple bracket mismatches like [[text] -> [text]
    Returns (fixed_string, was_fixed)
    """
    left_square = s.count('[')
    right_square = s.count(']')
    left_round = s.count('(')
    right_round = s.count(')')
    
    # Try to fix double square brackets
    if left_square > right_square:
        if '[[' in s:
            s = s.replace('[[', '[', 1)
            return s, True
            
    # Try to fix double round brackets
    if left_round > right_round:
        if '((' in s:
            s = s.replace('((', '(', 1)
            return s, True
            
    return s, False

def check_brackets(s):
    """
    Check if brackets are properly paired.
    Auto-fixes simple cases and raises ValueError for unfixable cases.
    """
    # First try to auto-fix
    fixed = False
    while True:
        s, was_fixed = attempt_auto_fix_brackets(s)
        if not was_fixed:
            break
        fixed = True
    
    # Then check if properly paired
    bracket_pairs = {'[': ']', '(': ')'}
    stack = []
    
    for i, c in enumerate(s):
        if c in '[(':
            stack.append(c)
        elif c in '])':
            if not stack:
                raise ValueError(f"Unmatched closing '{c}' at position {i} in '{s}'.")
            if c != bracket_pairs[stack[-1]]:
                raise ValueError(f"Mismatched brackets: expected '{bracket_pairs[stack[-1]]}' but got '{c}' at position {i} in '{s}'.")
            stack.pop()
    
    if stack:
        raise ValueError(f"Unmatched opening '{stack[-1]}' in '{s}'.")
    
    return fixed

def process_name(name):
    # First normalize brackets
    name = normalize_brackets(name)
    
    # Then check/fix brackets
    try:
        was_fixed = check_brackets(name)
        if was_fixed:
            print(f"Auto-fixed brackets in: {name}")
    except ValueError as e:
        raise
    
    # Remove '(同人誌)'
    name = name.replace('(同人誌)', '')
    
    # Replace () with [] for specific keywords
    keywords = r'汉化|翻译|漢化|翻譯|渣翻|机翻|个人|個人|死兆修会|去码|機翻|重嵌|Pixiv|無修正|中文|繁体|想舔羽月的jio组|换源|換源|賣水槍的小男孩|機翻|同人组|烤肉man|漫画の茜|忍殺團|今泉紅太狼'
    
    # Function to handle bracket replacement
    def replace_if_keyword(match):
        content = match.group(1)
        if re.search(keywords, content, re.IGNORECASE):
            return f'[{content}]'
        return f'({content})'
    
    # Replace brackets around keywords anywhere in the name
    name = re.sub(r'\(([^()]+)\)', replace_if_keyword, name)
    
    # Move keyword bracket at the start to the end
    match = re.match(r'^(\[[^\[\]]*(?:' + keywords + r')[^\[\]]*\])\s*(.*)', name)
    if match:
        bracket_to_move = match.group(1)
        rest_of_name = match.group(2)
        name = rest_of_name.strip() + ' ' + bracket_to_move
    
    # Replace underscores
    name = name.replace('_', ' ')
    
    # Add spaces around brackets consistently first
    name = name.replace('[', ' [').replace(']', '] ')
    name = name.replace('(', ' (').replace(')', ') ')
    
    # Normalize spaces after bracket spacing
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Process v-numbers with properly spaced context
    def replace_v_number(match):
        full = match.group(0)
        # Check if it's already in brackets
        if re.search(r'\[.*' + re.escape(full) + r'.*\]', name):
            return full
        return f'[{full}]'
    
    # Process main name and extension separately
    name_parts = name.rsplit('.', 1)
    main_name = name_parts[0]
    
    # Replace v-numbers with specific context requirements
    main_name = re.sub(r'(^|[\s\]\)])v\d+(?=[\s\.\[\(]|$)', replace_v_number, main_name)
    
    # Recombine with extension if it exists
    if len(name_parts) > 1:
        name = f"{main_name}.{name_parts[1]}"
    else:
        name = main_name
    
    # Fix ") ]" cases
    name = re.sub(r'\) \]', ')]', name)
    
    # Final space normalization
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Rearrange tags according to the specified order
    name = rearrange_tags(name)
    
    return name

def rearrange_tags(name):
    """
    Rearrange tags in the filename according to specified order.
    """
    # Define the category keywords
    category_keywords = {
        'source': ['Pixiv', 'Patreon', 'Fanbox', 'fanbox', 'pixiv', 'patreon', 'DL版'],
        'translator_group': ['汉化', '翻译', '漢化', '翻譯', '渣翻', '机翻', '个人', '個人', '死兆修会', '去码', '機翻', '中文', '繁体', 
                           '想舔羽月的jio组', '賣水槍的小男孩', '同人组', '烤肉man', '漫画の茜', '忍殺團', '今泉紅太狼'],
        'translation_version': ['重嵌', '無修正', '换源', '換源'],
        'version': ['v\\d+'],
        'timestamp': None  # will handle separately
    }

    # Compile patterns
    category_patterns = {}
    for category, keywords in category_keywords.items():
        if keywords:
            if category == 'version':
                # Special handling for version pattern
                pattern = re.compile(r'^(' + '|'.join(keywords) + r')$', re.IGNORECASE)
            else:
                pattern = re.compile(r'^(' + '|'.join(map(re.escape, keywords)) + r')$', re.IGNORECASE)
            category_patterns[category] = pattern
        else:
            # For timestamp, define pattern separately
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

    # Reconstruct the final name
    final_name = name_without_tags.strip()
    if rearranged_tags:
        final_name = final_name + ' ' + ' '.join(rearranged_tags)

    return re.sub(r'\s+', ' ', final_name).strip()

def process_filename(filename):
    """
    Process a filename, handling the extension separately.
    """
    if filename[0] == '.':
        return filename
    
    name, ext = (filename.rsplit('.', 1) + [''])[:2]
    name = process_name(name)
    ext = ext.strip()
    
    if len(ext) == 0:
        return name
    return name + '.' + ext

def parse_starting_tokens(name):
    """
    Parse the starting tokens (brackets) in a filename.
    Returns list of tuples (bracket_type, token).
    """
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
                break
        else:
            break
    return tokens

def is_filename_compliant(name):
    """
    Check if filename complies with the naming convention.
    """
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

def compare_files(file1, file2):
    """
    Compare two files based on modification time and size.
    Returns the path of the file that should be moved to temp directory.
    """
    stat1 = os.stat(file1)
    stat2 = os.stat(file2)
    
    # Compare modification times
    if stat1.st_mtime != stat2.st_mtime:
        return file1 if stat1.st_mtime < stat2.st_mtime else file2
    
    # If modification times are equal, compare sizes
    if stat1.st_size != stat2.st_size:
        return file1 if stat1.st_size < stat2.st_size else file2
    
    # If both are equal, return file1 arbitrarily
    return file1

def ensure_temp_dir(folder_path):
    """Create temp directory if it doesn't exist."""
    temp_dir = os.path.join(folder_path, 'temp')
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    return temp_dir

def main(folder_path, dry_run):
    """
    Main function to process all files in the given folder.
    """
    warnings = []
    temp_dir = None
    
    try:
        for item in os.listdir(folder_path):
            if item == 'temp':  # Skip the temp directory
                continue
                
            item_path = os.path.join(folder_path, item)
            
            # Process name (for both files and folders)
            if os.path.isdir(item_path):
                new_name = process_name(item)
            else:
                new_name = process_filename(item)
                
            new_path = os.path.join(folder_path, new_name)
            
            if item_path != new_path:
                if dry_run:
                    print(f"Would rename: {item} -> {new_name}")
                else:
                    try:
                        os.rename(item_path, new_path)
                        print(f"Renamed: {item} -> {new_name}")
                    except OSError as e:
                        if e.winerror == 183:  # File exists error
                            # Create temp directory only when needed
                            if temp_dir is None:
                                temp_dir = ensure_temp_dir(folder_path)
                                
                            # Compare files and move one to temp
                            file_to_move = compare_files(item_path, new_path)
                            temp_path = os.path.join(temp_dir, os.path.basename(file_to_move))
                            
                            # Ensure unique name in temp directory
                            counter = 1
                            base, ext = os.path.splitext(temp_path)
                            while os.path.exists(temp_path):
                                temp_path = f"{base}_{counter}{ext}"
                                counter += 1
                            
                            shutil.move(file_to_move, temp_path)
                            print(f"Conflict resolved: Moved {file_to_move} to {temp_path}")
                            
                            # If the original file was moved, try renaming again
                            if file_to_move == item_path:
                                continue
                        else:
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
