
# IPFS File Uploader

This is a Python script designed to upload files to an IPFS (InterPlanetary File System) gateway using HTTP requests. It can handle a folder of files recursively, retry failed uploads, and generate progress logs.

## Features
- Upload files to an IPFS gateway.
- Recursively scans and uploads files from a folder.
- Automatic retries for failed uploads.
- Support for secure and insecure connections.
- Detailed debugging for failed uploads.
- Track upload status and generate file hash tables.

## Requirements
- Python 3.8+
- Required Python packages:
  - `requests`
  - `tqdm`

Install the required packages using pip:

```sh
pip install requests tqdm
```

## Usage
The script requires the IPFS gateway URL, and authentication credentials to generate the required Bearer token.

```sh
python ipfs_uploader.py -gw <gateway_url> --addr <address> --hex <hex_value> <folder_path>
```

### Arguments
- `-gw`, `--gateway` (required): The URL of the IPFS gateway.
- `--retries`: The number of retries for failed uploads. Default is 3.
- `--addr`: Address for generating a Bearer token.
- `--hex`: Hex value for generating a Bearer token.
- `--auth`: Pre-generated auth header (either provide this or use `--addr` and `--hex`).
- `--allow-insecure`: Allow insecure connections by skipping SSL verification. Enabled by default.
- `--debug`: Enable detailed debugging logs for failed uploads.
- `<folder_path>` (required): The path to the folder containing files to be uploaded.

### Example
To upload all files from a folder:

```sh
python ipfs_uploader.py -gw http://localhost:5001 --addr your_address --hex your_hex_value ./your_folder
```

### Output
- **Upload Status**: Displays the upload status of each file.
- **File CID Table**: Prints a table of file names with their corresponding CID hashes and file sizes.

## Notes
- The script uses a Bearer token for authorization, which can either be generated using the provided address and hex value, or be provided directly.
- Files that fail to upload after the maximum number of retries will be logged for further inspection.
- By default, SSL verification is disabled, but this can be adjusted with `--allow-insecure`.

## License
No License. Use at your own risk.
