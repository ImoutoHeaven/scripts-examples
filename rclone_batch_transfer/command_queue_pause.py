#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time
import threading
import queue

# Global state for pause/resume functionality
execution_paused = False
input_queue = queue.Queue()
current_command_index = 0

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

def input_listener():
    """Thread function to listen for pause/resume commands"""
    global execution_paused
    
    while True:
        try:
            user_input = input().strip().lower()
            input_queue.put(user_input)
            
            if user_input == "pause":
                execution_paused = True
                print("\n[Command execution paused. Type 'resume' to restart the current command]")
            elif user_input == "resume":
                execution_paused = False
                print("\n[Restarting command...]")
            elif user_input == "exit":
                print("\n[Exiting program...]")
                sys.exit(0)
        except EOFError:
            break
        except Exception as e:
            print(f"Error in input listener: {e}")

def execute_command(cmd, total_retries):
    """执行命令，支持直接命令并提供重试机制"""
    global execution_paused
    retry_count = 0
    current_process = None
    user_terminated = False  # Flag to track if the process was terminated by user
    
    while retry_count <= total_retries:
        if retry_count > 0:
            print(f"Retrying '{cmd}' (Attempt {retry_count}/{total_retries})...")
        
        # Reset pause state before starting a new command
        execution_paused = False
        user_terminated = False  # Reset the user termination flag
        
        try:
            # Use subprocess.Popen to capture output in real-time
            current_process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,  # Line buffered
            )
            
            # Print output in real-time with unicode error handling
            while True:
                # Check for pause command
                if execution_paused:
                    print("\n[Command terminated due to pause]")
                    if current_process:
                        try:
                            # Kill the process
                            current_process.terminate()
                            time.sleep(0.5)
                            if current_process.poll() is None:  # If still running
                                current_process.kill()  # Force kill
                        except Exception as e:
                            print(f"Error terminating process: {e}")
                    
                    # Set the user termination flag
                    user_terminated = True
                    
                    # Wait for resume command
                    while execution_paused:
                        time.sleep(0.5)
                    
                    print("[Restarting command from beginning...]")
                    # Break the inner loop to restart the command
                    break
                
                # Try to read a line (non-blocking)
                line = current_process.stdout.readline()
                if not line and current_process.poll() is not None:
                    # Process has exited and no more output
                    break
                
                if line:
                    try:
                        decoded_line = line.decode('utf-8', errors='replace')
                        print(decoded_line, end='')
                        sys.stdout.flush()  # Ensure output is displayed immediately
                    except Exception as e:
                        print(f"Error decoding output: {e}", file=sys.stderr)
                else:
                    # No output but process still running, give a small pause
                    time.sleep(0.1)
            
            # If we broke out due to pause, continue to next iteration to restart
            if user_terminated:
                continue
                
            # Close the stdout to avoid resource leaks
            if current_process and current_process.stdout:
                current_process.stdout.close()
            
            # If we got here normally, get the return code
            return_code = current_process.poll()
            
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
    global execution_paused, current_command_index
    
    try:
        args = parse_args()
        commands = get_commands()
        
        if not commands:
            print("No valid commands entered. Exiting.")
            sys.exit(1)
        
        print(f"\nExecuting {len(commands)} commands with {args.total_retries} retries for failures...")
        print("You can type 'pause' to pause/kill the current command.")
        print("Type 'resume' to restart the current command from the beginning and continue execution.")
        print("Type 'exit' to terminate the program completely.\n")
        
        # Start input listener thread
        input_thread = threading.Thread(target=input_listener, daemon=True)
        input_thread.start()
        
        success_count = 0
        current_command_index = 0
        
        while current_command_index < len(commands):
            # Process any pending input
            while not input_queue.empty():
                cmd = input_queue.get()
                # Commands are handled in the input_listener thread
            
            cmd = commands[current_command_index]
            print(f"\nExecuting command {current_command_index+1}/{len(commands)}: {cmd}")
            
            if execute_command(cmd, args.total_retries):
                success_count += 1
            else:
                print(f"Command '{cmd}' failed after {args.total_retries} retries. Moving to next command.")
            
            current_command_index += 1
        
        print(f"\nExecution complete. {success_count}/{len(commands)} commands succeeded.")
    except KeyboardInterrupt:
        print("\nExecution interrupted by user. Exiting.")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
