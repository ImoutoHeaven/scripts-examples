#!/usr/bin/env python3
import os
import sys
import shutil
import argparse
import platform
import subprocess
import logging
from pathlib import Path
from typing import List, Tuple, Set

# 允许的文件扩展名（不区分大小写）
ALLOWED_EXTENSIONS = {
    # 视频格式
    'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'm4v', '3gp', 'mpeg', 'mpg', 'ts',
    # 音频格式
    'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'wma', 'ac3', 'dts', 'aiff', 'ape',
    # 图片格式
    'jpg', 'jpeg', 'png', 'webp', 'gif', 'avif', 'bmp', 'tiff', 'tif', 'heic', 'heif',
    # 文档和电子书格式
    'pdf', 'epub', 'mobi', 'azw', 'azw3', 'txt', 'doc', 'docx', 'rtf', 'odt',
    # 其他文本格式
    'md', 'markdown', 'rst', 'tex', 'log', 'ini', 'conf', 'cfg', 'json', 'xml', 
    'yml', 'yaml', 'toml', 'csv', 'tsv', 'properties', 'env',
    # 字幕和歌词
    'srt', 'ass', 'ssa', 'vtt', 'sub', 'idx', 'lrc'
}

def setup_logging():
    """设置日志配置"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def check_file_extension(file_path: Path) -> bool:
    """
    检查文件是否有合法的扩展名
    返回True表示文件合法，False表示不合法
    """
    # 如果文件没有后缀，返回False
    if not file_path.suffix:
        return False
    
    # 获取后缀名（去掉点号并转换为小写）
    ext = file_path.suffix[1:].lower()
    return ext in ALLOWED_EXTENSIONS

def validate_directory_structure(root_path: Path, logger: logging.Logger) -> Tuple[bool, List[str]]:
    """
    验证目录结构的合法性
    返回 (是否合法, 警告消息列表)
    """
    warnings = []
    
    # 检查深度1是否存在文件
    for item in root_path.iterdir():
        if item.is_file():
            warnings.append(f"错误: 在根目录 {root_path} 下发现文件: {item.name}")
    
    if warnings:
        return False, warnings
    
    # 检查所有子文件夹中的文件扩展名
    for folder in root_path.iterdir():
        if not folder.is_dir():
            continue
            
        # 递归遍历文件夹中的所有文件
        for file_path in folder.rglob('*'):
            if file_path.is_file():
                if not check_file_extension(file_path):
                    relative_path = file_path.relative_to(root_path)
                    warnings.append(f"警告: 发现不支持的文件: {relative_path}")
    
    return len(warnings) == 0, warnings

def create_zip_with_7z(folder_path: Path, output_zip: Path, compression_level: int, logger: logging.Logger) -> bool:
    """使用7z创建zip文件"""
    # 准备7z命令
    # -tzip: zip格式
    # -mx=N: 压缩级别 (0=store, 1-9=压缩)
    # -mm=Deflate: 使用Deflate方法
    # -mcu=on: 启用UTF-8编码
    compression_args = ['-mx=0'] if compression_level == 0 else ['-mx=1', '-mm=Deflate']
    
    # 使用当前工作目录来避免包含外层文件夹名
    current_dir = os.getcwd()
    try:
        os.chdir(str(folder_path))
        
        # 确保输出路径是绝对路径
        output_zip = output_zip.resolve()
        
        cmd = [
            '7z',
            'a',          # add
            '-tzip',      # zip格式
            '-mcu=on',    # UTF-8支持
            *compression_args,
            str(output_zip),
            '.' if platform.system() == 'Windows' else './*'
        ]
        
        logger.info(f'执行命令: {" ".join(cmd)}')
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                logger.info(output.strip())
        
        return_code = process.poll()
        _, stderr = process.communicate()
        
        if return_code != 0:
            logger.error(f'7z命令执行失败，返回码: {return_code}')
            if stderr:
                logger.error(f'错误信息: {stderr}')
            return False
            
        return True
        
    except Exception as e:
        logger.error(f'执行7z命令时发生错误: {str(e)}')
        return False
    finally:
        # 恢复原始工作目录
        os.chdir(current_dir)

def process_folders(root_path: str, delete_source: bool = True, compression_level: int = 0):
    """处理指定路径下的文件夹"""
    logger = setup_logging()
    
    root_path = Path(root_path).resolve()  # 转换为绝对路径
    if not root_path.exists():
        logger.error(f'指定路径不存在: {root_path}')
        return
    
    # 第一轮：验证目录结构
    logger.info("开始验证目录结构...")
    is_valid, warnings = validate_directory_structure(root_path, logger)
    
    if not is_valid:
        logger.error("发现以下问题:")
        for warning in warnings:
            logger.error(warning)
        logger.error("请处理以上问题后再次运行脚本")
        return
    
    logger.info("目录结构验证通过，开始处理文件...")
    
    # 第二轮：处理文件
    folders = [f for f in root_path.iterdir() if f.is_dir()]
    if not folders:
        logger.warning(f'在 {root_path} 中未找到文件夹')
        return
    
    success_count = 0
    for folder in folders:
        # 创建zip文件，确保它和源文件夹在同一层级
        zip_name = f"{folder.name}.zip"
        zip_path = root_path / zip_name
        
        logger.info(f'处理文件夹: {folder}')
        logger.info(f'输出zip文件: {zip_path}')
        
        if zip_path.exists():
            logger.info(f'删除已存在的zip文件: {zip_path}')
            zip_path.unlink()
        
        if create_zip_with_7z(folder, zip_path, compression_level, logger):
            success_count += 1
            if delete_source:
                try:
                    shutil.rmtree(folder)
                    logger.info(f'已删除源文件夹: {folder}')
                except Exception as e:
                    logger.error(f'删除文件夹 {folder} 时发生错误: {str(e)}')
        else:
            logger.error(f'处理文件夹 {folder} 失败')
    
    logger.info(f'完成！成功处理 {success_count}/{len(folders)} 个文件夹')

def main():
    parser = argparse.ArgumentParser(description='批量将文件夹压缩为zip文件')
    parser.add_argument('path', help='要处理的根目录路径')
    parser.add_argument('-d', '--delete', type=lambda x: str(x).lower() != 'false',
                      default=True, help='压缩后是否删除源文件夹 (默认: true)')
    parser.add_argument('-c', '--compress', type=int, choices=[0, 1],
                      default=0, help='压缩级别 (0=store, 1=deflate, 默认: 0)')
    
    args = parser.parse_args()
    process_folders(args.path, args.delete, args.compress)

if __name__ == '__main__':
    main()
