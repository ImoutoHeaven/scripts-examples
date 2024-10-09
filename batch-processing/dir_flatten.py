import argparse
import os
import shutil

def main():
    parser = argparse.ArgumentParser(description='Flatten directory structure.')
    parser.add_argument('path_to_0depth_folder', help='Path to 0-level folder')
    parser.add_argument('--rolling', type=int, default=20, help='Number of times to repeat the process')
    args = parser.parse_args()

    # Convert path to absolute path
    path_to_0depth_folder = os.path.abspath(args.path_to_0depth_folder)
    rolling_count = args.rolling

    # Check if path_to_0depth_folder exists and is a directory
    if not os.path.isdir(path_to_0depth_folder):
        print(f"Error: {path_to_0depth_folder} is not a valid directory.")
        return

    for _ in range(rolling_count):
        # Process 1-level folders
        process_1level_folders(path_to_0depth_folder)

def process_1level_folders(path_to_0depth_folder):
    # List items in 0-level folder
    for item in os.listdir(path_to_0depth_folder):
        item_path = os.path.join(path_to_0depth_folder, item)
        if os.path.isdir(item_path):
            # This is a 1-level folder
            process_1level_folder(item_path)

def process_1level_folder(path_to_1level_folder):
    # Get list of items in 1-level folder
    items = os.listdir(path_to_1level_folder)
    files = []
    folders = []

    for item in items:
        item_path = os.path.join(path_to_1level_folder, item)
        if os.path.isdir(item_path):
            folders.append(item)
        else:
            files.append(item)

    # Apply the logic
    if len(files) > 0 and len(folders) == 0:
        # Case 1: only files
        pass  # Do nothing
    elif len(files) > 0 and len(folders) > 0:
        # Case 2: files and folders
        pass  # Do nothing
    elif len(files) == 0 and len(folders) >= 2:
        # Case 3: only folders, >=2 folders
        pass  # Do nothing
    elif len(files) == 0 and len(folders) == 1:
        # Case 4: only one folder
        two_level_folder_name = folders[0]
        two_level_folder_path = os.path.join(path_to_1level_folder, two_level_folder_name)
        move_contents_and_remove(two_level_folder_path, path_to_1level_folder)

def move_contents_and_remove(src_folder, dest_folder):
    # Move all contents from src_folder to dest_folder
    for item in os.listdir(src_folder):
        src_item = os.path.join(src_folder, item)
        dest_item = os.path.join(dest_folder, item)
        # Check if dest_item exists
        if os.path.exists(dest_item):
            # Name conflict, handle accordingly
            print(f"Conflict: {dest_item} already exists. Skipping {src_item}.")
            continue
        try:
            shutil.move(src_item, dest_item)
        except Exception as e:
            print(f"Error moving {src_item} to {dest_item}: {e}")

    # After moving all contents, remove src_folder
    try:
        os.rmdir(src_folder)
    except Exception as e:
        print(f"Error removing directory {src_folder}: {e}")

if __name__ == '__main__':
    main()
