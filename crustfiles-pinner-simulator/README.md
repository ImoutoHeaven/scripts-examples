# CrustFiles Pinner CallCommand

This script is designed to interact with the CrustFiles service, which helps in pinning files to the Crust Network. It provides a command-line interface to input file details and initiate pinning operations via HTTP requests to Crust's API endpoint.

## Requirements

- Python 3.8 or higher
- The following Python packages:
  - `argparse` (standard library)
  - `sys` (standard library)
  - `requests`
  - `logging`
  - `re`

## Installation

Before running the script, make sure you have installed the required dependencies. You can install the `requests` library using the following command:

```sh
pip install requests
```

## Usage

```sh
./crustfiles_pinner.py --auth <Authorization Token> [OPTIONS]
```

### Arguments

- `--auth`: **Required**. Authorization token for the Crust service.

### Options

- `--low-level-retries`: Number of retries for each failed HTTP request (POST or OPTIONS). Default is `10`.

- `--retries`: Number of times to retry processing failed files. Use `"unless-stopped"` for infinite retries. Default is `3`.

- `--cooldown`: Cooldown period between retries (e.g., `30s`, `10m`, `1h`, `2d`, `1w`). Default is `1h`.

- `--debug`: Enable debug logging for more verbose output.

### Example

```sh
./crustfiles_pinner.py --auth myAuthToken123 --retries 5 --cooldown 30s --debug
```

## Input Format

The script will prompt the user for input with the following format:

```
<file name> <space/tab> <file cid> <space/tab> <file size>
```

Example:

```
example-file.txt  QmExampleCid1234567890  12345
example-image.jpg QmAnotherCid0987654321  54321
```

Press `Ctrl+D` to complete the input and start processing the files.

## Logging

The script uses Python's `logging` module to print logs to the console. If `--debug` is provided, debug logs are printed to provide more information about the process.

### Log Levels
- `INFO`: General information about the progress.
- `WARNING`: Warnings related to failed retries.
- `ERROR`: Errors that occurred during requests.
- `DEBUG`: Detailed logs, enabled with the `--debug` flag.

## Processing Flow

1. **OPTIONS Request**: The script first sends an OPTIONS request to the Crust API endpoint to check permissions.
2. **POST Request**: If the OPTIONS request is successful, it proceeds with a POST request to pin the file to Crust.
3. **Retries**: The script will retry failed requests based on the values provided with the `--low-level-retries` and `--retries` options.
4. **Cooldown**: The script will pause for the defined `--cooldown` period before retrying failed requests.

## Output

The script prints a summary of the processed entries, including their status and any entries that failed to be processed.

### Example Output

```
---
process completed. status:

200 success  example-file.txt
500 failed   example-image.jpg
---
---
files that need to be retried (in table):
example-image.jpg  QmAnotherCid0987654321  54321
---
```

## License

This project is licensed under the MIT License.
