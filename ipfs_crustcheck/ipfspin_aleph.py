#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
import time
import signal
import os
from typing import List, Tuple

def parse_line(line: str) -> Tuple[str, str, int]:
    """
    解析格式为 "<FILE NAME> <FILE CID> <FILE SIZE IN BYTES>" 的行
    从右往左解析以处理文件名中可能包含的空格和特殊字符
    
    返回元组 (file_name, file_cid, file_size)
    """
    line = line.strip()
    
    # 从右往左，找到第一个连续的数字串（文件大小）
    match = re.search(r'(\d+)\s*$', line)
    if not match:
        raise ValueError(f"无效的行格式，无法找到文件大小: {line}")
    
    file_size = int(match.group(1))
    remain = line[:match.start()].strip()
    
    # 接着，找到CID（连续的字母数字字符串）
    match = re.search(r'([a-zA-Z0-9]+)\s*$', remain)
    if not match:
        raise ValueError(f"无效的行格式，无法找到CID: {remain}")
    
    file_cid = match.group(1)
    file_name = remain[:match.start()].strip()
    
    return file_name, file_cid, file_size

def pin_cid(cid: str, retries: int) -> bool:
    """
    使用 'aleph file pin --debug' 命令固定CID
    监控输出中的 "DEBUG:aleph_client.commands.files:Upload finished"
    看到此消息后等待2秒然后终止进程
    
    如果命令成功返回True，否则返回False
    """
    command = f"aleph file pin --debug {cid}"
    
    for attempt in range(retries + 1):
        print(f"尝试 {attempt + 1}/{retries + 1}: 运行命令: {command}")
        
        try:
            # 使用Popen来实时监控输出
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            upload_finished = False
            all_output = []
            
            # 实时读取输出
            while True:
                # 检查进程是否已经结束
                if process.poll() is not None:
                    # 进程已经结束，读取剩余输出
                    remaining_output = process.stdout.read()
                    if remaining_output:
                        all_output.append(remaining_output)
                        if "DEBUG:aleph_client.commands.files:Upload finished" in remaining_output:
                            upload_finished = True
                    break
                
                # 读取一行输出
                line = process.stdout.readline()
                if line:
                    all_output.append(line)
                    print(line.rstrip())  # 实时显示输出
                    
                    # 检查是否包含Upload finished消息
                    if "DEBUG:aleph_client.commands.files:Upload finished" in line:
                        upload_finished = True
                        print("检测到Upload finished消息，等待2秒后终止进程...")
                        
                        # 等待2秒，期间检查进程状态
                        start_time = time.time()
                        while time.time() - start_time < 2:
                            if process.poll() is not None:
                                print("进程在等待期间自然退出")
                                break
                            time.sleep(0.1)
                        
                        # 如果进程还在运行，终止它
                        if process.poll() is None:
                            print("终止进程...")
                            try:
                                if os.name == 'nt':  # Windows
                                    process.terminate()
                                else:  # Unix/Linux/macOS
                                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                                
                                # 等待进程终止
                                try:
                                    process.wait(timeout=5)
                                except subprocess.TimeoutExpired:
                                    print("进程未能在5秒内终止，强制杀死...")
                                    if os.name == 'nt':
                                        process.kill()
                                    else:
                                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                                        process.wait()
                            except Exception as e:
                                print(f"终止进程时出错: {e}")
                        break
                else:
                    # 没有更多输出，进程可能卡住了
                    time.sleep(0.1)
            
            # 检查结果
            return_code = process.returncode
            
            if upload_finished:
                print(f"成功固定 {cid}")
                return True
            elif return_code is not None and return_code != 0:
                print(f"命令失败，退出码 {return_code}")
                full_output = ''.join(all_output)
                print(f"完整输出:\n{full_output}")
                
                if attempt == retries:
                    print(f"在 {retries + 1} 次尝试后无法固定 {cid}")
                    return False
            else:
                print(f"未检测到Upload finished消息，认为失败")
                
                if attempt == retries:
                    print(f"在 {retries + 1} 次尝试后无法固定 {cid}")
                    return False
                    
        except Exception as e:
            print(f"发生异常: {str(e)}")
            
            if attempt == retries:
                print(f"在 {retries + 1} 次尝试后无法固定 {cid}")
                return False
    
    return False

def process_input(lines: List[str], retries: int) -> None:
    """
    处理每行输入，提取CID并固定它们
    """
    if not lines:
        print("没有提供输入行。退出。")
        return
    
    success_count = 0
    total_count = 0
    failed_cids = []
    
    for line_num, line in enumerate(lines, 1):
        if not line.strip():
            continue
        
        try:
            file_name, file_cid, file_size = parse_line(line)
            total_count += 1
            
            print(f"\n处理第 {line_num} 行: {file_name} (CID: {file_cid}, 大小: {file_size} 字节)")
            
            if pin_cid(file_cid, retries):
                success_count += 1
            else:
                failed_cids.append(file_cid)
        except ValueError as e:
            print(f"解析第 {line_num} 行时出错: {str(e)}")
            continue
    
    print("\n摘要:")
    print(f"- 总共处理的CID数: {total_count}")
    print(f"- 成功固定: {success_count}")
    print(f"- 失败: {total_count - success_count}")
    
    if failed_cids:
        print("\n失败的CID:")
        for cid in failed_cids:
            print(f"- {cid}")

def main():
    parser = argparse.ArgumentParser(description="使用aleph固定文件CID")
    parser.add_argument("-i", "--input", help="输入文件路径")
    parser.add_argument("--retries", type=int, default=3, help="失败固定的重试次数（默认: 3）")
    
    args = parser.parse_args()
    
    lines = []
    
    if args.input:
        try:
            with open(args.input, 'r') as f:
                lines = f.readlines()
            print(f"从文件读取了 {len(lines)} 行: {args.input}")
        except Exception as e:
            print(f"读取输入文件时出错: {str(e)}")
            sys.exit(1)
    else:
        print("请输入数据（格式: <文件名> <文件CID> <文件大小(字节)>，每行一条）:")
        print("输入完成后按 Ctrl+D (EOF)")
        
        lines = sys.stdin.readlines()
        print(f"从标准输入读取了 {len(lines)} 行")
    
    process_input(lines, args.retries)

if __name__ == "__main__":
    main()
