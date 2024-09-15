import os
import base64
import argparse
import requests
from time import sleep
from tqdm import tqdm  # For progress bar
import urllib3
import traceback  # For detailed exception traceback

# Suppress only the specific InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def generate_bearer_token(addr, hex_value):
    auth_string = f"sub-{addr}:{hex_value}"
    auth_header = base64.b64encode(auth_string.encode()).decode()
    return auth_header

def upload_file(file_path, relative_path, gateway_url, headers, retries, file_index, total_files, verify_ssl, debug_mode):
    url = f"{gateway_url}/api/v0/add?pin=true&cid-version=1"
    file_size = os.path.getsize(file_path)  # Calculate file size locally
    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')}
        attempt = 0
        print(f"start file {file_index}/{total_files} {os.path.basename(file_path)} uploading:")
        progress_bar = tqdm(total=100, bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}]")

        while attempt < retries:
            try:
                response = requests.post(url, headers=headers, files=files, verify=verify_ssl)
                if response.status_code == 200:
                    res_json = response.json()
                    file_hash = res_json.get('Hash', 'N/A')
                    progress_bar.update(100)
                    progress_bar.close()
                    print(f"file {file_index}/{total_files} upload successfully")
                    return "success", os.path.basename(file_path), relative_path, file_hash, file_size
                else:
                    # For any non-200 response, treat the upload as failed and retry
                    attempt += 1
                    print(f"Attempt {attempt}/{retries} failed for {os.path.basename(file_path)}.")
                    if debug_mode:
                        print(f"Response status code: {response.status_code}")
                        print(f"Response content: {response.content.decode('utf-8')}")
                    if response.status_code == 413:
                        # Handle specific large file issue and exit retry
                        print(f"File {os.path.basename(file_path)} is too large to upload.")
                        break
                    progress_bar.update(20)
                    sleep(1)  # Delay between retries
            except Exception as e:
                attempt += 1
                print(f"Error on attempt {attempt}/{retries} for {os.path.basename(file_path)}.")
                if debug_mode:
                    print(f"Exception: {str(e)}")
                    traceback.print_exc()  # Print full traceback when in debug mode
                progress_bar.update(20)
                sleep(1)
        progress_bar.close()
    print(f"file {file_index}/{total_files} failed to upload")
    return "failed", os.path.basename(file_path), relative_path, None, file_size

def recursive_upload(folder_path, gateway_url, headers, retries, verify_ssl, debug_mode):
    print("scanning folders...")
    files_list = []
    for root, _, files in os.walk(folder_path):
        for file_name in files:
            full_path = os.path.join(root, file_name)
            relative_path = os.path.relpath(full_path, folder_path)  # Calculate relative path
            files_list.append((full_path, relative_path))

    total_files = len(files_list)
    print(f"total files to upload: {total_files}")

    file_stat_results = []
    cid_table_results = []
    for idx, (file_path, relative_path) in enumerate(files_list, start=1):
        status, name, rel_path, file_hash, file_size = upload_file(file_path, relative_path, gateway_url, headers, retries, idx, total_files, verify_ssl, debug_mode)
        # Collect file stat results
        file_stat_results.append(f"{status} {name} {rel_path}")
        # Collect cid table results if upload is successful
        if file_hash:
            cid_table_results.append(f"{name}\t{file_hash}\t{file_size}")

    return file_stat_results, cid_table_results

def main():
    parser = argparse.ArgumentParser(description="Upload files to IPFS gateway")
    parser.add_argument('-gw', '--gateway', required=True, help='IPFS Gateway URL')
    parser.add_argument('--retries', type=int, default=3, help='Number of retries for failed uploads')
    parser.add_argument('--addr', help='Address for token generation')
    parser.add_argument('--hex', help='Hex value for token generation')
    parser.add_argument('--auth', help='Pre-generated auth header')
    parser.add_argument('--allow-insecure', action='store_true', default=True, help='Allow insecure connections (skip SSL verification). Default: enabled.')
    parser.add_argument('--debug', action='store_true', help='Enable detailed error logs and exceptions.')
    parser.add_argument('folder', help='Path to folder for upload')

    args = parser.parse_args()

    if args.auth:
        auth_header = args.auth
    elif args.addr and args.hex:
        auth_header = generate_bearer_token(args.addr, args.hex)
    else:
        print("Either --auth or both --addr and --hex must be provided")
        return

    headers = {'Authorization': f'Bearer {auth_header}'}
    verify_ssl = not args.allow_insecure
    debug_mode = args.debug

    file_stat_results, cid_table_results = recursive_upload(args.folder, args.gateway, headers, args.retries, verify_ssl, debug_mode)

    # Print file stat results
    print("\nupload finished. file stat:\n")
    for result in file_stat_results:
        print(result)

    # Print file cid table results
    print("\nfile cid table:\n")
    for result in cid_table_results:
        print(result)

if __name__ == "__main__":
    main()
