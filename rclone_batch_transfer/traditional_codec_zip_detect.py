import os
import sys
import argparse
import subprocess
import re

def parse_arguments():
    parser = argparse.ArgumentParser(description='Test archives for password protection.')
    parser.add_argument('folder', help='Path to the folder to scan.')
    parser.add_argument('--out', default='log.txt', help='Output file for the list of archives with details.')
    return parser.parse_args()

def get_extension_and_base_name(filename):
    filename_lower = filename.lower()
    base_name = filename
    extension = ''

    # Patterns to match
    # .part001.rar, .part0001.rar, .part00001.rar
    part_pattern = re.compile(r'(.*)\.part\d+\.rar$')
    if part_pattern.match(filename_lower):
        base_name = part_pattern.match(filename_lower).group(1)
        extension = '.partN.rar'
        return base_name, extension

    part_pattern_zip = re.compile(r'(.*)\.part\d+\.zip$')
    if part_pattern_zip.match(filename_lower):
        base_name = part_pattern_zip.match(filename_lower).group(1)
        extension = '.partN.zip'
        return base_name, extension

    # .rar, .zip, .7z
    for ext in ['.rar', '.zip', '.7z']:
        if filename_lower.endswith(ext):
            base_name = filename_lower[:-len(ext)]
            extension = ext
            return base_name, extension

    # .r00, .z01
    r_pattern = re.compile(r'(.*)\.r\d{2,3}$')
    if r_pattern.match(filename_lower):
        base_name = r_pattern.match(filename_lower).group(1)
        extension = '.rNN'
        return base_name, extension

    z_pattern = re.compile(r'(.*)\.z\d{2,3}$')
    if z_pattern.match(filename_lower):
        base_name = z_pattern.match(filename_lower).group(1)
        extension = '.zNN'
        return base_name, extension

    # .7z.001
    seven_z_split_pattern = re.compile(r'(.*)\.7z\.\d{3}$')
    if seven_z_split_pattern.match(filename_lower):
        base_name = seven_z_split_pattern.match(filename_lower).group(1)
        extension = '.7z.NNN'
        return base_name, extension

    # .001 (could be split files)
    if filename_lower.endswith('.001'):
        base_name = filename_lower[:-4]
        extension = '.001'
        return base_name, extension

    # .exe
    if filename_lower.endswith('.exe'):
        base_name = filename_lower[:-4]
        extension = '.exe'
        return base_name, extension

    return None, None  # Not an archive we are interested in

def collect_archives(folder):
    EXTENSION_PREFERENCE = {
        '.exe': 0,
        '.rar': 1,
        '.zip': 1,
        '.7z': 1,
        '.partN.rar': 2,
        '.rNN': 2,
        '.partN.zip': 2,
        '.zNN': 2,
        '.7z.NNN': 2,
        '.001': 2,
    }

    base_name_to_file = {}
    for root, _, files in os.walk(folder):
        for filename in files:
            full_path = os.path.join(root, filename)
            base_name, extension = get_extension_and_base_name(filename)
            if base_name is not None:
                current_pref = EXTENSION_PREFERENCE.get(extension, len(EXTENSION_PREFERENCE))
                key = os.path.join(root, base_name)
                if key not in base_name_to_file:
                    base_name_to_file[key] = (full_path, current_pref)
                else:
                    _, stored_pref = base_name_to_file[key]
                    if current_pref < stored_pref:
                        base_name_to_file[key] = (full_path, current_pref)
    # Return the list of files to test
    return [file_info[0] for file_info in base_name_to_file.values()]

def is_password_protected(archive_path):
    try:
        # Run '7z l -slt -sccUTF-8' command to force UTF-8 encoding
        cmd = ['7z', 'l', '-slt', archive_path, '-sccUTF-8']
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        output = result.stdout

        is_encrypted = False
        headers_encrypted = False
        for line in output.splitlines():
            if 'Encrypted = +' in line:
                is_encrypted = True
            if 'Headers Encrypted = +' in line:
                headers_encrypted = True

        return is_encrypted, headers_encrypted

    except Exception as e:
        # Handle cases where 7z cannot open the archive
        print(f"Error processing file '{archive_path}': {e}")
        return False, False

def is_traditional_zip(archive_path):
    # Check if zip file uses traditional encoding (non-UTF-8)
    try:
        if not archive_path.lower().endswith('.zip'):
            return False  # Only interested in zip files
        with open(archive_path, 'rb') as f:
            # Read the local file headers
            while True:
                header = f.read(30)
                if len(header) < 30:
                    break
                # Check for PK signature
                if header[0:4] != b'PK\x03\x04':
                    break
                # General purpose bit flag is at bytes 6-7
                gpbf = int.from_bytes(header[6:8], 'little')
                # Bit 11 indicates UTF-8 encoding
                is_utf8 = (gpbf & (1 << 11)) != 0
                if is_utf8:
                    return False  # It's UTF-8 encoded
                # Skip the filename and extra field
                filename_length = int.from_bytes(header[26:28], 'little')
                extra_field_length = int.from_bytes(header[28:30], 'little')
                f.seek(filename_length + extra_field_length, os.SEEK_CUR)
            return True  # Did not find UTF-8 flag, assume traditional zip
    except Exception as e:
        print(f"Error reading zip file '{archive_path}': {e}")
        return False

def main():
    args = parse_arguments()
    folder = args.folder
    output_file = args.out
    if not os.path.isdir(folder):
        print(f"Error: The folder '{folder}' does not exist or is not a directory.")
        sys.exit(1)

    print("Collecting archives...")
    archives_to_test = collect_archives(folder)
    results = []

    print("Testing archives for password protection...")
    for archive in archives_to_test:
        is_encrypted, headers_encrypted = is_password_protected(archive)
        is_traditional_zip_format = is_traditional_zip(archive)
        if not (is_encrypted or headers_encrypted or is_traditional_zip_format):
            continue  # Skip files where all three are False
        relative_path = os.path.relpath(archive, folder)
        filename = os.path.basename(archive)
        results.append((filename, relative_path, is_encrypted, headers_encrypted, is_traditional_zip_format))
        print(f"Processed: {archive}")

    # Write the list to the output file
    with open(output_file, 'w', encoding='utf-8') as f:
        # Write header row
        f.write("FILE_NAME\tFILE_PATH_RELATIVELY\tIS_PASSWD_REQUIRED\tIS_METADATA_ENCRYPTED\tIS_TRADITIONAL_ZIP_FORMAT\n")
        for filename, relative_path, is_encrypted, headers_encrypted, is_traditional_zip_format in results:
            # Output format with tab separation
            f.write(f"{filename}\t{relative_path}\t{is_encrypted}\t{headers_encrypted}\t{is_traditional_zip_format}\n")

    print(f"Completed. Results are listed in '{output_file}'.")

if __name__ == "__main__":
    main()
