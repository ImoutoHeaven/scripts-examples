#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time

def parse_args():
    parser = argparse.ArgumentParser(description='Execute commands with retries.')
    parser.add_argument('--total-retries', type=int, default=3, help='Number of retries for failed commands. 0 means no retries.')
    return parser.parse_args()

def get_commands():
    print("Enter commands (one per line). Press Enter twice to finish:")
    commands = []
    while True:
        try:
            cmd = input().strip()
            if not cmd:  # Empty line, break the loop
                break
            commands.append(cmd)
        except KeyboardInterrupt:
            print("\nInput interrupted. Stopping command collection.")
            break
        except EOFError:
            print("\nEnd of input reached.")
            break
    return commands

def execute_command(cmd, total_retries):
    """执行命令，支持直接命令并提供重试机制"""
    retry_count = 0
    
    while retry_count <= total_retries:
        if retry_count > 0:
            print(f"Retrying '{cmd}' (Attempt {retry_count}/{total_retries})...")
        
        try:
            # Use subprocess.Popen to capture output in real-time
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,  # Line buffered
            )
            
            # Print output in real-time with unicode error handling
            for line in iter(process.stdout.readline, b''):
                try:
                    decoded_line = line.decode('utf-8', errors='replace')
                    print(decoded_line, end='')
                    sys.stdout.flush()  # Ensure output is displayed immediately
                except Exception as e:
                    print(f"Error decoding output: {e}", file=sys.stderr)
            
            # Close the stdout to avoid resource leaks
            process.stdout.close()
            
            # Wait for the process to complete
            return_code = process.wait()
            
            if return_code == 0:
                print(f"Command '{cmd}' executed successfully with error code: 0")
                return True
            else:
                print(f"Command '{cmd}' failed with error code: {return_code}")
                retry_count += 1
        except Exception as e:
            print(f"Error executing command '{cmd}': {e}")
            retry_count += 1
    
    return False

def main():
    try:
        args = parse_args()
        commands = get_commands()
        
        if not commands:
            print("No valid commands entered. Exiting.")
            sys.exit(1)
        
        print(f"\nExecuting {len(commands)} commands with {args.total_retries} retries for failures...\n")
        
        success_count = 0
        for i, cmd in enumerate(commands):
            print(f"\nExecuting command {i+1}/{len(commands)}: {cmd}")
            if execute_command(cmd, args.total_retries):
                success_count += 1
            else:
                print(f"Command '{cmd}' failed after {args.total_retries} retries. Moving to next command.")
        
        print(f"\nExecution complete. {success_count}/{len(commands)} commands succeeded.")
    except KeyboardInterrupt:
        print("\nExecution interrupted by user. Exiting.")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
