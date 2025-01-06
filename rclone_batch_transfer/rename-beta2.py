#!/usr/bin/env python3
"""
文件重命名脚本
用于规范化文件名格式、处理标签和括号。

使用方法:
python rename_script.py /path/to/folder [--dry-run] [--debug]

参数:
    path: 要处理的文件夹路径
    --dry-run: 模拟运行，不实际重命名文件
    --debug: 启用调试模式，输出详细日志
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

# 分类关键词定义
CATEGORY_KEYWORDS = {
    'source': ['Pixiv', 'Patreon', 'Fanbox', 'fanbox', 'pixiv', 'patreon', 'DL版'],
    'translator_group': [
        '汉化', '翻译', '漢化', '翻譯', '渣翻', '机翻', '个人', '個人', 
        '死兆修会', '去码', '機翻', '中文', '繁体', '想舔羽月的jio组', 
        '賣水槍的小男孩', '同人组', '烤肉man', '漫画の茜', '忍殺團', '今泉紅太狼'
    ],
    'translation_version': ['重嵌', '無修正', '换源', '換源'],
    'version': ['v\\d+'],
    'timestamp': None  # 时间戳格式由正则表达式单独处理
}

def create_keywords_pattern() -> str:
    """创建用于匹配所有关键词的正则表达式模式。"""
    all_keywords = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        if keywords and category not in ['version', 'timestamp']:
            all_keywords.extend(keywords)
    return '|'.join(map(re.escape, all_keywords))

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

def attempt_auto_fix_brackets(text: str) -> Tuple[str, bool]:
    """
    尝试自动修复简单的括号不匹配问题。
    返回: (修复后的文本, 是否进行了修复)
    """
    left_square = text.count('[')
    right_square = text.count(']')
    left_round = text.count('(')
    right_round = text.count(')')
    
    if left_square > right_square and '[[' in text:
        return text.replace('[[', '[', 1), True
    if left_round > right_round and '((' in text:
        return text.replace('((', '(', 1), True
    
    return text, False

def check_brackets(text: str) -> bool:
    """
    检查并尝试修复括号匹配。
    返回: 是否进行了修复
    抛出: ValueError 如果存在无法修复的括号不匹配
    """
    fixed = False
    while True:
        text, was_fixed = attempt_auto_fix_brackets(text)
        if not was_fixed:
            break
        fixed = True
    
    stack = []
    bracket_pairs = {'[': ']', '(': ')'}
    
    for i, char in enumerate(text):
        if char in '[(':
            stack.append(char)
        elif char in '])':
            if not stack:
                raise ValueError(f"未匹配的右括号 '{char}' 在位置 {i}")
            if char != bracket_pairs[stack[-1]]:
                raise ValueError(f"括号不匹配: 位置 {i} 处 '{char}' 不匹配")
            stack.pop()
    
    if stack:
        raise ValueError(f"未闭合的左括号 '{stack[-1]}'")
    
    return fixed

def process_name(name: str) -> str:
    """
    处理文件名，包括格式化、标签处理和重排序。
    """
    try:
        # 标准化括号
        name = normalize_brackets(name)
        
        # 检查和修复括号
        try:
            was_fixed = check_brackets(name)
            if was_fixed:
                logger.info(f"自动修复了括号: {name}")
        except ValueError as e:
            raise ValueError(f"括号检查失败: {str(e)}")
        
        # 移除特定标记
        name = name.replace('(同人誌)', '')
        
        # 创建关键词模式
        keywords_pattern = create_keywords_pattern()
        
        # 处理括号转换
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
        
        # 标准化空格和下划线
        name = name.replace('_', ' ')
        name = re.sub(r'\s+', ' ', name)
        
        # 处理版本号
        def process_version(match):
            full = match.group(0)
            if re.search(r'\[.*' + re.escape(full) + r'.*\]', name):
                return full
            return f'[{full}]'
        
        name_parts = name.rsplit('.', 1)
        main_name = name_parts[0]
        main_name = re.sub(
            r'(^|[\s\]\)])v\d+(?=[\s\.\[\(]|$)',
            process_version,
            main_name
        )
        
        # 重组文件名
        if len(name_parts) > 1:
            name = f"{main_name}.{name_parts[1]}"
        else:
            name = main_name
            
        # 最终清理
        name = re.sub(r'\) \]', ')]', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        # 重排序标签
        return rearrange_tags(name)
        
    except Exception as e:
        logger.error(f"处理文件名时出错: {str(e)}")
        raise

def rearrange_tags(name: str) -> str:
    """
    按照预定义的顺序重新排列标签。
    """
    # 编译分类模式
    category_patterns = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        if keywords:
            pattern = '|'.join(keywords if category == 'version' else map(re.escape, keywords))
            category_patterns[category] = re.compile(f'^({pattern})$', re.IGNORECASE)
        elif category == 'timestamp':
            category_patterns[category] = re.compile(r'^(\d{6,8}|\d{6,8}\d{2})$')
    
    # 定义标签顺序
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

def process_file(file_path: str, dry_run: bool = False) -> Optional[str]:
    """
    处理单个文件，返回新的文件名或None（如果发生错误）。
    """
    try:
        filename = os.path.basename(file_path)
        if filename.startswith('.'):
            return None
            
        # 处理文件名
        name, ext = os.path.splitext(filename)
        new_name = process_name(name)
        if ext:
            new_name = f"{new_name}{ext}"
            
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

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="文件重命名工具")
    parser.add_argument("folder", help="要处理的文件夹路径")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不实际重命名文件")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
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
        
        for item in os.listdir(folder_path):
            if item == 'temp':
                continue
                
            item_path = os.path.join(folder_path, item)
            
            try:
                if os.path.isfile(item_path):
                    new_name = process_file(item_path, dry_run)
                    if new_name:
                        new_path = os.path.join(folder_path, new_name)
                        
                        if dry_run:
                            logger.info(f"将重命名: {item} -> {new_name}")
                            processed_count += 1
                        else:
                            try:
                                if os.path.exists(new_path) and new_path != item_path:
                                    # 处理文件冲突
                                    temp_path = ensure_unique_path(os.path.join(temp_dir, item))
                                    logger.info(f"移动冲突文件到临时目录: {item} -> {os.path.basename(temp_path)}")
                                    shutil.move(item_path, temp_path)
                                else:
                                    # 直接重命名
                                    os.rename(item_path, new_path)
                                    logger.info(f"已重命名: {item} -> {new_name}")
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
        
    except Exception as e:
        logger.error(f"执行过程中出错: {str(e)}")
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
