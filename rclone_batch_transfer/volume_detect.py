#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import argparse
import locale
from pathlib import Path
from tqdm import tqdm
from collections import defaultdict
from datetime import datetime

class ArchiveScanner:
    def __init__(self, search_path, min_count=100, output_path=None):
        self.search_path = Path(search_path).resolve()
        self.min_count = min_count
        self.output_path = Path(output_path) if output_path else None
        self.results = defaultdict(list)
        self.total_archives = 0
        self.total_files = 0
        
        # Set default encoding for subprocess
        self.system_encoding = locale.getpreferredencoding()
        
        try:
            subprocess.run(['7z', '--help'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("7z command not found. Please install p7zip-full on Linux or 7-Zip on Windows.")

    def run_7z_command(self, args, file_path):
        """Execute 7z command with proper encoding handling"""
        try:
            # Use universal_newlines=True instead of text=True for better encoding handling
            process = subprocess.run(
                ['7z'] + args + [str(file_path)],
                capture_output=True,
                universal_newlines=True,
                encoding=self.system_encoding,
                errors='replace'
            )
            return process
        except subprocess.SubprocessError as e:
            print(f"Warning: Failed to process {file_path}: {str(e)}", file=sys.stderr)
            return None

    def is_archive_file(self, file_path):
        result = self.run_7z_command(['l'], file_path)
        return result is not None and result.returncode == 0

    def is_encrypted(self, file_path):
        result = self.run_7z_command(['l'], file_path)
        if result is None:
            return True
        return 'Enter password' in result.stdout or 'encrypted' in result.stdout.lower()

    def count_files(self, file_path):
        result = self.run_7z_command(['l'], file_path)
        if result is None or result.returncode != 0:
            return 0
            
        try:
            lines = result.stdout.split('\n')
            count = 0
            
            start_index = -1
            for i, line in enumerate(lines):
                if '------------------- ----- ------------ ------------  ------------------------' in line:
                    start_index = i + 1
                    break
                    
            if start_index == -1:
                return 0
                
            for line in lines[start_index:]:
                if line.strip() and not line.strip().endswith('/') and not line.strip().endswith('\\'):
                    if any(x in line for x in ['------------------- ----- ------------ ------------  ------------------------',
                                             'Size:', 'Archives:', 'Files:', 'Folders:']):
                        continue
                    count += 1
                    
            return count
            
        except Exception as e:
            print(f"Warning: Error counting files in {file_path}: {str(e)}", file=sys.stderr)
            return 0

    def get_all_archives(self):
        archive_files = []
        for root, _, files in os.walk(self.search_path):
            for file in files:
                try:
                    file_path = Path(root) / file
                    archive_files.append(file_path)
                except Exception as e:
                    print(f"Warning: Error processing path {root}/{file}: {str(e)}", file=sys.stderr)
        return archive_files

    def scan_directory(self):
        archive_files = self.get_all_archives()
        
        with tqdm(total=len(archive_files), desc="Scanning archives", unit="file") as pbar:
            for file_path in archive_files:
                try:
                    if not self.is_archive_file(file_path):
                        pbar.update(1)
                        continue
                        
                    if self.is_encrypted(file_path):
                        pbar.update(1)
                        continue
                    
                    file_count = self.count_files(file_path)
                    
                    if self.min_count == 0 or file_count >= self.min_count:
                        rel_path = str(file_path.relative_to(self.search_path))
                        parent_dir = str(file_path.parent.relative_to(self.search_path))
                        if parent_dir == '.':
                            parent_dir = ''
                        self.results[parent_dir].append((rel_path, file_count))
                        self.total_archives += 1
                        self.total_files += file_count
                except Exception as e:
                    print(f"Warning: Error processing {file_path}: {str(e)}", file=sys.stderr)
                finally:
                    pbar.update(1)

    def truncate_path(self, path, max_length=90):
        """Truncate path if it's too long while preserving the filename"""
        if len(path) <= max_length:
            return path
        
        parts = Path(path).parts
        filename = parts[-1]
        dirname = str(Path(*parts[:-1]))
        
        if len(filename) + 3 >= max_length:
            return "..." + filename[-(max_length-3):]
        
        available_space = max_length - len(filename) - 5  # 5 for ".../" and potential separator
        return "..." + dirname[-available_space:] + "/" + filename

    def get_terminal_width(self):
        """Get terminal width or default to 80 if cannot be determined"""
        try:
            import shutil
            terminal_width = shutil.get_terminal_size().columns
            # Ensure minimum width of 80 characters
            return max(80, terminal_width)
        except:
            return 80

    def calculate_column_widths(self, directory_files):
        """Calculate optimal column widths based on content"""
        # Get terminal width and calculate minimum widths
        total_width = self.get_terminal_width()
        min_count_width = 15  # Minimum width for file count column
        
        # Calculate max length of file paths in current directory
        max_path_length = max(
            (len(str(path)) for path, _ in directory_files),
            default=20  # Default minimum if no files
        )
        path_width = max(20, min(max_path_length, total_width - min_count_width - 5))  # 5 for borders and padding
        
        return path_width, min_count_width

    def create_table_header(self, path_width, count_width):
        # Create the header with dynamic widths
        border_line = "+" + "-" * (path_width + 2) + "+" + "-" * (count_width + 2) + "+"
        header_line = "|{:^{}}|{:^{}}|".format(
            "Archive Path", path_width + 2,
            "File Count", count_width + 2
        )
        return f"{border_line}\n{header_line}\n{border_line}"

    def create_summary_header(self):
        width = self.get_terminal_width()
        return (
            "\nScan Summary\n" +
            "=" * width + "\n" +
            f"Scan Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n" +
            f"Base Directory: {self.search_path}\n" +
            f"Minimum File Count: {self.min_count}\n" +
            f"Total Archives Found: {self.total_archives}\n" +
            f"Total Files in Archives: {self.total_files:,}\n" +
            "=" * width + "\n"
        )

    def create_table_footer(self, path_width, count_width):
        return "+" + "-" * (path_width + 2) + "+" + "-" * (count_width + 2) + "+"

    def format_directory_header(self, directory):
        if not directory:
            directory = "Root Directory"
        width = self.get_terminal_width()
        return (
            "\n" +
            "=" * width + "\n" +
            f"Directory: {directory}\n" +
            "=" * width
        )

    def output_results(self):
        sorted_dirs = sorted(self.results.keys())
        output_lines = [self.create_summary_header()]
        
        for directory in sorted_dirs:
            sorted_files = sorted(self.results[directory], 
                                key=lambda x: (-x[1], x[0]))
            
            if sorted_files:
                # Calculate optimal widths for this directory's files
                path_width, count_width = self.calculate_column_widths(sorted_files)
                
                output_lines.append(self.format_directory_header(directory))
                output_lines.append(self.create_table_header(path_width, count_width))
                
                for file_path, count in sorted_files:
                    if len(str(file_path)) > path_width:
                        # If path is too long, preserve the filename and truncate the middle
                        path_parts = Path(file_path).parts
                        if len(path_parts) > 1:
                            # Keep the last part (filename) and as much of the path as possible
                            filename = path_parts[-1]
                            remaining_width = path_width - len(filename) - 5  # 5 for ".../" and spacing
                            if remaining_width > 0:
                                path_start = str(Path(*path_parts[:-1]))
                                if len(path_start) > remaining_width:
                                    path_start = "..." + path_start[-(remaining_width-3):]
                                displayed_path = f"{path_start}/{filename}"
                            else:
                                displayed_path = "..." + filename[-(path_width-3):]
                        else:
                            # Single component path (filename only)
                            displayed_path = "..." + str(file_path)[-(path_width-3):]
                    else:
                        displayed_path = str(file_path)
                    
                    output_lines.append("|{:<{}}|{:>{},}|".format(
                        displayed_path, path_width + 2,
                        count, count_width + 1
                    ))
                
                output_lines.append(self.create_table_footer(path_width, count_width))
        
        output_text = '\n'.join(output_lines)
        
        if self.output_path:
            # Write with UTF-8 encoding
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, 'w', encoding='utf-8') as f:
                f.write(output_text)
        else:
            # Print with proper encoding
            try:
                print(output_text)
            except UnicodeEncodeError:
                # Fallback to safe encoding if terminal doesn't support UTF-8
                print(output_text.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding))

def main():
    # Set UTF-8 as default encoding for stdout
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description='Scan directory for archives and count files')
    parser.add_argument('path', help='Directory path to scan')
    parser.add_argument('--out', help='Output file path for results')
    parser.add_argument('--count', type=int, default=100, 
                      help='Minimum file count threshold (default: 100, 0 for all files)')
    
    args = parser.parse_args()
    
    try:
        scanner = ArchiveScanner(args.path, args.count, args.out)
        scanner.scan_directory()
        scanner.output_results()
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
