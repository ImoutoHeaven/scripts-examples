#!/usr/bin/env python3
"""
文件重命名工具

用于规范化文件名格式：
1. 标准化括号（全角转半角）
2. 验证和修复括号匹配
3. 标准化空格
4. 按规则重排序标签

使用方法:
    python rename_script.py <folder_path> [--dry-run] [--debug] [-i]

参数:
    folder_path: 要处理的文件夹路径
    --dry-run: 模拟运行，不实际重命名文件
    --debug: 启用调试模式，输出详细日志
    -i: 交互式预览模式
"""

import os
import sys
import re
import shutil
import logging
import argparse
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('rename.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 关键词分类定义
CATEGORY_KEYWORDS = {
    'source': ['Pixiv', 'Patreon', 'Fanbox', 'fanbox', 'pixiv', 'patreon', 'DL版'],
    'translator_group': [
        '汉化', '翻译', '漢化', '翻譯', '渣翻', '机翻', '个人', '個人', 
        '死兆修会', '去码', '機翻', '中文', '繁体', '想舔羽月的jio组', 
        '賣水槍的小男孩', '同人组', '烤肉man', '漫画の茜', '忍殺團', '今泉紅太狼'
    ],
    'translation_version': ['重嵌', '無修正', '换源', '換源'],
    'version': ['v\\d+'],
    'timestamp': None  # 时间戳使用正则匹配
}

def normalize_brackets(text: str) -> str:
    """标准化括号，将全角括号转换为半角括号。"""
    replacements = {
        '【': '[', '［': '[',
        '】': ']', '］': ']',
        '（': '(', '）': ')'
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

def attempt_auto_fix_brackets(s: str) -> Tuple[str, bool]:
    """
    尝试自动修复简单的括号不匹配。
    返回: (修复后的字符串, 是否进行了修复)
    """
    left_square = s.count('[')
    right_square = s.count(']')
    left_round = s.count('(')
    right_round = s.count(')')
    
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"括号统计: [ = {left_square}, ] = {right_square}, ( = {left_round}, ) = {right_round}")
    
    # 只处理明显的双括号错误
    if '[[' in s:
        s = s.replace('[[', '[', 1)
        return s, True
    elif ']]' in s:
        s = s.replace(']]', ']', 1)
        return s, True
    elif '((' in s:
        s = s.replace('((', '(', 1)
        return s, True
    elif '))' in s:
        s = s.replace('))', ')', 1)
        return s, True
        
    return s, False

def validate_brackets(s: str) -> None:
    """
    严格检查括号是否正确配对，如果有错误则抛出异常。
    支持嵌套括号结构。
    """
    stack = []
    bracket_pairs = {'[': ']', '(': ')'}
    
    for i, char in enumerate(s):
        if char in '[(':  # 左括号
            stack.append((char, i))
        elif char in '])':  # 右括号
            if not stack:  # 栈空说明有未匹配的右括号
                raise ValueError(f"位置 {i} 处有未匹配的右括号 '{char}'")
            
            last_left, pos = stack[-1]
            if bracket_pairs[last_left] != char:  # 括号类型不匹配
                raise ValueError(f"括号不匹配：位置 {i} 处期望 '{bracket_pairs[last_left]}' 但遇到 '{char}'")
            
            stack.pop()  # 匹配成功，弹出左括号
    
    # 检查是否有未闭合的左括号
    if stack:
        positions = [f"'{b[0]}' (位置 {pos})" for b, pos in stack]
        raise ValueError(f"存在未闭合的左括号: {', '.join(positions)}")

def create_keywords_pattern() -> str:
    """创建用于匹配所有关键词的正则表达式模式。"""
    all_keywords = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        if keywords and category not in ['version', 'timestamp']:
            all_keywords.extend(keywords)
    return '|'.join(map(re.escape, all_keywords))

def is_filename_compliant(name: str) -> bool:
    """
    检查文件名是否符合命名规范。
    """
    # 移除扩展名进行检查
    name = os.path.splitext(name)[0]
    
    def parse_starting_tokens(text: str) -> List[Tuple[str, str]]:
        """解析文件名开头的括号标记。"""
        tokens = []
        pos = 0
        length = len(text)
        
        while pos < length:
            # 跳过前导空格
            while pos < length and text[pos].isspace():
                pos += 1
            if pos >= length:
                break
            
            if text[pos] == '[':
                start = pos
                pos += 1
                depth = 1
                while pos < length and depth > 0:
                    if text[pos] == '[':
                        depth += 1
                    elif text[pos] == ']':
                        depth -= 1
                    pos += 1
                if depth == 0:
                    tokens.append(('[]', text[start:pos]))
                else:
                    break
            elif text[pos] == '(':
                start = pos
                pos += 1
                depth = 1
                while pos < length and depth > 0:
                    if text[pos] == '(':
                        depth += 1
                    elif text[pos] == ')':
                        depth -= 1
                    pos += 1
                if depth == 0:
                    tokens.append(('()', text[start:pos]))
                else:
                    break
            else:
                break
        return tokens
    
    tokens = parse_starting_tokens(name)
    
    # 如果没有标记，检查第一个字符
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
            # 检查第一个 [] 前是否有多于一个 ()
            index_of_first_square = token_types.index('[]')
            if index_of_first_square > 1:
                return False
        elif first_bracket_type == '[]':
            # 检查是否有多个连续的开头 []
            num_initial_square = 1
            i = 1
            while i < len(token_types) and token_types[i] == '[]':
                num_initial_square += 1
                i += 1
            if num_initial_square > 1:
                return False
            # 检查下一个是否为 ()
            if i < len(token_types) and token_types[i] == '()':
                return False
    
    return True

def rearrange_tags(name: str) -> str:
    """
    按预定义的顺序重新排列标签。
    """
    # 编译分类模式
    category_patterns = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        if keywords:
            pattern = '|'.join(keywords if category == 'version' else map(re.escape, keywords))
            category_patterns[category] = re.compile(f'^({pattern})$', re.IGNORECASE)
        elif category == 'timestamp':
            category_patterns[category] = re.compile(r'^(\d{6,8}|\d{6,8}\d{2})$')
    
    # 标签顺序
    category_order = ['source', 'translator_group', 'translation_version', 'version', 'timestamp']
    
    # 查找所有标签
    bracket_tags = re.finditer(r'\[([^\[\]]+)\]', name)
    matched_positions = []
    category_tags = {category: [] for category in category_order}
    
    # 分类标签
    for match in bracket_tags:
        content = match.group(1).strip()
        start, end = match.span()
        
        for category in category_order:
            if category_patterns[category].match(content):
                category_tags[category].append(content)
                matched_positions.append((start, end))
                break
    
    # 移除原有标签
    name_chars = list(name)
    for start, end in sorted(matched_positions, reverse=True):
        del name_chars[start:end]
    name_without_tags = ''.join(name_chars).strip()
    
    # 重建标签
    new_tags = []
    for category in category_order:
        tags = category_tags[category]
        if tags:
            tags.sort(key=str.lower)
            new_tags.extend(f'[{tag}]' for tag in tags)
    
    # 组合最终文件名
    if new_tags:
        return f"{name_without_tags} {' '.join(new_tags)}"
    return name_without_tags

def process_name(name: str) -> str:
    """处理文件名，包括格式化和括号处理。"""
    try:
        # 标准化括号
        name = normalize_brackets(name)
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"处理前的文件名: {name}")
        
        # 自动修复括号
        was_fixed = False
        original = name
        while True:
            name, fixed = attempt_auto_fix_brackets(name)
            if not fixed:
                break
            was_fixed = True
            
        if was_fixed and logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"修复后的文件名: {name}")
            
        # 验证括号
        validate_brackets(name)
        
        # 处理关键词标签
        name = name.replace('(同人誌)', '')
        
        # 替换包含关键词的小括号为中括号
        keywords_pattern = create_keywords_pattern()
        
        def replace_if_keyword(match):
            content = match.group(1)
            if re.search(keywords_pattern, content, re.IGNORECASE):
                return f'[{content}]'
            return f'({content})'
        
        name = re.sub(r'\(([^()]+)\)', replace_if_keyword, name)
        
        # 移动开头的关键词标签到末尾
        match = re.match(f'^(\\[[^\\[\\]]*(?:{keywords_pattern})[^\\[\\]]*\\])\\s*(.*)', name)
        if match:
            bracket_to_move = match.group(1)
            rest_of_name = match.group(2)
            name = f"{rest_of_name.strip()} {bracket_to_move}"
            
        # 规范化空格
        name = re.sub(r'\s*\[\s*', ' [', name)  # 左方括号前后的空格
        name = re.sub(r'\s*\]\s*', '] ', name)  # 右方括号前后的空格
        name = re.sub(r'\s*\(\s*', ' (', name)  # 左圆括号前后的空格
        name = re.sub(r'\s*\)\s*', ') ', name)  # 右圆括号前后的空格
        name = re.sub(r'\s+', ' ', name).strip()
        
        # 处理版本号
        name_parts = name.rsplit('.', 1)
        main_name = name_parts[0]
        main_name = re.sub(
            r'(^|[\s\]\)])v\d+(?=[\s\.\[\(]|$)',
            lambda m: f'[{m.group(0)}]' if not re.search(r'\[.*' + re.escape(m.group(0)) + r'.*\]', name) else m.group(0),
            main_name
        )
        
        name = f"{main_name}.{name_parts[1]}" if len(name_parts) > 1 else main_name
        
        # 重排序标签
        name = rearrange_tags(name)
        
        # 添加新的处理：将 ") ]" 替换为 ")]"
        name = re.sub(r'\)\s*\]', ')]', name)
            
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"最终处理后的文件名: {name}")
            
        return name
            
    except Exception as e:
        logger.error(f"处理文件名时出错: {str(e)}")
        raise

def process_file(file_path: str, dry_run: bool = False) -> Optional[str]:
    """
    处理单个文件，返回新的文件名或None。
    """
    try:
        filename = os.path.basename(file_path)
        if filename.startswith('.'):
            return None
            
        new_name = process_name(filename)
        return new_name if new_name != filename else None
        
    except Exception as e:
        logger.error(f"处理文件 {file_path} 时出错: {str(e)}")
        return None

def ensure_unique_path(path: str) -> str:
    """确保文件路径唯一，如果存在则添加数字后缀。"""
    if not os.path.exists(path):
        return path
        
    base, ext = os.path.splitext(path)
    counter = 1
    while True:
        new_path = f"{base}_{counter}{ext}"
        if not os.path.exists(new_path):
            return new_path
        counter += 1

def preview_names(filenames: List[str]) -> None:
    """预览文件名处理结果。"""
    logger.info("\n预览重命名结果:")
    logger.info("-" * 120)
    logger.info(f"{'原文件名':<60} → {'新文件名':<60}")
    logger.info("-" * 120)
    
    non_compliant_files = []
    
    for filename in filenames:
        try:
            new_name = process_name(filename.strip())
            if not is_filename_compliant(new_name):
                non_compliant_files.append(new_name)
            
            logger.info(f"{filename:<60} → {new_name:<60}")
                
        except ValueError as e:
            # 对于验证错误（如括号不匹配），只显示错误信息
            logger.error(f"处理文件名出错: {filename}")
            logger.error(f"错误原因: {str(e)}")
            
        except Exception as e:
            # 对于其他错误，显示详细的错误信息
            logger.error(f"处理文件时发生未知错误: {filename}")
            logger.error(f"错误原因: {str(e)}")
    
    logger.info("-" * 120)
    
    # 输出不符合命名规范的文件列表
    if non_compliant_files:
        logger.warning("\n警告：以下文件不遵循标准命名规范，建议手动检查:")
        for file in non_compliant_files:
            logger.warning(f"  - {file}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="文件重命名工具")
    parser.add_argument("folder", help="要处理的文件夹路径")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不实际重命名文件")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument("-i", "--interactive", action="store_true", help="交互式预览模式")
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # 交互式预览模式
    if args.interactive:
        logger.info("进入交互式预览模式")
        logger.info("请输入要预览的文件名(每行一个)")
        logger.info("输入两个空行结束输入\n")
        
        filenames = []
        empty_line_count = 0
        
        while empty_line_count < 2:
            try:
                line = input().strip()
                if not line:
                    empty_line_count += 1
                else:
                    empty_line_count = 0
                    filenames.append(line)
            except EOFError:
                break
            except KeyboardInterrupt:
                logger.info("\n用户中断输入")
                return 1
        
        if filenames:
            preview_names(filenames)
        else:
            logger.warning("未输入任何文件名")
        return 0
    
    # 常规处理模式
    folder_path = args.folder
    dry_run = args.dry_run
    
    if not os.path.isdir(folder_path):
        logger.error(f"文件夹不存在: {folder_path}")
        return 1
    
    # 创建临时文件夹
    temp_dir = os.path.join(folder_path, 'temp')
    if not dry_run and not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    
    try:
        processed_count = 0
        skipped_count = 0
        error_count = 0
        non_compliant_files = []
        
        for item in os.listdir(folder_path):
            if item == 'temp':
                continue
                
            item_path = os.path.join(folder_path, item)
            
            try:
                if os.path.isfile(item_path):
                    new_name = process_file(item_path, dry_run)
                    if new_name:
                        # 检查新文件名是否符合命名规范
                        if not is_filename_compliant(new_name):
                            non_compliant_files.append(new_name)
                        
                        new_path = os.path.join(folder_path, new_name)
                        
                        if dry_run:
                            logger.info(f"将重命名: {item} → {new_name}")
                            processed_count += 1
                        else:
                            try:
                                if os.path.exists(new_path) and new_path != item_path:
                                    # 处理文件冲突
                                    temp_path = ensure_unique_path(os.path.join(temp_dir, item))
                                    logger.info(f"移动冲突文件到临时目录: {item} → {os.path.basename(temp_path)}")
                                    shutil.move(item_path, temp_path)
                                else:
                                    # 直接重命名
                                    os.rename(item_path, new_path)
                                    logger.info(f"已重命名: {item} → {new_name}")
                                    processed_count += 1
                            except OSError as e:
                                logger.error(f"重命名文件时出错 {item}: {str(e)}")
                                error_count += 1
                    else:
                        skipped_count += 1
                        
            except Exception as e:
                logger.error(f"处理 {item} 时出错: {str(e)}")
                error_count += 1
        
        # 输出统计信息
        logger.info(f"\n处理完成:")
        logger.info(f"处理文件数: {processed_count}")
        logger.info(f"跳过文件数: {skipped_count}")
        logger.info(f"错误文件数: {error_count}")
        
        # 输出不符合命名规范的文件列表
        if non_compliant_files:
            logger.warning("\n警告：以下文件不遵循标准命名规范，建议手动检查:")
            for file in non_compliant_files:
                logger.warning(f"  - {file}")
        
    except Exception as e:
        logger.error(f"执行过程中出错: {str(e)}")
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
