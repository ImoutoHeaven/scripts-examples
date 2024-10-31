
# CrustFiles Pinner CallCommand

This Python script is a command-line tool for interacting with the CrustFiles pinner service. 
It sends `OPTIONS` and `POST` requests to pin files to Crust Network via CrustFiles API and handles retries and error handling based on server responses.

## Script Logic

1. **Argument Parsing**: The script uses `argparse` to parse command-line arguments for various configurations such as authorization token, retries, cooldown periods, and input file paths.

2. **Cooldown and Retry Logic**: 
   - If a request fails, the script implements cooldown and exponential backoff between retries.
   - The user can specify the maximum number of retries and cooldown duration after failures.

3. **Input Handling**: 
   - The script reads file details (name, CID, size) from a specified file or through interactive input.
   - Validates each entry to ensure it contains the correct format and skips any invalid entries.

4. **Request Processing**:
   - For each file entry, the script first makes an `OPTIONS` request to the server, followed by a `POST` request to pin the file.
   - It includes exponential backoff logic to handle server-side errors.
   - In the case of multiple consecutive 4xx responses, the script increases the retry delay to prevent server overload.

5. **Output**:
   - The script logs the status of each processed file and displays a summary of successful and failed entries.

## Usage

### Required Arguments
- `--auth`: Authorization token for accessing the CrustFiles API.

### Optional Arguments
- `--low-level-retries` or `--max-retries`: Number of retries for each failed request (default: 10).
- `--retries`: Number of times to retry processing failed files. Use "unless-stopped" for infinite retries (default: 3).
- `--cooldown`: Cooldown period between retries (e.g., 30s, 10m, 1h).
- `--debug`: Enable debug logging for detailed logs.
- `--input`: Path to input file containing the file table.
- `--url`: Server URL (default: `https://pin.crustcode.com:443`).
- `--timeout-sleep-time`: Sleep time after server (5xx) errors (default: 2s).
- `--ban-max-sleep-time`: Maximum sleep time after client (4xx) errors (default: 5m).

### Example Usage

```bash
python3 crustfiles_pinner.py --auth YOUR_AUTH_TOKEN --input file_table.txt --retries 5 --cooldown 1h
```

## Input

The input file or interactive input should follow this format:
```
<file_name> <CID> <size>
```
- `file_name`: Name of the file.
- `CID`: Content ID of the file.
- `size`: File size.

### Example Input
```
file1.jpg QmYwAPJzv5CZsnAzt8auVZRn6cYvZ7rZjp7kWsVdpJcwY1 51200
file2.png QmXxPzK8L2K9yV4tz5RmJ6cqkTfW5qM9C4XjV1qB6D 1048576
```

## Output

The script logs the status of each processed file, summarizing the following:
- Status code and success/failure for each file.
- A table of failed entries for possible retry.

### Example Output
```
---
Process completed. Status:
200 success file1.jpg
404 failed  file2.png
---
Files that need to be retried:
file2.png QmXxPzK8L2K9yV4tz5RmJ6cqkTfW5qM9C4XjV1qB6D 1048576
---
```

## License

This script is licensed under the GPL-3.0-only License.

---
