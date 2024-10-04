#!/usr/bin/env python3
import argparse
import sys
import requests
import logging
import time
import re

# Configure the basic logging format
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_arguments():
    parser = argparse.ArgumentParser(description='CrustFiles Pinner CallCommand')
    parser.add_argument('--auth', required=True, help='Authorization token')
    parser.add_argument('--low-level-retries', dest='low_level_retries', type=int, default=10,
                        help='Number of retries for each failed request (POST or OPTIONS)')
    parser.add_argument('--retries', type=str, default='3',
                        help='Number of times to retry processing failed files. Use "unless-stopped" for infinite retries.')
    parser.add_argument('--cooldown', type=str, default='1h',
                        help='Cooldown period between retries (e.g., 30s, 10m, 1h, 2d, 1w)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    return parser.parse_args()

def parse_cooldown(cooldown_str):
    match = re.match(r'^(\d+)([smhdw])$', cooldown_str)
    if not match:
        raise ValueError('Invalid cooldown format. Use formats like 30s, 10m, 1h, 2d, 1w')
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
        raise ValueError('Invalid time unit in cooldown')

def read_user_input():
    print('---')
    print('CrustFiles Pinner CallCommand ver1.0')
    print('Input file name and cid tables:')
    print('<user input...>')
    print('[example:')
    print('<file name 1> <space/tab> <file cid 1> <space/tab> <file size 1>')
    print('<file name 2> <space/tab> <file cid 2> <space/tab> <file size 2>')
    print('...')
    print('<file name i> <space/tab> <file cid i> <space/tab> <file size i>')
    print(']')
    print('(attention: Press Ctrl+D to start execution)')
    print('---')

    entries = []
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            tokens = line.rsplit(None, 2)
            if len(tokens) != 3:
                print(f'Invalid input line: "{line}"')
                continue
            file_name, cid, size = tokens
            entries.append({'file_name': file_name, 'cid': cid, 'size': size})
    except EOFError:
        pass
    print('---')
    return entries

def process_entries(entries, auth_token, max_retries):
    total = len(entries)
    status_entries = []

    headers_options = {
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Access-Control-Request-Headers': 'authorization,content-type',
        'Access-Control-Request-Method': 'POST',
        'Origin': 'https://crustfiles.io',
        'Referer': 'https://crustfiles.io/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }

    headers_post = {
        'Accept': 'application/json, text/plain, */*',
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json',
        'Referer': 'https://crustfiles.io/',
        'Sec-CH-UA': '"Chromium";v="127", "Not)A;Brand";v="99"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Windows"',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }

    url = 'https://pin.crustcode.com/psa/pins'

    for idx, entry in enumerate(entries, start=1):
        file_name = entry['file_name']
        cid = entry['cid']
        size = entry['size']
        logging.info(f'start processing {idx}/{total}.')
        success = False
        response_status_code = None

        # OPTIONS request
        for attempt in range(1, max_retries + 1):
            try:
                logging.debug(f'Attempting OPTIONS request {attempt}/{max_retries}')
                response = requests.options(url, headers=headers_options)
                response_status_code = response.status_code
                logging.debug(f'OPTIONS request headers: {headers_options}')
                logging.debug(f'OPTIONS response status code: {response.status_code}')
                logging.debug(f'OPTIONS response headers: {response.headers}')
                if 200 <= response.status_code < 300:
                    # Success on OPTIONS request
                    break
                elif 400 <= response.status_code < 600:
                    # Fail and retry
                    logging.warning(f'failed {idx}/{total}, response is {response.status_code}, retry in {attempt}/{max_retries}...')
                else:
                    logging.error(f'Unexpected response code {response.status_code} during OPTIONS request.')
            except requests.exceptions.RequestException as e:
                logging.error(f'Exception during OPTIONS request: {e}')
            if attempt == max_retries:
                logging.error(f'failed {idx}/{total}, response is {response_status_code}, retry count exceeded, skipped by now.')
                status_entries.append({'status_code': response_status_code, 'status': 'failed', 'file_name': file_name, 'cid': cid, 'entry': entry})
                break
        else:
            continue  # Skip to next entry if OPTIONS request fails

        if attempt == max_retries and response_status_code not in range(200, 300):
            continue  # Skip to next entry if OPTIONS request fails after retries

        # POST request
        payload = {'cid': cid, 'name': file_name}
        for attempt in range(1, max_retries + 1):
            try:
                logging.debug(f'Attempting POST request {attempt}/{max_retries}')
                response = requests.post(url, headers=headers_post, json=payload)
                response_status_code = response.status_code
                logging.debug(f'POST request headers: {headers_post}')
                logging.debug(f'POST request payload: {payload}')
                logging.debug(f'POST response status code: {response.status_code}')
                logging.debug(f'POST response headers: {response.headers}')
                logging.debug(f'POST response content: {response.text}')
                if 200 <= response.status_code < 300:
                    logging.info(f'{response_status_code} success {idx}/{total}.')
                    success = True
                    status_entries.append({'status_code': response_status_code, 'status': 'success', 'file_name': file_name, 'cid': cid, 'entry': entry})
                    break
                elif 400 <= response.status_code < 600:
                    logging.warning(f'failed {idx}/{total}, response is {response_status_code}, retry in {attempt}/{max_retries}...')
                else:
                    logging.error(f'Unexpected response code {response_status_code} during POST request.')
            except requests.exceptions.RequestException as e:
                logging.error(f'Exception during POST request: {e}')
            if attempt == max_retries:
                logging.error(f'failed {idx}/{total}, response is {response_status_code}, retry count exceeded, skipped by now.')
                status_entries.append({'status_code': response_status_code, 'status': 'failed', 'file_name': file_name, 'cid': cid, 'entry': entry})
        if not success and not any(d['file_name'] == file_name and d['cid'] == cid for d in status_entries):
            status_entries.append({'status_code': response_status_code, 'status': 'failed', 'file_name': file_name, 'cid': cid, 'entry': entry})
    return status_entries

def print_summary(status_entries):
    print('---')
    print('process completed. status:')
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
        print('---')
        print('files that need to be retried (in table):')
        for entry in failed_entries:
            file_entry = entry['entry']
            print(f'{file_entry["file_name"]}\t{file_entry["cid"]}\t{file_entry["size"]}')
        print('---')

def main():
    args = parse_arguments()
    if args.debug:
        # Set logging level to DEBUG
        logging.getLogger().setLevel(logging.DEBUG)
        # Enable debugging for requests library
        logging.getLogger('urllib3').setLevel(logging.DEBUG)
        logging.debug('Debug logging enabled')

    # Process args.retries
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

    entries = read_user_input()
    if not entries:
        logging.info('No entries to process.')
        sys.exit(0)

    try:
        cooldown_seconds = parse_cooldown(args.cooldown)
    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)

    retry_count = 0
    status_dict = {}  # key: (file_name, cid), value: status_entry

    while True:
        if retry_count > 0:
            if max_retries is not None:
                logging.info(f'Retry attempt {retry_count}/{max_retries}')
            else:
                logging.info(f'Retry attempt {retry_count}')
        status_entries = process_entries(entries, args.auth, args.low_level_retries)
        # Update status_dict with the latest status
        for entry in status_entries:
            key = (entry['file_name'], entry['cid'])
            status_dict[key] = entry
        # Collect failed entries
        failed_entries = [entry['entry'] for entry in status_entries if entry['status'] == 'failed']
        if failed_entries:
            if max_retries is None or retry_count < max_retries:
                if retry_count > 0:
                    logging.info(f'Failed entries detected. Waiting for {cooldown_seconds} seconds before retrying.')
                    time.sleep(cooldown_seconds)
                entries = failed_entries
                retry_count += 1
            else:
                logging.info('Maximum number of retries reached. Exiting.')
                break
        else:
            # All entries processed successfully
            break

    # After all retries, print summary
    print_summary(list(status_dict.values()))

if __name__ == '__main__':
    main()
