#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Password Detection Script for Archives
This script recursively scans a directory for archive files (including self-extracting archives/SFX)
and identifies which ones are password-protected.
Usage: python3 enhanced_passwddetect.py /path/to/folder [--verbose]
Works on Windows 10 and Debian 12, requires 7z to be in PATH.
"""
import os
import sys
import subprocess
import re
import struct
from datetime import datetime

# Global verbose flag
VERBOSE = False

class SFXDetector:
    """Detects if an EXE file is a self-extracting archive by analyzing file headers"""
    
    # Common archive format signatures
    SIGNATURES = {
        'RAR': [b'Rar!'],
        '7Z': [b'\x37\x7A\xBC\xAF\x27\x1C'],
        'ZIP': [b'PK\x03\x04'],
        'CAB': [b'MSCF'],
        'ARJ': [b'\x60\xEA'],
    }
    
    def __init__(self, verbose=False):
        """
        Initialize the SFX detector
        
        Args:
            verbose: Whether to output detailed information
        """
        self.verbose = verbose
    
    def is_exe(self, file_path):
        """
        Check if a file is a valid EXE file (only reads the first two bytes)
        
        Returns:
            bool: True if it's a valid EXE file, False otherwise
        """
        try:
            with open(file_path, 'rb') as f:
                return f.read(2) == b'MZ'
        except:
            return False
    
    def get_pe_structure(self, file_path):
        """
        Analyze PE file structure to find the end of the executable part
        Only reads necessary header and section table information
        
        Returns:
            Dict: Analysis results containing:
                - valid: Whether it's a valid PE file
                - file_size: Total file size
                - executable_end: End position of the executable part
                - error: Error message (if any)
        """
        result = {
            'valid': False,
            'file_size': 0,
            'executable_end': 0,
            'error': None
        }
        
        try:
            with open(file_path, 'rb') as f:
                # Get total file size
                f.seek(0, 2)
                result['file_size'] = f.tell()
                f.seek(0)
                
                # Read DOS header (only need the first 64 bytes)
                dos_header = f.read(64)
                if dos_header[:2] != b'MZ':
                    result['error'] = 'Not a valid PE file (MZ header)'
                    return result
                    
                # Get PE header offset
                pe_offset = struct.unpack('<I', dos_header[60:64])[0]
                
                # Check if PE offset is reasonable
                if pe_offset <= 0 or pe_offset >= result['file_size']:
                    result['error'] = 'Invalid PE header offset'
                    return result
                
                # Move to PE header
                f.seek(pe_offset)
                pe_signature = f.read(4)
                if pe_signature != b'PE\x00\x00':
                    result['error'] = 'Not a valid PE file (PE signature)'
                    return result
                
                # Read File Header (20 bytes)
                file_header = f.read(20)
                num_sections = struct.unpack('<H', file_header[2:4])[0]
                size_of_optional_header = struct.unpack('<H', file_header[16:18])[0]
                
                # Skip Optional Header
                f.seek(pe_offset + 24 + size_of_optional_header)
                
                # Analyze section table to find the maximum file offset
                max_end_offset = 0
                
                for _ in range(num_sections):
                    section = f.read(40)  # Each section table entry is 40 bytes
                    if len(section) < 40:
                        break
                    
                    pointer_to_raw_data = struct.unpack('<I', section[20:24])[0]
                    size_of_raw_data = struct.unpack('<I', section[16:20])[0]
                    
                    if pointer_to_raw_data > 0:
                        section_end = pointer_to_raw_data + size_of_raw_data
                        max_end_offset = max(max_end_offset, section_end)
                
                result['executable_end'] = max_end_offset
                result['valid'] = True
                return result
                
        except Exception as e:
            result['error'] = str(e)
            return result
    
    def find_signature_after_exe(self, file_path, start_offset):
        """
        Find archive signatures from the specified offset by reading the file in chunks
        
        Returns:
            Dict: Results containing:
                - found: Whether a signature was found
                - format: Archive format found
                - offset: Position of the signature in the file
        """
        result = {
            'found': False,
            'format': None,
            'offset': 0
        }
        
        # Based on NSIS and other SFX implementations, archives are usually located at 512 or 4096 byte aligned positions
        aligned_offsets = []
        
        # Calculate nearest 512-byte aligned position
        if start_offset % 512 != 0:
            aligned_offsets.append(start_offset + (512 - start_offset % 512))
        else:
            aligned_offsets.append(start_offset)
        
        # Add next few aligned positions
        for i in range(1, 10):
            aligned_offsets.append(aligned_offsets[0] + i * 512)
            
        # Also check 4096-byte aligned positions
        if start_offset % 4096 != 0:
            aligned_offsets.append(start_offset + (4096 - start_offset % 4096))
        
        # Add extra potential positions
        aligned_offsets.append(start_offset)  # Start directly from executable end
        aligned_offsets.append(0x800)  # Some SFX use fixed offsets
        aligned_offsets.append(0x1000)
        
        # Remove duplicates and sort
        aligned_offsets = sorted(set(aligned_offsets))
        
        try:
            with open(file_path, 'rb') as f:
                # Check file size to ensure offset is valid
                f.seek(0, 2)
                file_size = f.tell()
                
                # Read block size
                block_size = 4096  # Read 4KB at a time
                
                # Check each aligned position
                for offset in aligned_offsets:
                    if offset >= file_size:
                        continue
                    
                    f.seek(offset)
                    block = f.read(block_size)
                    
                    # Check if this block contains any known archive signatures
                    for fmt, signatures in self.SIGNATURES.items():
                        for sig in signatures:
                            pos = block.find(sig)
                            if pos >= 0:
                                result['found'] = True
                                result['format'] = fmt
                                result['offset'] = offset + pos
                                return result
                
                # If aligned positions didn't find anything, try sequential scanning
                # But limit scan range to avoid reading the entire file
                max_scan_size = min(10 * 1024 * 1024, file_size - start_offset)  # Scan max 10MB
                
                if max_scan_size > 0:
                    # Use larger block size for scanning
                    scan_block_size = 1024 * 1024  # 1MB blocks
                    
                    for offset in range(start_offset, start_offset + max_scan_size, scan_block_size):
                        f.seek(offset)
                        block = f.read(scan_block_size)
                        
                        for fmt, signatures in self.SIGNATURES.items():
                            for sig in signatures:
                                pos = block.find(sig)
                                if pos >= 0:
                                    result['found'] = True
                                    result['format'] = fmt
                                    result['offset'] = offset + pos
                                    return result
                
                return result
                
        except Exception as e:
            if self.verbose:
                print(f"Error finding signature: {str(e)}")
            return result
    
    def check_7z_signature_variant(self, file_path):
        """
        Specially check for 7z SFX variant signatures
        Some 7z SFX may use different signatures or offsets
        
        Returns:
            Dict: Results
        """
        result = {
            'found': False,
            'offset': 0
        }
        
        # Some known 7z SFX variant offsets and signatures
        known_offsets = [0x80000, 0x88000, 0x8A000, 0x8C000, 0x90000]
        
        try:
            with open(file_path, 'rb') as f:
                f.seek(0, 2)
                file_size = f.tell()
                
                for offset in known_offsets:
                    if offset >= file_size:
                        continue
                    
                    f.seek(offset)
                    # Check 7z signature
                    signature = f.read(6)
                    if signature == b'\x37\x7A\xBC\xAF\x27\x1C':
                        result['found'] = True
                        result['offset'] = offset
                        return result
        except:
            pass
            
        return result
    
    def check_rar_special_marker(self, file_path):
        """
        Check for RAR SFX special markers
        Some WinRAR SFX files contain special markers at specific positions
        
        Returns:
            bool: Whether it contains RAR SFX markers
        """
        try:
            with open(file_path, 'rb') as f:
                # Check file size
                f.seek(0, 2)
                file_size = f.tell()
                
                # Check several known RAR marker positions
                markers = [
                    (0x100, b'WinRAR SFX'),
                    (0x400, b'WINRAR'),
                    (0x400, b'WinRAR')
                ]
                
                for offset, marker in markers:
                    if offset + len(marker) <= file_size:
                        f.seek(offset)
                        if f.read(len(marker)) == marker:
                            return True
                            
                # Try to find "WINRAR" or "WinRAR" strings in the first 8KB
                f.seek(0)
                header = f.read(8192)
                if b'WINRAR' in header or b'WinRAR' in header:
                    return True
                    
        except:
            pass
            
        return False
        
    def is_sfx(self, file_path, detailed=False):
        """
        Determine if a file is a self-extracting (SFX) archive by analyzing file headers
        
        Args:
            file_path: File path
            detailed: Whether to return detailed analysis results
            
        Returns:
            Union[bool, Dict]: 
                If detailed=False, returns a boolean indicating whether it's an SFX file
                If detailed=True, returns a dictionary with detailed analysis results
        """
        if not os.path.exists(file_path):
            if detailed:
                return {'is_sfx': False, 'error': 'File does not exist'}
            return False
        
        if not self.is_exe(file_path):
            if detailed:
                return {'is_sfx': False, 'error': 'Not a valid EXE file'}
            return False
        
        results = {}
        
        # 1. Analyze PE structure
        pe_analysis = self.get_pe_structure(file_path)
        results['pe_analysis'] = pe_analysis
        
        # 2. Check RAR special markers
        rar_marker_found = self.check_rar_special_marker(file_path)
        results['rar_marker'] = rar_marker_found
        
        # 3. Find archive signatures from executable end position
        signature_result = {'found': False}
        if pe_analysis['valid']:
            signature_result = self.find_signature_after_exe(
                file_path, 
                pe_analysis['executable_end']
            )
        results['signature'] = signature_result
        
        # 4. Check 7z special variants
        if not signature_result['found']:
            sevenzip_variant = self.check_7z_signature_variant(file_path)
            results['7z_variant'] = sevenzip_variant
            signature_result['found'] = sevenzip_variant['found']
        
        # 5. Analyze extra data size (if PE analysis is valid)
        extra_data_size = 0
        if pe_analysis['valid']:
            extra_data_size = pe_analysis['file_size'] - pe_analysis['executable_end']
        results['extra_data_size'] = extra_data_size
        
        # Final determination
        is_sfx = (
            signature_result['found'] or 
            rar_marker_found or 
            (pe_analysis['valid'] and extra_data_size > 1024 * 10)  # 10KB threshold
        )
        results['is_sfx'] = is_sfx
        
        if detailed:
            return results
        return is_sfx

def is_archive(filename):
    """
    Check if a file is an archive based on its extension
    
    Returns:
        bool or None: True if it's an archive, None if it might be (like an exe)
    """
    filename_lower = filename.lower()
    # SFX executable files (self-extracting archives or regular executables)
    if filename_lower.endswith('.exe'):
        return None
    
    # 7z single archive
    if filename_lower.endswith('.7z'):
        return True
    
    # RAR single archive (not part of .partXX.rar structure)
    if filename_lower.endswith('.rar') and not re.search(r'\.part\d+\.rar$', filename_lower):
        return True
    
    # ZIP single archive or main volume of split ZIP
    if filename_lower.endswith('.zip'):
        return True
    return None
    
def is_main_volume(filepath):
    """
    Determine if a file is a main archive volume that needs to be checked.
    Returns True if it is a main volume, False otherwise.
    """
    filename = os.path.basename(filepath)
    filename_lower = filename.lower()
    
    # SFX executable files - we'll check if they're archives in the main function
    if filename_lower.endswith('.exe'):
        # Will need special handling in main function to check if it's an SFX
        return True
    
    # SFX RAR volumes (.part1.exe, .part01.exe, etc.)
    if re.search(r'\.part0*1\.exe$', filename_lower):
        return True
    
    # 7z single archive
    if filename_lower.endswith('.7z') and not re.search(r'\.7z\.\d+$', filename_lower):
        return True
    
    # 7z first volume of multi-volume archive
    if filename_lower.endswith('.7z.001'):
        return True
    
    # RAR single archive (not part of .partXX.rar structure)
    if filename_lower.endswith('.rar') and not re.search(r'\.part\d+\.rar$', filename_lower):
        return True
    
    # RAR first volume of multi-volume archive (.part1.rar, .part01.rar, .part001.rar, etc.)
    if re.search(r'\.part0*1\.rar$', filename_lower):
        return True
    
    # ZIP single archive or main volume of split ZIP
    if filename_lower.endswith('.zip'):
        # Check if there are .z01, .z02, etc. files with the same base name
        # For both single ZIP and split ZIP, we need to check the main volume
        return True
    
    return False

def is_secondary_volume(filepath):
    """
    Determine if a file is a secondary archive volume (not the main volume).
    Returns True if it is a secondary volume, False otherwise.
    """
    filename = os.path.basename(filepath)
    filename_lower = filename.lower()
    
    # SFX RAR secondary volumes (.part2.exe, .part02.exe, etc.)
    if re.search(r'\.part(?!0*1\.exe$)\d+\.exe$', filename_lower):
        return True
    
    # 7z secondary volumes (.7z.002, .7z.003, etc.)
    if re.search(r'\.7z\.(?!001$)\d+$', filename_lower):
        return True
    
    # RAR secondary volumes (.part2.rar, .part02.rar, .part002.rar, etc.)
    if re.search(r'\.part(?!0*1\.rar$)\d+\.rar$', filename_lower):
        return True
    
    # ZIP split files (.z01, .z02, etc. - not the main .zip)
    if re.search(r'\.z\d+$', filename_lower):
        return True
    
    return False

def check_encryption(filepath):
    """
    Check if an archive is encrypted by running 7z command with a dummy password.
    Returns True if encrypted, False if not, None if not an archive.
    """
    try:
        if VERBOSE:
            print(f"  DEBUG: Testing archive: {filepath}")
        
        # Direct approach: Try listing with a dummy password
        # This will immediately fail for encrypted archives with a clear error message
        if VERBOSE:
            print(f"  DEBUG: Checking with dummy password")
        
        # Use binary mode and handle decoding errors
        proc = subprocess.Popen(['7z', 'l', '-slt', '-pDUMMYPASSWORD', filepath], 
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=False)  # Use binary mode instead of text=True
        
        stdout_bytes, stderr_bytes = proc.communicate()
        
        # Safely decode with error handling
        try:
            stdout_output = stdout_bytes.decode('utf-8', errors='replace')
        except:
            stdout_output = ""
        
        try:
            stderr_output = stderr_bytes.decode('utf-8', errors='replace')
        except:
            stderr_output = ""
        
        output_combined = stdout_output + stderr_output
        
        if VERBOSE:
            print(f"  DEBUG: Return code: {proc.returncode}")
            print(f"  DEBUG: Output excerpt: {output_combined[:200]}")
        
        # Check for encryption indicators
        if "Cannot open encrypted archive. Wrong password?" in output_combined:
            if VERBOSE:
                print(f"  DEBUG: Wrong password error detected - file is encrypted")
            return True
        
        # Check if it's not an archive
        if "Cannot open the file as archive" in output_combined:
            if VERBOSE:
                print(f"  DEBUG: Not an archive detected")
            return None
            
        # If the dummy password didn't trigger an error, try without password
        # to check other encryption indicators
        if VERBOSE:
            print(f"  DEBUG: Checking without password")
            
        proc = subprocess.Popen(['7z', 'l', '-slt', filepath], 
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=False)  # Use binary mode
        
        stdout_bytes, stderr_bytes = proc.communicate()
        
        # Safely decode with error handling
        try:
            stdout_output = stdout_bytes.decode('utf-8', errors='replace')
        except:
            stdout_output = ""
        
        try:
            stderr_output = stderr_bytes.decode('utf-8', errors='replace')
        except:
            stderr_output = ""
        
        output_combined = stdout_output + stderr_output
        
        if VERBOSE:
            print(f"  DEBUG: Return code: {proc.returncode}")
            print(f"  DEBUG: Output excerpt: {output_combined[:200]}")
        
        # Check for other encryption indicators
        if "Encrypted = +" in output_combined:
            if VERBOSE:
                print(f"  DEBUG: Found 'Encrypted = +' in output")
            return True
            
        if "Enter password" in output_combined:
            if VERBOSE:
                print(f"  DEBUG: Found password prompt in output")
            return True
            
        if VERBOSE:
            print(f"  DEBUG: No encryption detected")
        return False
            
    except subprocess.SubprocessError as e:
        print(f"  Subprocess error: {str(e)}")
        return None
    except Exception as e:
        print(f"  Error: {str(e)}")
        return None
def main():
    global VERBOSE
    
    # Check if path argument is provided
    if len(sys.argv) < 2:
        print("Usage: python enhanced_passwddetect.py /path/to/folder [--verbose]")
        sys.exit(1)
    
    folder_path = sys.argv[1]
    
    # Check for verbose flag
    if len(sys.argv) >= 3 and sys.argv[2] == "--verbose":
        VERBOSE = True
        print("Verbose mode enabled - detailed logging will be shown")
    
    # Validate that the folder exists
    if not os.path.isdir(folder_path):
        print(f"Error: The path '{folder_path}' is not a valid directory.")
        sys.exit(1)
    
    # Initialize SFX detector
    sfx_detector = SFXDetector(verbose=VERBOSE)
    log_dir = 'log'
    if not os.path.exists(log_dir):
        os.mkdir(log_dir)
    unencrypted_archive_lst = os.path.join(log_dir, "unencrypted_archives.log")
    encrypted_archive_lst = os.path.join(log_dir, "encrypted_archives.log")
    error_archive_lst = os.path.join(log_dir, "error_archives.log")
    other_file_lst = os.path.join(log_dir, "unknown_files.log")
    
    encrypted_archives = []
    unencrypted_archives = []
    error_archives = []
    other_files = []
    
    # Walk through directory and subdirectories
    print(f"Scanning directory: {folder_path}")
    for root, _, files in os.walk(folder_path):
        for filename in files:
            filepath = os.path.join(root, filename)
            filename_lower = filename.lower()
            
            # Skip text files
            if filename_lower.endswith('.txt'):
                continue
            
            # Skip secondary volumes of split archives
            if is_secondary_volume(filepath):
                continue
            
            # Special handling for EXE files - check if they're SFX archives
            is_sfx_archive = False
            if filename_lower.endswith('.exe'):
                print(f"Checking if EXE is SFX: {filepath}")
                is_sfx_archive = sfx_detector.is_sfx(filepath)
                if not is_sfx_archive:
                    other_files.append(filepath)
                    continue
                print(f"Confirmed as SFX archive: {filepath}")
            
            # Check if this is a main archive that needs to be examined
            known_archive = is_archive(filename)
            if is_sfx_archive or is_main_volume(filepath):
                print(f"Checking for password: {filepath}")
                
                # Check if it's encrypted
                encryption_status = check_encryption(filepath)
                
                if encryption_status is None:
                    print(f"  Not an archive: {filepath}")
                    error_archives.append(filepath)
                elif encryption_status:
                    print(f"  Encrypted: {filepath}")
                    encrypted_archives.append(filepath)
                else:
                    print(f"  Not encrypted: {filepath}")
                    unencrypted_archives.append(filepath)
            elif known_archive is None:
                other_files.append(filepath)
    
    # Write results to log file
    with open(encrypted_archive_lst, 'w', encoding='utf-8') as log_file:
        for item in encrypted_archives:
            log_file.write(f"{item}\n")
    with open(unencrypted_archive_lst, 'w', encoding='utf-8') as log_file:
        for item in unencrypted_archives:
            log_file.write(f"{item}\n")
    with open(error_archive_lst, 'w', encoding='utf-8') as log_file:
        for item in error_archives:
            log_file.write(f"{item}\n")
    with open(other_file_lst, 'w', encoding='utf-8') as log_file:
        for item in other_files:
            log_file.write(f"{item}\n")
    
    print(f"Check completed. Found {len(encrypted_archives)} encrypted archives.")
    print(f"Results saved to log folder: {log_dir}")

if __name__ == "__main__":
    main()
