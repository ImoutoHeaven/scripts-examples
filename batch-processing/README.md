
# Filename Processor Script

This script processes filenames (and folder names) in a specified directory. It standardizes naming conventions, rearranges tags, and performs checks for compliance. The script provides warnings for non-compliant names and offers a `--dry-run` option to preview changes.

## Features
- **Bracket Replacement**: Converts special brackets (e.g., `【】`, `（）`) into standard ones (`[]`, `()`).
- **Keyword Handling**: Replaces keywords inside `()` with `[]` for better readability.
- **Version Tag Normalization**: Converts `v2`, `v3`, etc., into `[v2]`, `[v3]` unless they are already inside square brackets.
- **Whitespace Handling**: Replaces underscores with spaces and normalizes whitespace.
- **Tag Rearrangement**: Sorts and places specific tags in the correct order at the end of filenames.
- **Compliance Check**: Ensures filenames start correctly with `[]` or `()` and follow other specific conventions.

## Usage
```bash
python script.py /path/to/folder [--dry-run]
```
- `/path/to/folder`: The path to the directory to process.
- `--dry-run`: Optional. Use this flag to preview changes without applying them.

## Example Input and Output

### Example 1: Standard Case
**Input Filename:**
```
【Pixiv】_v2_测试文件_(汉化).zip
```
**Output Filename:**
```
测试文件 [Pixiv] [v2] [汉化].zip
```

### Example 2: Folder Renaming
**Input Folder:**
```
【Patreon】_项目_v3_(中文)
```
**Output Folder:**
```
项目 [Patreon] [v3] [中文]
```

## Warnings and Errors

### Warnings
If a filename does not conform to the naming conventions, it will be listed under warnings:
```
WARNING: The following files do not conform to the naming convention and require manual renaming:
Test_file
```

### Errors
The script checks for unmatched brackets. If detected, it will stop execution with an error message:
```
Error: Unmatched opening '(' in 'Test(漢化.zip'. Please handle the issue manually. No changes have been made.
```

## Dry Run Mode
Using `--dry-run` allows you to preview the changes without applying them:
```bash
python script.py /path/to/folder --dry-run
```
Example Output:
```
Rename: /path/to/folder/【Pixiv】_测试文件_(汉化).zip -> /path/to/folder/测试文件 [Pixiv] [汉化].zip
```

## Requirements
- Python 3.8 or above

## Error Handling
- **Unmatched Brackets**: The script will stop and raise a `ValueError` if there are unmatched brackets.
- **OS Errors**: If the script cannot rename a file due to system restrictions, it will display an error message.

## License
This script is licensed under the MIT License.

## Author
This script was generated based on user-provided logic.

---

**Note:** Use this script with caution, especially if running without `--dry-run`. Ensure you have backups of your files.
