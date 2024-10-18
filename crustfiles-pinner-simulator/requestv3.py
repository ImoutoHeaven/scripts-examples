#!/usr/bin/env python3
import argparse
import sys
import requests
import logging
import time
import re
import os
from urllib.parse import urlparse

# Configure the basic logging format
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_arguments():
    parser = argparse.ArgumentParser(description='CrustFiles Pinner CallCommand')
    parser.add_argument('--auth', required=True, help='Authorization token')
    parser.add_argument('--low-level-retries', dest='max_retries', type=int, default=10,
                        help='Number of retries for each failed request (POST or OPTIONS)')
    parser.add_argument('--retries', type=str, default='3',
                        help='Number of times to retry processing failed files. Use "unless-stopped" for infinite retries.')
    parser.add_argument('--cooldown', type=str, default='1h',
                        help='Cooldown period between retries (e.g., 30s, 10m, 1h, 2d, 1w)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--input', type=str, help='Path to input file containing file table')
    parser.add_argument('--url', default='https://pin.crustcode.com:443', help='Server URL including protocol and port, e.g., https://xxx.com:443')
    parser.add_argument('--timeout-sleep-time', default='2s',
                        help='Sleep time after 5xx errors (e.g., 2s, 1m). Default is 2s.')
    parser.add_argument('--ban-max-sleep-time', default='5m',
                        help='Maximum sleep time after 4xx errors (e.g., 5m, 10s). Default is 5m.')
    return parser.parse_args()

def parse_time(time_str):
    match = re.match(r'^(\d+)([smhdw])$', time_str)
    if not match:
        raise ValueError('Invalid time format. Use formats like 30s, 10m, 1h, 2d, 1w')
    value = int(match.group(1))
    unit = match.group(2)
    if unit == 's':
        return value
    elif unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 3600
    elif unit == 'd':
        return value * 86400
    elif unit == 'w':
        return value * 604800
    else:
        raise ValueError('Invalid time unit')

def parse_cooldown(cooldown_str):
    return parse_time(cooldown_str)

def read_user_input(input_file=None):
    entries = []
    
    if input_file:
        if not os.path.exists(input_file):
            logging.error(f'File {input_file} does not exist.')
            sys.exit(1)
        with open(input_file, 'r') as file:
            lines = file.readlines()
    else:
        # Prompt user for interactive input
        print('---')
        print('CrustFiles Pinner CallCommand ver1.0')
        print('Input file name and cid tables:')
        print('<user input...>')
        print('[example:')
        print('<file name 1> <space/tab> <file cid 1> <space/tab> <file size 1>')
        print('<file name 2> <space/tab> <file cid 2> <space/tab> <file size 2>')
        print('...]')
        print('<file name i> <space/tab> <file cid i> <space/tab> <file size i>')
        print(']')
        print('(attention: Press Ctrl+D to start execution)')
        print('---')
        
        lines = []
        try:
            for line in sys.stdin:
                lines.append(line.strip())
        except EOFError:
            pass
    
    for line in lines:
        line = line.strip()  # Remove whitespace characters
        if not line:
            continue  # Skip empty lines
        tokens = line.rsplit(None, 2)  # Reverse split, last two parts are CID and file size
        if len(tokens) != 3:
            logging.warning(f'Invalid input line: "{line}". Expected format: <file_name> <cid> <size>. Skipping...')
            continue
        file_name, cid, size = tokens
        
        # Use regular expression to check if CID consists of valid characters
        if not re.match(r'^[a-zA-Z0-9]+$', cid):  # CID format validation, CID must consist of letters and numbers
            logging.warning(f'Invalid CID format: "{cid}" in line "{line}". Skipping...')
            continue
        if not size.isdigit():  # Ensure size is a number
            logging.warning(f'Invalid size: "{size}" in line "{line}". Skipping...')
            continue
        entries.append({'file_name': file_name, 'cid': cid, 'size': size})
    
    return entries

def process_entries(entries, auth_token, max_retries, url, timeout_sleep_time, ban_max_sleep_time):
    if not entries:
        logging.info("No entries to process.")
        return []

    total = len(entries)
    status_entries = []

    base_url = url.rstrip('/')
    full_url = f'{base_url}/psa/pins'

    parsed_url = urlparse(base_url)
    origin = f'{parsed_url.scheme}://{parsed_url.netloc}'
    referer = f'{origin}/'

    headers_options = {
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Access-Control-Request-Headers': 'authorization,content-type',
        'Access-Control-Request-Method': 'POST',
        'Origin': origin,
        'Referer': referer,
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }

    headers_post = {
        'Accept': 'application/json, text/plain, */*',
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json',
        'Referer': referer,
        'Sec-CH-UA': '"Chromium";v="127", "Not)A;Brand";v="99"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Windows"',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }

    INITIAL_BACKOFF_TIME = 2  # seconds

    for idx, entry in enumerate(entries, start=1):
        file_name = entry['file_name']
        cid = entry['cid']
        size = entry['size']
        logging.info(f'Start processing {idx}/{total}.')
        success = False
        response_status_code = None

        backoff_time_options = INITIAL_BACKOFF_TIME
        backoff_time_post = INITIAL_BACKOFF_TIME

        # OPTIONS request
        for attempt in range(1, max_retries + 1):
            try:
                logging.debug(f'Attempting OPTIONS request {attempt}/{max_retries}')
                response = requests.options(full_url, headers=headers_options)
                response_status_code = response.status_code
                if 200 <= response_status_code < 300:
                    break
                else:
                    if 500 <= response_status_code < 600:
                        logging.warning(f'Failed OPTIONS request {attempt}/{max_retries}, response is {response_status_code}, server error. Retrying after {timeout_sleep_time} seconds...')
                        time.sleep(timeout_sleep_time)
                    elif 400 <= response_status_code < 500:
                        logging.warning(f'Failed OPTIONS request {attempt}/{max_retries}, response is {response_status_code}, client error. Retrying after {backoff_time_options} seconds...')
                        time.sleep(backoff_time_options)
                        backoff_time_options = min(backoff_time_options * 2, ban_max_sleep_time)
                    else:
                        logging.error(f'Unexpected response code {response_status_code} during OPTIONS request.')
                        time.sleep(timeout_sleep_time)
            except requests.exceptions.RequestException as e:
                logging.error(f'Exception during OPTIONS request: {e}')
                logging.warning(f'Exception during OPTIONS request, treating as server error. Retrying after {timeout_sleep_time} seconds...')
                time.sleep(timeout_sleep_time)
            if attempt == max_retries:
                logging.error(f'Failed OPTIONS request {attempt}/{max_retries}, retry count exceeded.')
                status_entries.append({'status_code': response_status_code, 'status': 'failed', 'file_name': file_name, 'cid': cid, 'entry': entry})
                break

        if attempt == max_retries and response_status_code not in range(200, 300):
            continue  # Skip to next entry if OPTIONS request fails after retries

        # POST request
        payload = {'cid': cid, 'name': file_name}
        for attempt in range(1, max_retries + 1):
            try:
                logging.debug(f'Attempting POST request {attempt}/{max_retries}')
                response = requests.post(full_url, headers=headers_post, json=payload)
                response_status_code = response.status_code
                if 200 <= response_status_code < 300:
                    logging.info(f'Successful POST request for {file_name}.')
                    success = True
                    status_entries.append({'status_code': response_status_code, 'status': 'success', 'file_name': file_name, 'cid': cid, 'entry': entry})
                    break
                else:
                    if 500 <= response_status_code < 600:
                        logging.warning(f'Failed POST request {attempt}/{max_retries}, response is {response_status_code}, server error. Retrying after {timeout_sleep_time} seconds...')
                        time.sleep(timeout_sleep_time)
                    elif 400 <= response_status_code < 500:
                        logging.warning(f'Failed POST request {attempt}/{max_retries}, response is {response_status_code}, client error. Retrying after {backoff_time_post} seconds...')
                        time.sleep(backoff_time_post)
                        backoff_time_post = min(backoff_time_post * 2, ban_max_sleep_time)
                    else:
                        logging.error(f'Unexpected response code {response_status_code} during POST request.')
                        time.sleep(timeout_sleep_time)
            except requests.exceptions.RequestException as e:
                logging.error(f'Exception during POST request: {e}')
                logging.warning(f'Exception during POST request, treating as server error. Retrying after {timeout_sleep_time} seconds...')
                time.sleep(timeout_sleep_time)
            if attempt == max_retries:
                logging.error(f'Failed POST request {attempt}/{max_retries}, retry count exceeded.')
                status_entries.append({'status_code': response_status_code, 'status': 'failed', 'file_name': file_name, 'cid': cid, 'entry': entry})

    return status_entries

def print_summary(status_entries):
    print('---')
    print('Process completed. Status:')
    print()
    failed_entries = []
    for entry in status_entries:
        status_code = entry['status_code']
        status = entry['status']
        file_name = entry['file_name']
        print(f'{status_code} {status}\t{file_name}')
        if status == 'failed':
            failed_entries.append(entry)
    print('---')
    if failed_entries:
        print('Files that need to be retried (in table):')
        for entry in failed_entries:
            file_entry = entry['entry']
            print(f'{file_entry["file_name"]}\t{file_entry["cid"]}\t{file_entry["size"]}')
        print('---')

def main():
    args = parse_arguments()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger('urllib3').setLevel(logging.DEBUG)
        logging.debug('Debug logging enabled')

    if args.retries == 'unless-stopped':
        max_retries = None  # Infinite retries
    else:
        try:
            max_retries = int(args.retries)
            if max_retries < 0:
                raise ValueError
        except ValueError:
            logging.error('Invalid value for --retries. Must be a non-negative integer or "unless-stopped".')
            sys.exit(1)

    entries = read_user_input(args.input)
    if not entries:
        logging.info('No entries to process.')
        sys.exit(0)

    try:
        cooldown_seconds = parse_cooldown(args.cooldown)
    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)

    try:
        timeout_sleep_time = parse_time(args.timeout_sleep_time)
    except ValueError as e:
        logging.error(f'Invalid timeout-sleep-time: {e}')
        sys.exit(1)

    try:
        ban_max_sleep_time = parse_time(args.ban_max_sleep_time)
    except ValueError as e:
        logging.error(f'Invalid ban-max-sleep-time: {e}')
        sys.exit(1)

    retry_count = 0
    status_dict = {}

    while True:
        if retry_count > 0:
            if max_retries is not None:
                logging.info(f'Retry attempt {retry_count}/{max_retries}')
            else:
                logging.info(f'Retry attempt {retry_count}')
        
        status_entries = process_entries(entries, args.auth, args.max_retries, args.url, timeout_sleep_time, ban_max_sleep_time)
        if not status_entries:
            logging.info('No status entries returned.')
            break
        
        for entry in status_entries:
            key = (entry['file_name'], entry['cid'])
            status_dict[key] = entry
        
        failed_entries = [entry['entry'] for entry in status_entries if entry['status'] == 'failed']
        if failed_entries:
            if max_retries is None or retry_count < max_retries:
                logging.info(f'Waiting for {cooldown_seconds} seconds before retrying failed entries.')
                time.sleep(cooldown_seconds)
                entries = failed_entries
                retry_count += 1
            else:
                logging.info('Maximum number of retries reached. Exiting.')
                break
        else:
            break

    print_summary(list(status_dict.values()))

if __name__ == '__main__':
    main()
