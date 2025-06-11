#!/usr/bin/env python3
"""
SurfShark Server Checker - Cross-platform script for Windows 10 and Debian 12
Checks SurfShark servers for HTTP 407 responses and sorts by ping latency
Version 2.2 - Added CN accessibility check
"""

import argparse
import sys
import socket
import subprocess
import platform
import time
import concurrent.futures
from datetime import datetime
from typing import List, Tuple, Optional
import re
import locale
import os

try:
    import requests
except ImportError:
    print("Error: requests library not found. Please install it using: pip3 install requests")
    sys.exit(1)

try:
    from requests.auth import HTTPProxyAuth
except ImportError:
    HTTPProxyAuth = None

class ServerChecker:
    def __init__(self, addr_prefix: str, start: int, end: int, username: str = "xxxxxx", password: str = "yyyyyy", real_ping: bool = False, cn_check: bool = False):
        self.addr_prefix = addr_prefix
        self.start = start
        self.end = end
        self.username = username
        self.password = password
        self.real_ping = real_ping
        self.cn_check = cn_check
        self.found_407_servers = []
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = f"avail-urls-{self.timestamp}.log"
        
        # Detect system encoding
        if platform.system().lower() == 'windows':
            # Get Windows console code page
            import ctypes
            kernel32 = ctypes.windll.kernel32
            self.console_cp = kernel32.GetConsoleCP()
            self.system_encoding = f'cp{self.console_cp}' if self.console_cp else 'gbk'
        else:
            self.system_encoding = locale.getpreferredencoding()
        
    def check_url(self, url: str) -> Optional[int]:
        """Check URL and return HTTP status code"""
        try:
            response = requests.get(url, timeout=5, allow_redirects=True)
            return response.status_code
        except requests.exceptions.RequestException:
            return None
    
    def get_ip_address(self, hostname: str) -> Optional[str]:
        """Resolve hostname to IP address"""
        try:
            # Extract hostname from URL
            host = hostname.replace("https://", "").replace("http://", "").split('/')[0]
            ip = socket.gethostbyname(host)
            return ip
        except socket.gaierror:
            return None
    
    def ping_host(self, hostname: str) -> Optional[float]:
        """Ping host and return average latency in ms"""
        try:
            # Extract hostname from URL
            host = hostname.replace("https://", "").replace("http://", "").split('/')[0]
            
            # Platform-specific ping command
            if platform.system().lower() == 'windows':
                # Set UTF-8 for Windows console
                cmd = ['cmd', '/c', 'chcp 65001 >nul 2>&1 && ping', '-n', '3', host]
                encoding = 'utf-8'
                
                # Try UTF-8 first, fallback to system encoding
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, 
                                          encoding='utf-8', shell=True)
                except UnicodeDecodeError:
                    # Fallback to system encoding (GBK for Chinese Windows)
                    cmd = ['ping', '-n', '3', host]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, 
                                          encoding=self.system_encoding)
            else:  # Linux/Unix
                cmd = ['ping', '-c', '3', '-W', '2', host]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                output = result.stdout
                
                # Parse average ping time
                if platform.system().lower() == 'windows':
                    # Try multiple patterns for different Windows language versions
                    patterns = [
                        # English patterns
                        r'Average = (\d+)ms',
                        r'Minimum = \d+ms, Maximum = \d+ms, Average = (\d+)ms',
                        # Chinese patterns
                        r'平均 = (\d+)ms',
                        r'最短 = \d+ms，最长 = \d+ms，平均 = (\d+)ms',
                        # Generic patterns
                        r'(?:平均|Average)\s*=\s*(\d+)\s*ms',
                    ]
                    
                    # Try to find average in summary
                    for pattern in patterns:
                        match = re.search(pattern, output, re.IGNORECASE)
                        if match:
                            return float(match.group(1))
                    
                    # Extract from individual ping lines
                    time_patterns = [
                        r'(?:时间|time)[=<]\s*(\d+)\s*ms',  # Chinese/English with = or <
                        r'time\s*=\s*(\d+)\s*ms',           # English
                        r'时间\s*=\s*(\d+)\s*ms',           # Chinese
                        r'TTL=\d+\s+(?:时间|time)[=<]\s*(\d+)\s*ms',  # With TTL
                        r':\s+(?:字节|bytes)=\d+\s+(?:时间|time)[=<]\s*(\d+)\s*ms',  # Full line
                    ]
                    
                    times = []
                    for pattern in time_patterns:
                        matches = re.findall(pattern, output, re.IGNORECASE)
                        times.extend([float(m) for m in matches if m.isdigit()])
                    
                    if times:
                        # Remove outliers if we have enough samples
                        if len(times) >= 3:
                            times_sorted = sorted(times)
                            # Remove highest value if it's significantly higher
                            if times_sorted[-1] > times_sorted[-2] * 1.5:
                                times = times_sorted[:-1]
                        return sum(times) / len(times) if times else None
                        
                else:  # Linux/Unix
                    # Linux ping output patterns
                    patterns = [
                        r'min/avg/max/(?:mdev|stddev)\s*=\s*[\d.]+/([\d.]+)/',
                        r'rtt\s+min/avg/max/mdev\s*=\s*[\d.]+/([\d.]+)/',
                        r'round-trip\s+min/avg/max/stddev\s*=\s*[\d.]+/([\d.]+)/',
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, output)
                        if match:
                            return float(match.group(1))
                    
                    # Fallback: extract individual times
                    time_pattern = r'time=([\d.]+)\s*ms'
                    times = re.findall(time_pattern, output)
                    if times:
                        times = [float(t) for t in times]
                        return sum(times) / len(times)
                    
            return None
            
        except subprocess.TimeoutExpired:
            return None
        except Exception as e:
            # Debug output - uncomment if needed
            # print(f"\nPing error for {hostname}: {type(e).__name__}: {e}")
            return None
    
    def extract_country_code(self, hostname: str) -> str:
        """Extract country code from hostname"""
        # Format: xx-xxx-vNNN.prod.surfshark.com
        parts = hostname.split('-')
        if len(parts) >= 2:
            return parts[0].upper()
        return "XX"
    
    def extract_server_name(self, url: str) -> str:
        """Extract server name from URL"""
        # Extract hostname from URL
        host = url.replace("https://", "").replace("http://", "").split('/')[0]
        # Remove .prod.surfshark.com
        server = host.replace(".prod.surfshark.com", "")
        return server
    
    def test_cn_accessibility(self, hostname: str) -> bool:
        """Test if proxy can access CN resources by checking Aliyun OSS"""
        try:
            # Extract hostname from URL if needed
            if hostname.startswith('http'):
                hostname = hostname.replace("https://", "").replace("http://", "").split('/')[0]
            
            # Setup proxy
            proxy_url = f"https://{self.username}:{self.password}@{hostname}:443"
            proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
            
            # Test URL - Aliyun OSS
            test_url = 'https://fhnfile.oss-cn-shenzhen.aliyuncs.com'
            
            # Make request through proxy
            response = requests.get(
                test_url,
                proxies=proxies,
                timeout=10,
                verify=False,  # Skip SSL verification for proxy
                allow_redirects=False
            )
            
            # Check if we got 403 Forbidden (expected response from Aliyun OSS)
            if response.status_code == 403:
                return True
            else:
                # Any other status code means the proxy doesn't work properly for CN
                return False
                
        except requests.exceptions.Timeout:
            # Timeout - proxy can't reach CN resources
            return False
        except requests.exceptions.ConnectionError:
            # TCP RST or connection error
            return False
        except Exception as e:
            # Any other error
            # Debug: uncomment to see errors
            # print(f"\nCN check error for {hostname}: {type(e).__name__}: {e}")
            return False
    
    def test_real_proxy_latency(self, hostname: str) -> Tuple[Optional[float], Optional[bool]]:
        """Test real proxy connection latency and optionally CN accessibility"""
        try:
            # Extract hostname from URL if needed
            if hostname.startswith('http'):
                hostname = hostname.replace("https://", "").replace("http://", "").split('/')[0]
            
            # Setup proxy
            proxy_url = f"https://{self.username}:{self.password}@{hostname}:443"
            proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
            
            # Test URL - Google's connectivity check endpoint
            test_url = 'http://www.gstatic.com/generate_204'
            
            # Measure connection time
            start_time = time.time()
            
            # Make request through proxy
            response = requests.get(
                test_url,
                proxies=proxies,
                timeout=10,
                verify=False,  # Skip SSL verification for proxy
                allow_redirects=False
            )
            
            end_time = time.time()
            
            # Check if we got the expected response
            if response.status_code == 204:
                latency = (end_time - start_time) * 1000  # Convert to milliseconds
                
                # Check CN accessibility if requested
                cn_accessible = None
                if self.cn_check:
                    cn_accessible = self.test_cn_accessibility(hostname)
                
                return latency, cn_accessible
            else:
                # Unexpected status code
                return None, None
                
        except requests.exceptions.ProxyError:
            # Proxy connection failed
            return None, None
        except requests.exceptions.Timeout:
            # Request timed out
            return None, None
        except Exception as e:
            # Other errors
            # Debug: uncomment to see errors
            # print(f"\nReal proxy test error for {hostname}: {type(e).__name__}: {e}")
            return None, None
    
    def run(self):
        """Main execution function"""
        print(f"开始检查 {self.addr_prefix} 从 {self.start:03d} 到 {self.end:03d} 的服务器...")
        print(f"查找返回码为 407 的 URL：")
        print(f"日志文件: {self.log_file}")
        print(f"系统编码: {self.system_encoding}")
        if self.real_ping:
            print(f"真实代理测试: 已启用")
            if self.cn_check:
                print(f"大陆可达性检查: 已启用")
        print("=" * 60)
        
        # Check all URLs
        for i in range(self.start, self.end + 1):
            num = f"{i:03d}"
            url = f"https://{self.addr_prefix}-v{num}.prod.surfshark.com"
            
            # Show progress
            if i % 10 == 0:
                print(f"\r正在检查: {i}/{self.end}", end='', flush=True)
            
            http_code = self.check_url(url)
            if http_code == 407:
                self.found_407_servers.append(url)
                print(f"\r{url} - HTTP 407")
        
        print(f"\r" + " " * 60 + "\r", end='')  # Clear progress line
        print("=" * 60)
        
        if not self.found_407_servers:
            print("未找到任何返回 407 的服务器")
            return
        
        print(f"找到 {len(self.found_407_servers)} 个返回 407 的 URL")
        print("正在进行 DNS 解析和 Ping 测试...")
        print("注意: Ping 测试可能需要一些时间，请耐心等待...")
        
        # Get ping latencies for all servers
        server_info = []
        failed_pings = 0
        
        # Use ThreadPoolExecutor with limited workers to avoid overwhelming the system
        max_workers = min(10, len(self.found_407_servers))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(self.ping_host, url): url 
                           for url in self.found_407_servers}
            
            completed = 0
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                completed += 1
                
                try:
                    latency = future.result()
                    ip = self.get_ip_address(url)
                    
                    if latency is None:
                        failed_pings += 1
                    
                    server_info.append((url, ip, latency, None, None))  # Added None for real_latency and cn_accessible
                    
                    # Show progress with more detail
                    status = f"✓ {latency:.1f}ms" if latency else "✗ N/A"
                    print(f"\r已测试: {completed}/{len(self.found_407_servers)} - 最新: {url.split('/')[-1].split('.')[0]} {status}", 
                          end='', flush=True)
                    
                except Exception as e:
                    server_info.append((url, None, None, None, None))
                    failed_pings += 1
                    print(f"\r已测试: {completed}/{len(self.found_407_servers)} - 错误: {url.split('/')[-1].split('.')[0]}", 
                          end='', flush=True)
        
        print(f"\r" + " " * 100 + "\r", end='')  # Clear progress line
        
        # Sort by ping latency (None values at the end)
        server_info.sort(key=lambda x: (x[2] is None, x[2] if x[2] is not None else float('inf')))
        
        # Real proxy testing if enabled
        if self.real_ping and self.username != "xxxxxx" and self.password != "yyyyyy":
            print("\n" + "=" * 60)
            print("开始真实代理延迟测试...")
            if self.cn_check:
                print("同时进行大陆可达性检查...")
            
            # Take top 20 servers based on ping latency
            top_servers = [s for s in server_info if s[2] is not None][:20]
            
            if not top_servers:
                print("警告: 没有可用的服务器进行真实代理测试")
            else:
                print(f"将对延迟最低的 {len(top_servers)} 个服务器进行真实代理测试")
                print("每组并发 3 个连接，避免超出连接限制...")
                
                # Test in groups of 3 to avoid connection limits
                for i in range(0, len(top_servers), 3):
                    group = top_servers[i:i+3]
                    group_num = i // 3 + 1
                    total_groups = (len(top_servers) + 2) // 3
                    
                    print(f"\n测试第 {group_num}/{total_groups} 组:")
                    
                    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                        futures = {}
                        for url, ip, ping_latency, _, _ in group:
                            hostname = url.replace("https://", "").replace("http://", "").split('/')[0]
                            future = executor.submit(self.test_real_proxy_latency, hostname)
                            futures[future] = (url, ip, ping_latency)
                        
                        for future in concurrent.futures.as_completed(futures):
                            url, ip, ping_latency = futures[future]
                            try:
                                real_latency, cn_accessible = future.result()
                                
                                # Update server_info with real latency and cn accessibility
                                for j, (s_url, s_ip, s_ping, _, _) in enumerate(server_info):
                                    if s_url == url:
                                        server_info[j] = (s_url, s_ip, s_ping, real_latency, cn_accessible)
                                        break
                                
                                # Show result
                                server_name = self.extract_server_name(url)
                                if real_latency:
                                    status = f"Ping={ping_latency:.1f}ms, 真实延迟={real_latency:.1f}ms"
                                    if self.cn_check:
                                        cn_status = "大陆可达 ✓" if cn_accessible else "大陆不可达 ✗"
                                        status += f", {cn_status}"
                                    print(f"  {server_name}: {status}")
                                else:
                                    print(f"  {server_name}: Ping={ping_latency:.1f}ms, 真实延迟=失败 ✗")
                                    
                            except Exception as e:
                                print(f"  {self.extract_server_name(url)}: 测试失败 - {type(e).__name__}")
                    
                    # Small delay between groups
                    if i + 3 < len(top_servers):
                        time.sleep(1)
                
                # Filter servers based on CN accessibility if cn_check is enabled
                if self.cn_check:
                    original_count = len(server_info)
                    # Keep servers that either weren't tested (not in top 20) or passed CN check
                    server_info = [s for s in server_info if s[4] is None or s[4] is True]
                    filtered_count = original_count - len(server_info)
                    if filtered_count > 0:
                        print(f"\n已过滤掉 {filtered_count} 个大陆不可达的服务器")
                
                # Re-sort by real latency if available, otherwise by ping latency
                server_info.sort(key=lambda x: (
                    x[3] is None,  # Real latency is None
                    x[3] if x[3] is not None else (x[2] if x[2] is not None else float('inf'))
                ))
        
        # Show summary
        successful_pings = len([s for s in server_info if s[2] is not None])
        print(f"\n" + "=" * 60)
        print(f"Ping 测试完成: 成功 {successful_pings}/{len(server_info)}")
        
        if successful_pings > 0:
            latencies = [s[2] for s in server_info if s[2] is not None]
            print(f"Ping 延迟范围: {min(latencies):.1f}ms - {max(latencies):.1f}ms")
            print(f"Ping 平均延迟: {sum(latencies)/len(latencies):.1f}ms")
        
        if self.real_ping and self.username != "xxxxxx" and self.password != "yyyyyy":
            real_latencies = [s[3] for s in server_info if s[3] is not None]
            if real_latencies:
                print(f"\n真实代理延迟统计:")
                print(f"  成功测试: {len(real_latencies)} 个服务器")
                print(f"  延迟范围: {min(real_latencies):.1f}ms - {max(real_latencies):.1f}ms")
                print(f"  平均延迟: {sum(real_latencies)/len(real_latencies):.1f}ms")
                
                if self.cn_check:
                    cn_accessible_count = len([s for s in server_info if s[4] is True])
                    print(f"\n大陆可达性统计:")
                    print(f"  大陆可达服务器: {cn_accessible_count} 个")
        
        # Write to log file
        self.write_log(server_info)
        
        print("=" * 60)
        print(f"检查完成！结果已保存到: {self.log_file}")
        
        # Show top 5 servers
        if self.real_ping and any(s[3] is not None for s in server_info):
            print("\n真实延迟最低的前 5 个服务器:")
            count = 0
            for url, ip, ping_latency, real_latency, cn_accessible in server_info:
                if real_latency is not None and count < 5:
                    count += 1
                    server_name = self.extract_server_name(url)
                    status = f"Ping: {ping_latency:.1f}ms, 真实: {real_latency:.1f}ms"
                    if self.cn_check and cn_accessible is not None:
                        status += f", {'大陆可达' if cn_accessible else '大陆不可达'}"
                    print(f"  {count}. {server_name} - {status}")
        elif successful_pings > 0:
            print("\nPing 延迟最低的前 5 个服务器:")
            for i, (url, ip, latency, _, _) in enumerate(server_info[:5]):
                if latency is not None:
                    server_name = self.extract_server_name(url)
                    print(f"  {i+1}. {server_name} - {latency:.1f}ms")
    
    def write_log(self, server_info: List[Tuple[str, Optional[str], Optional[float], Optional[float], Optional[bool]]]):
        """Write results to log file"""
        with open(self.log_file, 'w', encoding='utf-8') as f:
            # Header
            f.write(f"# 检查时间: {datetime.now()}\n")
            f.write(f"# 地址前缀: {self.addr_prefix}\n")
            f.write(f"# 数字范围: {self.start:03d}-{self.end:03d}\n")
            f.write(f"# 系统编码: {self.system_encoding}\n")
            if self.real_ping:
                f.write(f"# 真实代理测试: 已启用\n")
                if self.cn_check:
                    f.write(f"# 大陆可达性检查: 已启用\n")
            f.write(f"# 返回 HTTP 407 的 URL 列表（按延迟排序）：\n")
            f.write("#\n")
            
            # Statistics
            successful_pings = [s for s in server_info if s[2] is not None]
            if successful_pings:
                latencies = [s[2] for s in successful_pings]
                f.write(f"# Ping 统计信息:\n")
                f.write(f"#   总服务器数: {len(server_info)}\n")
                f.write(f"#   Ping 成功: {len(successful_pings)}\n")
                f.write(f"#   最低延迟: {min(latencies):.1f}ms\n")
                f.write(f"#   最高延迟: {max(latencies):.1f}ms\n")
                f.write(f"#   平均延迟: {sum(latencies)/len(latencies):.1f}ms\n")
                
                if self.real_ping:
                    real_latencies = [s[3] for s in server_info if s[3] is not None]
                    if real_latencies:
                        f.write(f"#\n")
                        f.write(f"# 真实代理延迟统计:\n")
                        f.write(f"#   测试成功: {len(real_latencies)}\n")
                        f.write(f"#   最低延迟: {min(real_latencies):.1f}ms\n")
                        f.write(f"#   最高延迟: {max(real_latencies):.1f}ms\n")
                        f.write(f"#   平均延迟: {sum(real_latencies)/len(real_latencies):.1f}ms\n")
                        
                        if self.cn_check:
                            cn_accessible = [s for s in server_info if s[4] is True]
                            f.write(f"#\n")
                            f.write(f"# 大陆可达性统计:\n")
                            f.write(f"#   测试服务器数: {len([s for s in server_info if s[4] is not None])}\n")
                            f.write(f"#   大陆可达: {len(cn_accessible)}\n")
                
                f.write("#\n")
            
            # URL list with ping info
            f.write("# URL 列表（含 IP 和延迟信息）：\n")
            for url, ip, ping_latency, real_latency, cn_accessible in server_info:
                ip_str = ip if ip else "N/A"
                ping_str = f"{ping_latency:.1f}ms" if ping_latency else "N/A"
                
                info_line = f"# {url} - IP: {ip_str} - Ping: {ping_str}"
                
                if self.real_ping and real_latency is not None:
                    info_line += f" - 真实延迟: {real_latency:.1f}ms"
                
                if self.cn_check and cn_accessible is not None:
                    info_line += f" - 大陆可达: {'是' if cn_accessible else '否'}"
                
                f.write(info_line + "\n")
            
            f.write("\n")
            
            # Proxies configuration in YAML format
            f.write("# Proxies 配置（YAML格式）：\n")
            f.write("proxies:\n")
            
            for url, ip, ping_latency, real_latency, cn_accessible in server_info:
                # Extract server name
                server_name = self.extract_server_name(url)
                country_code = self.extract_country_code(server_name)
                
                # Format server name for display
                display_name = f"[{country_code}] SurfSharkVPN {server_name.upper()}"
                hostname = url.replace("https://", "").replace("http://", "").split('/')[0]
                
                # Add latency info to name if available
                if self.real_ping and real_latency is not None:
                    display_name = f"{display_name} (真实:{real_latency:.0f}ms"
                    if self.cn_check and cn_accessible is not None:
                        display_name += f",{'CN' if cn_accessible else 'NC'}"
                    display_name += ")"
                elif ping_latency is not None:
                    display_name = f"{display_name} ({ping_latency:.0f}ms)"
                
                # Write proxy configuration
                f.write(f'  - {{name: "{display_name}", '
                       f'server: {hostname}, '
                       f'port: 443, '
                       f'type: http, '
                       f'username: {self.username}, '
                       f'password: {self.password}, '
                       f'tls: true, '
                       f'udp: false}}\n')

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='SurfShark Server Checker - 检查 SurfShark 服务器并按 Ping 延迟排序',
        usage='%(prog)s -addr <地址前缀> -r <起始数字>-<结束数字> [--user <用户名>] [--pass <密码>] [--real-ping] [--cn-check]',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s -addr hk-hkg -r 001-120
  %(prog)s -addr us-nyc -r 100-200 --user myuser --pass mypass
  %(prog)s -addr fr-par -r 001-100 --user myuser --pass mypass --real-ping
  %(prog)s -addr sg-sng -r 001-100 --user myuser --pass mypass --real-ping --cn-check
  
支持的功能:
  - 自动检测返回 HTTP 407 的服务器
  - DNS 解析获取 IP 地址
  - Ping 测试并按延迟排序
  - 生成 YAML 格式的代理配置
  - 支持中文和英文 Windows 系统
  - 真实代理连接延迟测试（需要有效的用户名和密码）
  - 大陆可达性检查（--cn-check，仅在 --real-ping 时有效）
        """
    )
    
    parser.add_argument('-addr', required=True, 
                       help='地址前缀 (例如: hk-hkg, us-nyc, uk-lon)')
    parser.add_argument('-r', required=True,
                       help='数字范围 (例如: 001-120)')
    parser.add_argument('--user', default='xxxxxx',
                       help='代理用户名 (默认: xxxxxx)')
    parser.add_argument('--pass', dest='password', default='yyyyyy',
                       help='代理密码 (默认: yyyyyy)')
    parser.add_argument('--real-ping', action='store_true',
                       help='启用真实代理连接测试（需要有效的用户名和密码）')
    parser.add_argument('--cn-check', action='store_true',
                       help='检查代理服务器的大陆可达性（仅在 --real-ping 时有效）')
    
    args = parser.parse_args()
    
    # Validate real-ping requirements
    if args.real_ping and (args.user == 'xxxxxx' or args.password == 'yyyyyy'):
        print("错误: --real-ping 需要提供有效的用户名和密码")
        print("请使用 --user 和 --pass 参数提供您的 SurfShark 凭据")
        sys.exit(1)
    
    # Validate cn-check requirements
    if args.cn_check and not args.real_ping:
        print("错误: --cn-check 仅在指定 --real-ping 时有效")
        print("请同时使用 --real-ping 和 --cn-check")
        sys.exit(1)
    
    # Parse range with better error handling
    try:
        # Use regex to properly parse the range
        match = re.match(r'^(\d+)-(\d+)$', args.r)
        if not match:
            raise ValueError("范围格式必须是 '数字-数字'")
        
        start = int(match.group(1))
        end = int(match.group(2))
        
        if start > end:
            print("错误: 起始数字不能大于结束数字")
            sys.exit(1)
            
        if end - start > 500:
            print(f"警告: 范围较大 ({end - start + 1} 个服务器)，测试可能需要较长时间")
            if args.real_ping:
                print("注意: 启用了真实代理测试，将额外增加测试时间")
                if args.cn_check:
                    print("注意: 启用了大陆可达性检查，将进一步增加测试时间")
            response = input("是否继续? (y/n): ")
            if response.lower() != 'y':
                print("操作已取消")
                sys.exit(0)
                
    except ValueError as e:
        print(f"错误: 无效的数字范围格式 - {str(e)}")
        print("正确格式示例: 001-120")
        sys.exit(1)
    
    return args.addr, start, end, args.user, args.password, args.real_ping, args.cn_check

def main():
    """Main entry point"""
    # Set console encoding for Windows
    if platform.system().lower() == 'windows':
        # Try to set UTF-8 mode for better compatibility
        try:
            # Set console code page to UTF-8
            os.system('chcp 65001 >nul 2>&1')
            # Set Python's stdout encoding
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    
    # Suppress SSL warnings for proxy connections
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    try:
        # Parse all arguments including username, password, real_ping, and cn_check
        addr_prefix, start, end, username, password, real_ping, cn_check = parse_arguments()
        
        print(f"\nSurfShark Server Checker v2.2")
        print(f"Python {sys.version.split()[0]} on {platform.system()} {platform.release()}")
        if real_ping:
            print("模式: 真实代理延迟测试")
            if cn_check:
                print("大陆可达性检查: 已启用")
        print()
        
        # Create and run checker
        checker = ServerChecker(addr_prefix, start, end, username, password, real_ping, cn_check)
        checker.run()
        
    except KeyboardInterrupt:
        print("\n\n操作被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
