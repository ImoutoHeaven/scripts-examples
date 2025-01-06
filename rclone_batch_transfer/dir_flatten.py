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
        else:  # DELETE
            return f"DELETE: {self.source}"

class DirectoryFlattener:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.operations: List[Operation] = []
        # 用于追踪已经存在的路径，避免名称冲突
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

    def is_empty_dir(self, path: Path) -> bool:
        """检查目录是否为空"""
        try:
            return not any(path.iterdir())
        except Exception:
            return False

    def handle_name_conflict(self, current_dir: Path, subdir: Path) -> Path:
        """处理内层文件夹与外层文件夹同名的情况"""
        if current_dir.name == subdir.name:
            new_subdir = self.generate_unique_name(subdir)
            self.operations.append(Operation(
                OperationType.RENAME,
                subdir,
                new_subdir,
                f"Rename directory due to name conflict with parent"
            ))
            if not self.dry_run:
                try:
                    subdir.rename(new_subdir)
                    print(f"Renamed directory '{subdir}' to '{new_subdir}'")
                    return new_subdir
                except Exception as e:
                    print(f"Error renaming directory {subdir}: {e}")
                    return subdir
            return new_subdir
        return subdir

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

    def cleanup_empty_dirs(self, path: Path):
        """递归删除空目录"""
        try:
            for item in path.iterdir():
                if item.is_dir():
                    self.cleanup_empty_dirs(item)
            
            if self.is_empty_dir(path):
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
        """递归扁平化目录结构"""
        try:
            # 初始化当前目录下所有已存在的路径
            self.existing_paths.update(path.iterdir())
            
            # 获取当前目录下所有内容
            items = list(path.iterdir())
            dirs = [item for item in items if item.is_dir()]
            files = [item for item in items if item.is_file()]
            
            # 如果只有一个子目录且没有文件，且不是根目录
            if len(dirs) == 1 and len(files) == 0 and not is_root:
                subdir = dirs[0]
                # 处理可能的文件夹同名情况
                subdir = self.handle_name_conflict(path, subdir)
                # 移动子目录中的所有内容到当前目录
                if self.move_contents(subdir, path):
                    if self.is_empty_dir(subdir):
                        self.operations.append(Operation(
                            OperationType.DELETE,
                            subdir,
                            description="Remove empty directory after content move"
                        ))
                        if not self.dry_run:
                            try:
                                subdir.rmdir()
                                print(f"Removed empty directory '{subdir}'")
                            except Exception as e:
                                print(f"Error removing directory {subdir}: {e}")
            
            # 递归处理所有子目录
            for dir_path in path.iterdir():
                if dir_path.is_dir():
                    self.flatten_directory(dir_path, is_root=False)
            
            # 清理空目录
            self.cleanup_empty_dirs(path)
                    
        except Exception as e:
            print(f"Error processing directory {path}: {e}")

    def print_operations_summary(self):
        """打印操作摘要"""
        if not self.operations:
            print("No operations needed - directory structure is already flat.")
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
        
        print("\nNote: This is a dry run - no actual changes were made.")

def main():
    parser = argparse.ArgumentParser(description='Intelligently flatten directory structure.')
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
    
    if args.dry_run:
        flattener.print_operations_summary()
    else:
        print("Directory flattening completed.")

if __name__ == '__main__':
    main()
