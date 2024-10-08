import argparse
import subprocess
import time
import sys
import signal

def parse_time(time_str):
    unit = time_str[-1]
    value = int(time_str[:-1])
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
        raise ValueError("Invalid time unit. Use s, m, h, d, or w.")

def execute_command(cmd, low_level_retries):
    for attempt in range(1, low_level_retries + 1):
        print(f"Attempt {attempt}: {cmd}")
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output, error = process.communicate()
        print(output)
        print(error, file=sys.stderr)
        
        if "error" not in output.lower() and "error" not in error.lower():
            return True
        else:
            print(f"Command execution failed, error detected.")
    
    print(f"Command failed after {low_level_retries} attempts.")
    return False

def handle_sigint(signum, frame):
    print("\nCtrl+C detected, forcefully exiting the script.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Execute commands with retries and cooldown.")
    parser.add_argument("--low-level-retries", type=int, default=30, help="Number of retries for each command on error.")
    parser.add_argument("--retries", default="unless-stopped", help="Number of script execution cycles or 'unless-stopped'.")
    parser.add_argument("--cooldown", default="1h", help="Cooldown time between cycles (e.g., 30s, 5m, 2h, 1d, 1w).")
    args = parser.parse_args()

    low_level_retries = args.low_level_retries
    retries = args.retries
    cooldown = parse_time(args.cooldown)

    print("Enter the commands to execute, one per line. Press Ctrl+D when finished:")
    commands = sys.stdin.read().splitlines()

    signal.signal(signal.SIGINT, handle_sigint)

    cycle = 1
    while True:
        print(f"Executing cycle {cycle}")
        failed_commands = []

        for cmd in commands:
            if not execute_command(cmd, low_level_retries):
                failed_commands.append(cmd)

        if failed_commands:
            print("Retrying failed commands...")
            for failed_cmd in failed_commands:
                if not execute_command(failed_cmd, low_level_retries):
                    print(f"Skipping command: {failed_cmd}")

        if not failed_commands:
            print("All commands executed successfully.")
            break

        if retries != "unless-stopped" and cycle >= int(retries):
            print(f"Reached maximum number of retries ({retries}).")
            break

        print(f"Waiting for {cooldown} seconds...")
        time.sleep(cooldown)
        cycle += 1

    print("All tasks completed")

if __name__ == "__main__":
    main()
