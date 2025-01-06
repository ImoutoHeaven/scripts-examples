import argparse
import os
import shutil
from pathlib import Path
import uuid
from typing import List, Dict, Set
from dataclasses import dataclass
from enum import Enum, auto

class OperationType(Enum):
    RENAME = auto()
    MOVE = auto()
    DELETE = auto()
    MOVE_CONTENT = auto()  # 新增：整体移动内容目录

@dataclass
class Operation:
    op_type: OperationType
    source: Path
    destination: Path = None
    description: str = ""

    def __str__(self) -> str:
        if self.op_type == OperationType.RENAME:
            return f"RENAME: {self.source} -> {self.destination}"
        elif self.op_type == OperationType.MOVE:
            return f"MOVE: {self.source} -> {self.destination}"
        elif self.op_type == OperationType.MOVE_CONTENT:
            return f"MOVE_CONTENT: {self.source} -> {self.destination} (Content directory preserved)"
        else:  # DELETE
            return f"DELETE: {self.source}"

class DirectoryFlattener:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.operations: List[Operation] = []
        self.existing_paths: Set[Path] = set()

    def generate_unique_name(self, original_path: Path) -> Path:
        """为发生冲突的文件/文件夹生成唯一名称"""
        while True:
            stem = original_path.stem
            suffix = original_path.suffix
            unique_stem = f"{stem}_{str(uuid.uuid4())[:8]}"
            new_path = original_path.with_name(unique_stem + suffix)
            if new_path not in self.existing_paths:
                return new_path

    def is_content_directory(self, path: Path) -> bool:
        """判断是否为内容目录(包含2个或以上文件/文件夹)"""
        try:
            items = list(path.iterdir())
            return len(items) >= 2
        except Exception as e:
            print(f"Error checking directory {path}: {e}")
            return False

    def handle_name_conflict(self, current_dir: Path, target_dir: Path) -> Path:
        """处理目录重名情况"""
        if current_dir.name == target_dir.name or target_dir in self.existing_paths:
            new_dir = self.generate_unique_name(target_dir)
            self.operations.append(Operation(
                OperationType.RENAME,
                target_dir,
                new_dir,
                f"Rename directory due to name conflict"
            ))
            if not self.dry_run:
                try:
                    if target_dir.exists():  # 确保目标存在再重命名
                        target_dir.rename(new_dir)
                        print(f"Renamed directory '{target_dir}' to '{new_dir}'")
                    return new_dir
                except Exception as e:
                    print(f"Error renaming directory {target_dir}: {e}")
                    return target_dir
            return new_dir
        return target_dir

    def move_content_directory(self, src: Path, dest_parent: Path) -> bool:
        """整体移动内容目录到目标位置"""
        try:
            dest = dest_parent / src.name
            dest = self.handle_name_conflict(dest_parent, dest)
            
            self.operations.append(Operation(
                OperationType.MOVE_CONTENT,
                src,
                dest,
                f"Move content directory from {src.parent.name} to {dest_parent.name}"
            ))
            
            if not self.dry_run:
                shutil.move(str(src), str(dest))
                print(f"Moved content directory '{src}' to '{dest}'")
                self.existing_paths.add(dest)
            return True
        except Exception as e:
            print(f"Error moving content directory {src}: {e}")
            return False

    def simulate_move_contents(self, src: Path, dest: Path) -> Dict[Path, Path]:
        """模拟移动操作并返回源目标路径映射"""
        path_mapping = {}
        try:
            for item in src.iterdir():
                dest_path = dest / item.name
                if dest_path in self.existing_paths:
                    dest_path = self.generate_unique_name(dest_path)
                path_mapping[item] = dest_path
                self.existing_paths.add(dest_path)
        except Exception as e:
            print(f"Error simulating move from {src}: {e}")
        return path_mapping

    def move_contents(self, src: Path, dest: Path) -> bool:
        """移动文件/文件夹的内容到目标位置"""
        path_mapping = self.simulate_move_contents(src, dest)
        
        for source, destination in path_mapping.items():
            self.operations.append(Operation(
                OperationType.MOVE,
                source,
                destination,
                f"Move from {source.parent.name} to {destination.parent.name}"
            ))
            
        if self.dry_run:
            return True
            
        all_success = True
        for source, destination in path_mapping.items():
            try:
                shutil.move(str(source), str(destination))
                print(f"Moved '{source}' to '{destination}'")
            except Exception as e:
                print(f"Error moving {source} to {destination}: {e}")
                all_success = False
                
        return all_success

    def cleanup_empty_dirs(self, path: Path, is_content: bool = False):
        """递归删除空目录，但跳过内容目录中的空目录"""
        if is_content:
            return

        try:
            for item in path.iterdir():
                if item.is_dir() and not self.is_content_directory(item):
                    self.cleanup_empty_dirs(item)
            
            # 只有非内容目录的空目录才会被删除
            if not self.is_content_directory(path) and not any(path.iterdir()):
                self.operations.append(Operation(
                    OperationType.DELETE,
                    path,
                    description="Remove empty directory"
                ))
                if not self.dry_run:
                    try:
                        path.rmdir()
                        print(f"Removed empty directory '{path}'")
                    except Exception as e:
                        print(f"Error removing directory {path}: {e}")
        except Exception as e:
            print(f"Error cleaning up directory {path}: {e}")

    def flatten_directory(self, path: Path, is_root: bool = True):
        """递归扁平化目录结构，但保护内容目录"""
        try:
            # 初始化当前目录下所有已存在的路径
            self.existing_paths.update(path.iterdir())
            
            # 检查当前目录是否为内容目录
            is_content = self.is_content_directory(path)
            if is_content and not is_root:
                # 如果是内容目录（且不是根目录），将整个目录移动到父目录
                self.move_content_directory(path, path.parent.parent)
                return
            
            # 获取当前目录下所有内容
            items = list(path.iterdir())
            dirs = [item for item in items if item.is_dir()]
            
            # 递归处理所有子目录
            for dir_path in dirs:
                if dir_path.is_dir():
                    self.flatten_directory(dir_path, is_root=False)
            
            # 清理空目录，但跳过内容目录
            self.cleanup_empty_dirs(path, is_content)
                    
        except Exception as e:
            print(f"Error processing directory {path}: {e}")

    def print_operations_summary(self):
        """打印操作摘要"""
        if not self.operations:
            print("No operations needed.")
            return

        print("\nOperation Summary:")
        print("=" * 80)
        
        # 按操作类型分组统计
        op_counts = {op_type: 0 for op_type in OperationType}
        for op in self.operations:
            op_counts[op.op_type] += 1
        
        print("\nOperation Counts:")
        print("-" * 40)
        for op_type, count in op_counts.items():
            if count > 0:
                print(f"{op_type.name}: {count}")
        
        print("\nDetailed Operations:")
        print("-" * 80)
        for i, op in enumerate(self.operations, 1):
            print(f"{i}. {op}")
        
        if self.dry_run:
            print("\nNote: This is a dry run - no actual changes were made.")

def main():
    parser = argparse.ArgumentParser(description='Intelligently flatten directory structure while preserving content directories.')
    parser.add_argument('path', help='Path to the root folder')
    parser.add_argument('--dry-run', action='store_true', 
                      help='Show what would be done without actually doing it')
    
    args = parser.parse_args()
    root_path = Path(args.path).resolve()
    
    if not root_path.is_dir():
        print(f"Error: {root_path} is not a valid directory.")
        return
    
    print(f"Processing directory: {root_path}")
    
    flattener = DirectoryFlattener(dry_run=args.dry_run)
    flattener.flatten_directory(root_path)
    
    if args.dry_run or flattener.operations:
        flattener.print_operations_summary()
    else:
        print("Directory flattening completed - no changes needed.")

if __name__ == '__main__':
    main()
