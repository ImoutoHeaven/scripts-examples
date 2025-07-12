#!/usr/bin/env python3
"""
Advanced Decompressor Script
Supports Windows 10/Debian 12 platforms
Recursively scans and extracts various archive formats including SFX files
"""

import os
import sys
import re
import struct
import subprocess
import argparse
import shutil
import time
import threading
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Union, Tuple

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


def is_password_correct(archive_path, password):
    """Test if a password is correct for an archive."""
    cmd = ['7z', 't', str(archive_path), f'-p{password}', '-y']
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    if result.returncode == 0:
        return True
    else:
        return False


def try_extract(archive_path, password, tmp_dir):
    """Extract archive to temporary directory."""
    cmd = ['7z', 'x', archive_path, f'-o{tmp_dir}', f'-p{password}', '-y']
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode == 0


def get_archive_base_name(filepath):
    """Get base name for archive (corrected version following spec)."""
    filename = os.path.basename(filepath)
    filename_lower = filename.lower()
    
    # Handle different archive types correctly
    if filename_lower.endswith('.exe'):
        # For SFX files, remove .exe and part indicators
        base = re.sub(r'\.exe$', '', filename, flags=re.IGNORECASE)
        base = re.sub(r'\.part\d+$', '', base, flags=re.IGNORECASE)
        return base
    
    elif filename_lower.endswith('.rar'):
        if re.search(r'\.part\d+\.rar$', filename_lower):
            # Multi-part RAR: remove .partN.rar
            return re.sub(r'\.part\d+\.rar$', '', filename, flags=re.IGNORECASE)
        else:
            # Single RAR: remove .rar
            return re.sub(r'\.rar$', '', filename, flags=re.IGNORECASE)
    
    elif filename_lower.endswith('.7z'):
        # Single 7z: remove .7z
        return re.sub(r'\.7z$', '', filename, flags=re.IGNORECASE)
    
    elif re.search(r'\.7z\.\d+$', filename_lower):
        # Multi-part 7z: remove .7z.NNN
        return re.sub(r'\.7z\.\d+$', '', filename, flags=re.IGNORECASE)
    
    elif filename_lower.endswith('.zip'):
        # ZIP: remove .zip
        return re.sub(r'\.zip$', '', filename, flags=re.IGNORECASE)
    
    elif re.search(r'\.z\d+$', filename_lower):
        # ZIP volumes: remove .zNN
        return re.sub(r'\.z\d+$', '', filename, flags=re.IGNORECASE)
    
    # Fallback
    return os.path.splitext(filename)[0]


def find_archive_volumes(main_archive_path):
    """Find all volumes related to a main archive."""
    volumes = [main_archive_path]
    base_dir = os.path.dirname(main_archive_path)
    main_filename = os.path.basename(main_archive_path)
    main_filename_lower = main_filename.lower()
    
    # For different archive types, find related volumes
    if main_filename_lower.endswith('.rar') and not re.search(r'\.part\d+\.rar$', main_filename_lower):
        # Single RAR, look for .r00, .r01, etc.
        base_name = os.path.splitext(main_filename)[0]
        for i in range(100):  # Check up to .r99
            volume_name = f"{base_name}.r{i:02d}"
            volume_path = os.path.join(base_dir, volume_name)
            if os.path.exists(volume_path):
                volumes.append(volume_path)
    
    elif re.search(r'\.part0*1\.rar$', main_filename_lower):
        # Multi-part RAR, find all parts
        base_name = re.sub(r'\.part0*1\.rar$', '', main_filename, flags=re.IGNORECASE)
        for filename in os.listdir(base_dir):
            if re.search(rf'^{re.escape(base_name)}\.part\d+\.rar$', filename, re.IGNORECASE):
                volume_path = os.path.join(base_dir, filename)
                if volume_path != main_archive_path:
                    volumes.append(volume_path)
    
    elif main_filename_lower.endswith('.7z.001'):
        # Multi-part 7z, find all parts
        base_name = main_filename[:-4]  # Remove .001
        for i in range(2, 1000):  # Check .002, .003, etc.
            volume_name = f"{base_name}{i:03d}"
            volume_path = os.path.join(base_dir, volume_name)
            if os.path.exists(volume_path):
                volumes.append(volume_path)
            else:
                break
    
    elif main_filename_lower.endswith('.zip'):
        # Split ZIP, look for .z01, .z02, etc.
        base_name = os.path.splitext(main_filename)[0]
        for i in range(1, 100):
            volume_name = f"{base_name}.z{i:02d}"
            volume_path = os.path.join(base_dir, volume_name)
            if os.path.exists(volume_path):
                volumes.append(volume_path)
    
    elif re.search(r'\.part0*1\.exe$', main_filename_lower):
        # Multi-part SFX, find all parts
        base_name = re.sub(r'\.part0*1\.exe$', '', main_filename, flags=re.IGNORECASE)
        for filename in os.listdir(base_dir):
            if re.search(rf'^{re.escape(base_name)}\.part\d+\.exe$', filename, re.IGNORECASE):
                volume_path = os.path.join(base_dir, filename)
                if volume_path != main_archive_path:
                    volumes.append(volume_path)
    
    return volumes


def count_items_in_dir(directory):
    """Count files and directories in a directory recursively."""
    files = 0
    dirs = 0
    
    for root, dirnames, filenames in os.walk(directory):
        files += len(filenames)
        dirs += len(dirnames)
    
    return files, dirs


def ensure_unique_name(target_path, unique_suffix):
    """Ensure target path is unique by adding unique_suffix if needed."""
    if not os.path.exists(target_path):
        return target_path
    
    base, ext = os.path.splitext(target_path)
    return f"{base}_{unique_suffix}{ext}"


def clean_temp_dir(temp_dir):
    """Safely remove temporary directory and confirm it's empty first."""
    try:
        if os.path.exists(temp_dir):
            # Check if directory is empty
            if not os.listdir(temp_dir):
                os.rmdir(temp_dir)
            else:
                # If not empty, force remove (this shouldn't happen in normal flow)
                shutil.rmtree(temp_dir)
                if VERBOSE:
                    print(f"  Warning: Temp directory {temp_dir} was not empty, force removed")
    except Exception as e:
        print(f"Warning: Could not remove temporary directory {temp_dir}: {e}")


class ArchiveProcessor:
    """Handles archive processing with various policies."""
    
    def __init__(self, args):
        self.args = args
        self.sfx_detector = SFXDetector(verbose=args.verbose)
        self.failed_archives = []
        self.successful_archives = []
        self.skipped_archives = []
        
    def find_archives(self, search_path):
        """Find all archives to process in the given path."""
        archives = []
        
        if os.path.isfile(search_path):
            if is_main_volume(search_path):
                archives.append(search_path)
        else:
            for root, dirs, files in os.walk(search_path):
                for file in files:
                    filepath = os.path.join(root, file)
                    
                    # Skip secondary volumes
                    if is_secondary_volume(filepath):
                        continue
                    
                    # Check if it's a main volume or potential archive
                    if is_main_volume(filepath):
                        # For .exe files, check if they're SFX
                        if filepath.lower().endswith('.exe'):
                            if self.sfx_detector.is_sfx(filepath):
                                archives.append(filepath)
                        else:
                            archives.append(filepath)
        
        return archives
    
    def find_correct_password(self, archive_path, password_candidates):
        """Find correct password from candidates using is_password_correct."""
        if not password_candidates:
            return ""
        
        for password in password_candidates:
            if is_password_correct(archive_path, password):
                return password
        
        return None
    
    def get_relative_path(self, file_path, base_path):
        """Get relative path from base path."""
        try:
            return os.path.relpath(os.path.dirname(file_path), base_path)
        except ValueError:
            return ""
    
    def move_volumes_with_structure(self, volumes, target_base):
        """Move volumes preserving directory structure."""
        os.makedirs(target_base, exist_ok=True)
        
        base_path = self.args.path if os.path.isdir(self.args.path) else os.path.dirname(self.args.path)
        
        for volume in volumes:
            try:
                rel_path = self.get_relative_path(volume, base_path)
                target_dir = os.path.join(target_base, rel_path) if rel_path else target_base
                os.makedirs(target_dir, exist_ok=True)
                
                target_file = os.path.join(target_dir, os.path.basename(volume))
                shutil.move(volume, target_file)
                print(f"  Moved: {volume} -> {target_file}")
            except Exception as e:
                print(f"  Warning: Could not move {volume}: {e}")
    
    def process_archive(self, archive_path):
        """Process a single archive following the exact specification."""
        print(f"Processing: {archive_path}")
        
        if self.args.dry_run:
            print(f"  [DRY RUN] Would process: {archive_path}")
            return True
        
        # Step 1: Determine if we need to test passwords
        # Following spec: only test passwords if -pf is provided
        need_password_testing = bool(self.args.password_file)
        
        # Step 2: Check encryption only if we need to test passwords
        is_encrypted = False
        if need_password_testing:
            encryption_status = check_encryption(archive_path)
            if encryption_status is True:
                is_encrypted = True
            elif encryption_status is None:
                print(f"  Warning: Cannot determine if {archive_path} is an archive")
                self.skipped_archives.append(archive_path)
                return False
        
        # Step 3: Prepare password candidates according to spec
        password_candidates = []
        correct_password = ""
        
        if need_password_testing and is_encrypted:
            # Build password candidate list: -p first, then -pf
            if self.args.password:
                password_candidates.append(self.args.password)
            
            if self.args.password_file:
                try:
                    with open(self.args.password_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            password = line.strip()
                            if password and password not in password_candidates:
                                password_candidates.append(password)
                except Exception as e:
                    print(f"  Warning: Cannot read password file: {e}")
            
            # Test passwords using is_password_correct
            correct_password = self.find_correct_password(archive_path, password_candidates)
            if correct_password is None:
                print(f"  Error: No correct password found for {archive_path}")
                # Apply fail policy before returning
                all_volumes = find_archive_volumes(archive_path)
                if self.args.fail_policy == 'move' and self.args.fail_to:
                    self.move_volumes_with_structure(all_volumes, self.args.fail_to)
                self.failed_archives.append(archive_path)
                return False
        else:
            # Not testing passwords - use provided password directly or empty
            correct_password = self.args.password if self.args.password else ""
        
        # Step 4: Create temporary directory with thread-safe unique name
        timestamp = str(int(time.time() * 1000))
        thread_id = threading.get_ident()
        unique_id = str(uuid.uuid4().hex[:8])  # 8-char random hex for extra safety
        unique_suffix = f"{timestamp}_{thread_id}_{unique_id}"
        tmp_dir = f"tmp_{unique_suffix}"
        
        try:
            # Step 5: Extract using try_extract function
            success = try_extract(archive_path, correct_password, tmp_dir)
            
            # Step 6: Find all volumes for this archive
            all_volumes = find_archive_volumes(archive_path)
            
            if success:
                print(f"  Successfully extracted to temporary directory")
                
                # Step 7: Apply success policy BEFORE decompress policy
                if self.args.success_policy == 'delete':
                    for volume in all_volumes:
                        try:
                            os.remove(volume)
                            print(f"  Deleted: {volume}")
                        except Exception as e:
                            print(f"  Warning: Could not delete {volume}: {e}")
                
                elif self.args.success_policy == 'move' and self.args.success_to:
                    self.move_volumes_with_structure(all_volumes, self.args.success_to)
                
                # Step 8: Apply decompress policy
                self.apply_decompress_policy(archive_path, tmp_dir, unique_suffix)
                
                self.successful_archives.append(archive_path)
                return True
                
            else:
                print(f"  Failed to extract: {archive_path}")
                
                # Step 7: Apply fail policy BEFORE decompress policy cleanup
                if self.args.fail_policy == 'move' and self.args.fail_to:
                    self.move_volumes_with_structure(all_volumes, self.args.fail_to)
                
                self.failed_archives.append(archive_path)
                return False
                
        finally:
            # Step 9: Clean up temporary directory
            clean_temp_dir(tmp_dir)
    
    def apply_decompress_policy(self, archive_path, tmp_dir, unique_suffix):
        """Apply the specified decompress policy following exact specification."""
        base_path = self.args.path if os.path.isdir(self.args.path) else os.path.dirname(self.args.path)
        rel_path = self.get_relative_path(archive_path, base_path)
        
        # Determine output directory
        if self.args.output:
            output_base = self.args.output
        else:
            output_base = base_path
        
        final_output_dir = os.path.join(output_base, rel_path) if rel_path else output_base
        os.makedirs(final_output_dir, exist_ok=True)
        
        archive_base_name = get_archive_base_name(archive_path)
        
        if self.args.decompress_policy == 'separate':
            self.apply_separate_policy(tmp_dir, final_output_dir, archive_base_name, unique_suffix)
        
        elif self.args.decompress_policy == 'direct':
            self.apply_direct_policy(tmp_dir, final_output_dir, archive_base_name, unique_suffix)
        
        else:
            # N-collect policy
            threshold = int(self.args.decompress_policy.split('-')[0])
            self.apply_collect_policy(tmp_dir, final_output_dir, archive_base_name, threshold, unique_suffix)
    
    def apply_separate_policy(self, tmp_dir, output_dir, archive_name, unique_suffix):
        """Apply separate decompress policy following exact specification."""
        separate_dir = f"separate_{unique_suffix}"
        
        try:
            os.makedirs(separate_dir, exist_ok=True)
            
            # Create archive folder in separate directory
            archive_folder = os.path.join(separate_dir, archive_name)
            archive_folder = ensure_unique_name(archive_folder, unique_suffix)
            os.makedirs(archive_folder, exist_ok=True)
            
            # Move contents from tmp to archive folder
            for item in os.listdir(tmp_dir):
                src_item = os.path.join(tmp_dir, item)
                dest_item = os.path.join(archive_folder, item)
                shutil.move(src_item, dest_item)
            
            # Move archive folder to final destination
            final_archive_path = os.path.join(output_dir, archive_name)
            final_archive_path = ensure_unique_name(final_archive_path, unique_suffix)
            shutil.move(archive_folder, final_archive_path)
            
            print(f"  Extracted to: {final_archive_path}")
            
        finally:
            clean_temp_dir(separate_dir)
    
    def apply_direct_policy(self, tmp_dir, output_dir, archive_name, unique_suffix):
        """Apply direct decompress policy following exact specification."""
        # Check for conflicts
        tmp_items = os.listdir(tmp_dir)
        conflicts = [item for item in tmp_items if os.path.exists(os.path.join(output_dir, item))]
        
        if conflicts:
            # Create archive folder for conflicts
            archive_folder = os.path.join(output_dir, archive_name)
            archive_folder = ensure_unique_name(archive_folder, unique_suffix)
            os.makedirs(archive_folder, exist_ok=True)
            
            # Move all items to archive folder
            for item in tmp_items:
                src_item = os.path.join(tmp_dir, item)
                dest_item = os.path.join(archive_folder, item)
                shutil.move(src_item, dest_item)
            
            print(f"  Extracted to: {archive_folder} (conflicts detected)")
        else:
            # Move directly to output directory
            for item in tmp_items:
                src_item = os.path.join(tmp_dir, item)
                dest_item = os.path.join(output_dir, item)
                shutil.move(src_item, dest_item)
            
            print(f"  Extracted to: {output_dir}")
    
    def apply_collect_policy(self, tmp_dir, output_dir, archive_name, threshold, unique_suffix):
        """Apply N-collect decompress policy following exact specification."""
        files, dirs = count_items_in_dir(tmp_dir)
        total_items = files + dirs
        
        if total_items >= threshold:
            # Create archive folder
            archive_folder = os.path.join(output_dir, archive_name)
            archive_folder = ensure_unique_name(archive_folder, unique_suffix)
            os.makedirs(archive_folder, exist_ok=True)
            
            # Move all items to archive folder
            for item in os.listdir(tmp_dir):
                src_item = os.path.join(tmp_dir, item)
                dest_item = os.path.join(archive_folder, item)
                shutil.move(src_item, dest_item)
            
            print(f"  Extracted to: {archive_folder} ({total_items} items >= {threshold})")
        else:
            # Extract directly, handling conflicts like direct policy
            self.apply_direct_policy(tmp_dir, output_dir, archive_name, unique_suffix)
            print(f"  Extracted directly ({total_items} items < {threshold})")


def main():
    """Main function."""
    global VERBOSE
    
    parser = argparse.ArgumentParser(
        description='Advanced archive decompressor supporting various formats and policies'
    )
    
    # Required argument
    parser.add_argument(
        'path',
        help='Path to file or folder to scan for archives'
    )
    
    # Optional arguments
    parser.add_argument(
        '-o', '--output',
        help='Output directory for extracted files'
    )
    
    parser.add_argument(
        '-p', '--password',
        help='Password for encrypted archives'
    )
    
    parser.add_argument(
        '-pf', '--password-file',
        help='Path to password file (one password per line)'
    )
    
    parser.add_argument(
        '-t', '--threads',
        type=int,
        default=1,
        help='Number of concurrent extraction tasks (default: 1)'
    )
    
    parser.add_argument(
        '-dp', '--decompress-policy',
        default='2-collect',
        help='Decompress policy: separate/direct/N-collect (default: 2-collect)'
    )
    
    parser.add_argument(
        '-sp', '--success-policy',
        choices=['delete', 'asis', 'move'],
        default='asis',
        help='Policy for successful extractions (default: asis)'
    )
    
    parser.add_argument(
        '--success-to',
        help='Directory to move successful archives (required with -sp move)'
    )
    
    parser.add_argument(
        '-fp', '--fail-policy',
        choices=['asis', 'move'],
        default='asis',
        help='Policy for failed extractions (default: asis)'
    )
    
    parser.add_argument(
        '--fail-to',
        help='Directory to move failed archives (required with -fp move)'
    )
    
    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help='Preview mode - do not actually extract'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    args = parser.parse_args()
    
    # Set global verbose flag
    VERBOSE = args.verbose
    
    # Validate arguments
    if not os.path.exists(args.path):
        print(f"Error: Path does not exist: {args.path}")
        return 1
    
    if args.success_policy == 'move' and not args.success_to:
        print("Error: --success-to is required when using -sp move")
        return 1
    
    if args.fail_policy == 'move' and not args.fail_to:
        print("Error: --fail-to is required when using -fp move")
        return 1
    
    # Validate decompress policy
    if args.decompress_policy not in ['separate', 'direct']:
        if not re.match(r'^\d+-collect$', args.decompress_policy):
            print(f"Error: Invalid decompress policy: {args.decompress_policy}")
            return 1
        else:
            # Validate N-collect threshold
            threshold = int(args.decompress_policy.split('-')[0])
            if threshold < 0:
                print(f"Error: N-collect threshold must be >= 0")
                return 1
    
    # Check if 7z is available
    try:
        subprocess.run(['7z'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        print("Error: 7z command not found. Please install p7zip or 7-Zip.")
        return 1
    
    # Create processor and find archives
    processor = ArchiveProcessor(args)
    archives = processor.find_archives(args.path)
    
    if not archives:
        print("No archives found to process.")
        return 0
    
    print(f"Found {len(archives)} archive(s) to process.")
    
    # Process archives
    if args.threads == 1:
        # Single-threaded processing
        for archive in archives:
            processor.process_archive(archive)
    else:
        # Multi-threaded processing
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = {executor.submit(processor.process_archive, archive): archive 
                      for archive in archives}
            
            for future in as_completed(futures):
                archive = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"Error processing {archive}: {e}")
                    processor.failed_archives.append(archive)
    
    # Print summary
    print("\n" + "="*50)
    print("PROCESSING SUMMARY")
    print("="*50)
    print(f"Total archives found: {len(archives)}")
    print(f"Successfully processed: {len(processor.successful_archives)}")
    print(f"Failed to process: {len(processor.failed_archives)}")
    print(f"Skipped: {len(processor.skipped_archives)}")
    
    if processor.failed_archives:
        print("\nFailed archives:")
        for archive in processor.failed_archives:
            print(f"  - {archive}")
    
    if processor.skipped_archives:
        print("\nSkipped archives:")
        for archive in processor.skipped_archives:
            print(f"  - {archive}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
