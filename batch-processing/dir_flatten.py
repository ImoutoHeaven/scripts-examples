import os
import sys
import shutil
import argparse

def optimize_directory(path, dry_run=False, max_depth=20):
    # 将路径转换为绝对路径
    abs_path = os.path.abspath(path)
    for root, dirs, files in os.walk(abs_path, topdown=False):
        rel_depth = os.path.relpath(root, abs_path).count(os.sep)
        if rel_depth > 0 and rel_depth <= max_depth:
            parent_dir = os.path.dirname(root)
            if not files and not dirs:  # 如果是空目录
                if not dry_run:
                    os.rmdir(root)
                print(f"{'[DRY RUN] ' if dry_run else ''}Removed empty directory: {root}")
            elif rel_depth > 0:  # 如果不是起始目录
                for item in files + dirs:
                    src = os.path.join(root, item)
                    dst = os.path.join(parent_dir, item)
                    if not os.path.exists(dst):
                        if not dry_run:
                            shutil.move(src, dst)
                        print(f"{'[DRY RUN] ' if dry_run else ''}Moved: {src} -> {dst}")
                    else:
                        print(f"{'[DRY RUN] ' if dry_run else ''}Skipped (already exists): {src}")
                if not dry_run and not os.listdir(root):
                    os.rmdir(root)
                    print(f"Removed directory after moving contents: {root}")

def main():
    parser = argparse.ArgumentParser(description="Optimize directory structure by removing redundant nested folders.")
    parser.add_argument("path", help="Path to the directory to optimize (absolute or relative)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without making them")
    args = parser.parse_args()

    # 将输入路径转换为绝对路径
    abs_path = os.path.abspath(args.path)

    if not os.path.isdir(abs_path):
        print(f"Error: {abs_path} is not a valid directory")
        sys.exit(1)

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Optimizing directory structure for: {abs_path}")
    optimize_directory(abs_path, args.dry_run)
    print("Optimization complete.")

if __name__ == "__main__":
    main()
