#!/usr/bin/env python3

import argparse
import subprocess
import time
import os
import sys
import re

def parse_cooldown(cooldown_str):
    # Parse the cooldown argument, return seconds
    # Examples: '1h', '30m', '10s', '2d', '1w'
    match = re.match(r'(\d+)([smhdw])$', cooldown_str)
    if not match:
        raise ValueError("Invalid cooldown format. Please use format like '1h', '30m', '10s', '2d', '1w'")
    value, unit = match.groups()
    value = int(value)
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
        raise ValueError("Invalid cooldown unit")

def parse_arguments():
    parser = argparse.ArgumentParser(description='Execute commands and process outputs.')
    parser.add_argument('-o', '--out', default='check-output.log', help='Path to log file')
    parser.add_argument('--low-level-retries', type=int, default=30,
                        help='Number of retries for each command on error (default: 30)')
    parser.add_argument('--retries', default='unless-stopped',
                        help='Number of times the entire script loops (number or "unless-stopped"). Default is "unless-stopped"')
    parser.add_argument('--cooldown', default='1h',
                        help='Sleep time between retries (e.g., 30s, 15m, 1h, 1d). Default is 1h')
    args = parser.parse_args()
    return args

def read_commands():
    print("请输入需要逐行执行的指令，按回车输入下一条指令；全部输入完成后按Ctrl+D进行运行：")
    commands = []
    try:
        for line in sys.stdin:
            line = line.strip()
            if line:
                commands.append(line)
    except EOFError:
        pass
    return commands

class Command:
    def __init__(self, cmd_str, index):
        self.cmd_str = cmd_str
        self.index = index
        self.cid = self.extract_cid()
        self.status = None  # 'success', 'error', 'failed', 'empty', 'pinning', 'queued', 'pinned'
        self.output = ''
        self.retries = 0
        self.completed = False  # Set to True when no longer needs to be retried

    def extract_cid(self):
        match = re.search(r'--cid=([^\s]+)', self.cmd_str)
        if match:
            return match.group(1)
        else:
            return None  # Or some default value

def execute_command(command_obj, low_level_retries):
    success = False
    while command_obj.retries < low_level_retries:
        print(f"正在执行第{command_obj.index +1}条：{command_obj.cmd_str}")
        process = subprocess.Popen(command_obj.cmd_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        output = stdout + stderr
        command_obj.output = output
        print(output)
        
        if re.search(r'error', output, re.IGNORECASE):
            command_obj.retries +=1
            if command_obj.retries < low_level_retries:
                print(f"第{command_obj.index +1}条指令遇到错误，重试{command_obj.retries}/{low_level_retries}次：")
            else:
                print(f"第{command_obj.index +1}条指令在多次重试后仍然失败，跳过；")
                command_obj.status = 'error'
                command_obj.completed = True
            continue
        else:
            # Process other statuses
            if not output.strip():
                print(f"第{command_obj.index +1}条指令stdout和stderr均无输出，记录此指令；")
                command_obj.status = 'empty'
            elif re.search(r'failed', output, re.IGNORECASE):
                print("stdout或stderr返回failed，记录此指令。")
                command_obj.status = 'failed'
            elif re.search(r'pinned', output, re.IGNORECASE):
                print(f"第{command_obj.index +1}条指令返回pinned，跳过；")
                command_obj.status = 'pinned'
            elif re.search(r'pinning', output, re.IGNORECASE):
                print("stdout或stderr返回pinning，记录此指令。")
                command_obj.status = 'pinning'
            elif re.search(r'queued', output, re.IGNORECASE):
                print("stdout或stderr返回queued，记录此指令。")
                command_obj.status = 'queued'
            else:
                print(f"第{command_obj.index +1}条指令执行成功，stdout和stderr输出：")
                command_obj.status = 'success'
            command_obj.completed = True
            success = True
            break
    if not success and command_obj.retries >= low_level_retries and not command_obj.completed:
        command_obj.status = 'error'
        command_obj.completed = True

def main():
    args = parse_arguments()
    log_file = args.out
    low_level_retries = args.low_level_retries
    retries_arg = args.retries
    cooldown_str = args.cooldown
    try:
        cooldown = parse_cooldown(cooldown_str)
    except ValueError as e:
        print(str(e))
        sys.exit(1)
    
    # Handle retries argument
    if retries_arg == 'unless-stopped':
        retries = None
    else:
        try:
            retries = int(retries_arg)
            if retries < 1:
                raise ValueError
        except ValueError:
            print("Invalid --retries value. Please provide a positive integer or 'unless-stopped'.")
            sys.exit(1)
    
    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    
    commands = read_commands()
    if not commands:
        print("No commands provided.")
        sys.exit(0)
    
    # Create Command objects
    command_objects = [Command(cmd_str, idx) for idx, cmd_str in enumerate(commands)]
    total_retries = 0

    while True:
        # Check if we have exceeded retries
        if retries is not None and total_retries >= retries:
            break
        total_retries += 1

        commands_to_process = [cmd_obj for cmd_obj in command_objects if not cmd_obj.completed and cmd_obj.status != 'success']
        if not commands_to_process:
            # All commands completed
            break

        for cmd_obj in commands_to_process:
            execute_command(cmd_obj, low_level_retries)

        # Check if there are commands still needing retries
        commands_to_retry = [cmd_obj for cmd_obj in command_objects if not cmd_obj.completed and cmd_obj.status == 'error']
        if not commands_to_retry:
            # All commands completed
            break
        else:
            # Sleep cooldown
            print(f"所有指令未成功执行，等待 {cooldown} 秒后重试...")
            time.sleep(cooldown)

    # Collect statuses
    pinning_commands = [cmd_obj.cid for cmd_obj in command_objects if cmd_obj.status == 'pinning' and cmd_obj.cid]
    queued_commands = [cmd_obj.cid for cmd_obj in command_objects if cmd_obj.status == 'queued' and cmd_obj.cid]
    failed_commands = [cmd_obj.cid for cmd_obj in command_objects if cmd_obj.status == 'failed' and cmd_obj.cid]
    error_failed_commands = [cmd_obj.cid for cmd_obj in command_objects if cmd_obj.status == 'error' and cmd_obj.cid]
    empty_output_commands = [cmd_obj.cid for cmd_obj in command_objects if cmd_obj.status == 'empty' and cmd_obj.cid]

    total_cids = pinning_commands + queued_commands + failed_commands + error_failed_commands + empty_output_commands

    # Generate log file
    def write_section(f, title, cids):
        f.write(f"{title}:\n")
        if cids:
            for cid in cids:
                f.write(f"{cid}\n")
        else:
            f.write("None\n")
        f.write("======\n")

    # Write to log file and print results
    with open(log_file, 'w') as f:
        write_section(f, "pinning", pinning_commands)
        write_section(f, "queued", queued_commands)
        write_section(f, "failed", failed_commands)
        write_section(f, "error executing", error_failed_commands)
        write_section(f, "empty response", empty_output_commands)
        f.write("=*=*=*=*=*=\n")
        f.write("total all cids:\n")
        if total_cids:
            for cid in total_cids:
                f.write(f"{cid}\n")
        else:
            f.write("None\n")
        f.write("=*=*=*=*=*=\n")

    # Also print results to console
    print("\n执行结果：")
    with open(log_file, 'r') as f:
        print(f.read())

    print(f"脚本执行完毕，所有结果已记录到日志文件：{log_file}")

if __name__ == "__main__":
    main()
