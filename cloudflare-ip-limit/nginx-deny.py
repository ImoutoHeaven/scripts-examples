#!/usr/bin/env python3
import re
import time
import subprocess
import ipaddress
import os
import signal
import logging
import argparse
import glob
from collections import defaultdict
from datetime import datetime, timedelta

# 解析命令行参数
parser = argparse.ArgumentParser(description='Nginx日志监控与IP封禁工具')
parser.add_argument('--debug', action='store_true', help='启用调试模式，输出更详细的IP计数统计和封禁判断信息')
parser.add_argument('--log-dir', default='/var/log/nginx', help='日志文件目录路径')
parser.add_argument('--filter', default='/api/fs/link', help='请求路径过滤模式')
parser.add_argument('--ip-header', default='CF-CONNECTING-IP', 
                    help='包含真实IP的HTTP头名称(如CF-CONNECTING-IP, X-REAL-IP, X-FORWARDED-FOR等)')
parser.add_argument('--threshold', type=int, default=50, help='10秒内请求数阈值，超过此值将被封禁')
parser.add_argument('--time-window', type=int, default=10, help='检测时间窗口（秒）')
parser.add_argument('--block-duration', type=int, default=1200, help='封禁持续时间（秒）')
parser.add_argument('--http-conf', default='/etc/nginx/limit-http.conf', help='HTTP块封禁配置文件路径')
parser.add_argument('--location-conf', default='/etc/nginx/limit-location.conf', help='Location块封禁配置文件路径')
args = parser.parse_args()

# 配置参数
LOG_DIR = args.log_dir
HTTP_CONF_FILE = args.http_conf
LOCATION_CONF_FILE = args.location_conf
REQUEST_THRESHOLD = args.threshold  # 时间窗口内超过阈值的请求数将被封禁
TIME_WINDOW = args.time_window  # 时间窗口（秒）
BLOCK_DURATION = args.block_duration  # 封禁持续时间（秒）
CHECK_INTERVAL = 5  # 检查过期封禁的间隔（秒）
FILTER_PATTERN = args.filter  # 只监控包含此模式的请求
MIN_RELOAD_INTERVAL = 300  # 最小重载Nginx间隔（秒）
REAL_IP_HEADER = args.ip_header  # 真实IP的HTTP头

# 配置日志
if args.debug:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=LOG_LEVEL,
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Nginx日志解析正则表达式
LOG_PATTERN = r'^(\d+\.\d+\.\d+\.\d+|[0-9a-fA-F:]+) - - \[([^\]]+)\] "([^"]*)" ([^ ]+) (\d+) "([^"]*)" "([^"]*)"'

# 脚本说明信息
def print_usage_info():
    logging.info("=== Nginx IP封禁监控器 ===")
    logging.info(f"配置文件:")
    logging.info(f"  - HTTP块配置: {HTTP_CONF_FILE} (包含map指令，请放在http块中)")
    logging.info(f"  - Location块配置: {LOCATION_CONF_FILE} (包含if条件，请放在location块中)")
    logging.info(f"监控设置:")
    logging.info(f"  - 使用的IP头: {REAL_IP_HEADER}")
    logging.info(f"  - 监控路径: 包含 {FILTER_PATTERN} 的请求")
    logging.info(f"  - 封禁阈值: {REQUEST_THRESHOLD}个请求/{TIME_WINDOW}秒")
    logging.info(f"  - 封禁时长: {BLOCK_DURATION}秒")
    if args.debug:
        logging.info(f"调试模式已启用 - 将显示详细的IP请求统计")
    logging.info("=" * 30)

# 将IPv6地址转换为/64子网
def ipv6_to_subnet(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
        if isinstance(ip, ipaddress.IPv6Address):
            network = ipaddress.IPv6Network(f"{ip}/64", strict=False)
            return str(network)
        return ip_str
    except:
        return ip_str

# 转义IPv6地址中的特殊字符，使其在Nginx正则表达式中安全
def escape_ip_for_regex(ip_str):
    if ':' in ip_str:  # IPv6地址
        # 转义冒号，因为在正则表达式中有特殊含义
        if '/' in ip_str:  # CIDR格式
            ip_part = ip_str.split('/')[0]
            escaped = ip_part.replace(':', '\\:')
            return escaped
        else:
            return ip_str.replace(':', '\\:')
    return ip_str  # IPv4地址，无需转义

# 从日志文件名提取站点名称
def extract_site_name(log_file):
    # 从日志文件路径提取站点名称，例如从 "/var/log/nginx/example.com.log" 提取 "example.com"
    filename = os.path.basename(log_file)
    # 尝试匹配常见的日志文件命名模式
    site_match = re.match(r'([^.]+\.[^.]+)\.(?:access\.)?log', filename)
    if site_match:
        return site_match.group(1)
    # 如果无法提取，使用文件名作为站点标识
    return filename

# 获取目录中的所有日志文件
def get_log_files(log_dir):
    log_files = {}
    for log_file in glob.glob(os.path.join(log_dir, "*.log")):
        if not log_file.endswith(('.1', '.2', '.3', '.4', '.5', '.gz', '.zip')):
            # 获取文件大小作为起始位置
            try:
                file_size = os.path.getsize(log_file)
                log_files[log_file] = file_size
                if args.debug:
                    logging.debug(f"添加日志文件监控: {log_file} (起始位置: {file_size})")
            except:
                logging.warning(f"无法获取文件大小: {log_file}")
    
    logging.info(f"监控 {len(log_files)} 个日志文件")
    return log_files

# 辅助函数：将HTTP头名称转换为Nginx变量名
def header_to_nginx_var(header_name):
    # Nginx变量命名规则：小写 + 破折号转下划线 + 前缀http_
    var_name = header_name.lower().replace('-', '_')
    return f"http_{var_name}"

# 保存IP封禁列表（双文件版本）
def save_ban_list(ban_dict):
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        real_ip_var = header_to_nginx_var(REAL_IP_HEADER)

        # 1. 创建HTTP块配置文件（使用map指令）
        http_config = f"""# 自动生成的IP封禁配置（HTTP块） - 请勿手动编辑
# 最后更新: {current_time}
# 使用的真实IP头: {REAL_IP_HEADER} (变量: ${real_ip_var})
# 总封禁IP数: {len(ban_dict)}

# 检查IP头是否存在
map ${real_ip_var} $has_real_ip {{
    ""      0;  # 头不存在，跳过封禁检查
    default 1;  # 头存在，进行封禁检查
}}

# IP封禁映射表 - 仅当$has_real_ip=1时有效
map ${real_ip_var} $ip_is_banned {{
    default 0;
"""

        # IPv4 地址直接添加到映射
        ipv4_bans = [ip for ip in ban_dict.keys() if ':' not in ip]
        for ip in sorted(ipv4_bans):
            expiry = ban_dict[ip].strftime('%Y-%m-%d %H:%M:%S')
            http_config += f'    # 封禁到: {expiry}\n'
            http_config += f'    "{ip}" 1;\n'
        
        # IPv6 地址/64子网匹配，作为精确匹配添加到映射
        ipv6_bans = [ip for ip in ban_dict.keys() if ':' in ip]
        for ip in sorted(ipv6_bans):
            expiry = ban_dict[ip].strftime('%Y-%m-%d %H:%M:%S')
            http_config += f'    # 封禁到: {expiry}\n'
            
            # 处理CIDR格式
            if '/' in ip:
                # 添加IPv6子网CIDR作为完整匹配，避免正则表达式问题
                http_config += f'    "{ip}" 1; # IPv6子网\n'
            else:
                http_config += f'    "{ip}" 1;\n'
        
        http_config += "}\n"

        # 组合两个条件：IP头存在且IP被封禁
        http_config += """
# 最终封禁决定 - 只有当IP头存在且IP在封禁列表中时才封禁
map $has_real_ip $is_banned_ip {
    0       0;  # IP头不存在，强制不封禁
    1       $ip_is_banned;  # IP头存在，使用封禁结果
}
"""

        # 2. 创建Location块配置文件（使用if条件）
        location_config = f"""# 自动生成的IP封禁配置（Location块） - 请勿手动编辑
# 最后更新: {current_time}
# 使用的真实IP头: {REAL_IP_HEADER}
# 总封禁IP数: {len(ban_dict)}

# 应用封禁规则
if ($is_banned_ip = 1) {{
    return 429;
}}
"""

        # 写入文件
        with open(HTTP_CONF_FILE, 'w') as f:
            f.write(http_config)
        
        with open(LOCATION_CONF_FILE, 'w') as f:
            f.write(location_config)
        
        logging.info(f"已更新HTTP块配置文件: {HTTP_CONF_FILE}")
        logging.info(f"已更新Location块配置文件: {LOCATION_CONF_FILE}")
        logging.info(f"总封禁IP数: {len(ban_dict)}")
        return True
    except Exception as e:
        logging.error(f"保存封禁列表时出错: {e}")
        return False

# 加载现有的IP封禁列表（从HTTP配置文件）
def load_ban_list():
    ban_dict = {}
    try:
        # 尝试从HTTP配置文件中读取现有封禁
        with open(HTTP_CONF_FILE, 'r') as f:
            content = f.read()
            
            # 检查配置中使用的IP头是否与当前设置匹配
            header_pattern = r'# 使用的真实IP头: (.+) \(变量:'
            header_match = re.search(header_pattern, content)
            if header_match and header_match.group(1) != REAL_IP_HEADER:
                logging.warning(f"配置文件中的IP头 ({header_match.group(1)}) 与当前设置 ({REAL_IP_HEADER}) 不匹配")
                logging.warning("将重新创建配置文件")
                return {}
            
            # 查找所有封禁IP及其过期时间 - 精确匹配的IPv4/IPv6
            pattern = r'#\s+封禁到:\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"\s*([0-9a-fA-F:.]+)\s*"\s+1;'
            matches = re.finditer(pattern, content)
            
            for match in matches:
                expiry_str = match.group(1)
                ip = match.group(2)
                try:
                    expiry = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
                    ban_dict[ip] = expiry
                    if args.debug:
                        logging.debug(f"加载已封禁IP: {ip}, 到期时间: {expiry_str}")
                except:
                    pass
            
            # 查找IPv6子网（CIDR格式）
            pattern_ipv6_cidr = r'#\s+封禁到:\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"\s*([0-9a-fA-F:]+/\d+)\s*"\s+1;\s+#\s+IPv6子网'
            matches = re.finditer(pattern_ipv6_cidr, content)
            
            for match in matches:
                expiry_str = match.group(1)
                cidr = match.group(2)
                try:
                    expiry = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
                    ban_dict[cidr] = expiry
                    if args.debug:
                        logging.debug(f"加载已封禁IPv6子网: {cidr}, 到期时间: {expiry_str}")
                except:
                    pass
                    
    except FileNotFoundError:
        # 如果文件不存在则创建空的封禁列表
        save_ban_list({})
    
    logging.info(f"已加载 {len(ban_dict)} 个现有封禁IP")
    return ban_dict

# 重新加载Nginx配置
def reload_nginx(last_reload_time):
    current_time = time.time()
    
    # 检查是否符合最小重载间隔
    if current_time - last_reload_time < MIN_RELOAD_INTERVAL:
        time_left = int(MIN_RELOAD_INTERVAL - (current_time - last_reload_time))
        logging.info(f"跳过Nginx重载: 需等待 {time_left} 秒才能再次重载")
        return last_reload_time
    
    try:
        # 首先测试配置
        test_result = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
        if test_result.returncode != 0:
            logging.error(f"Nginx配置测试失败: {test_result.stderr}")
            return last_reload_time
        
        # 重载配置
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        logging.info("Nginx配置已重新加载")
        return current_time  # 更新上次重载时间
    except subprocess.CalledProcessError as e:
        logging.error(f"重新加载Nginx配置失败: {e}")
        return last_reload_time

# 清理过期的IP封禁
def clean_expired_bans(ban_dict, last_reload_time):
    current_time = datetime.now()
    expired_ips = [ip for ip, expiry in ban_dict.items() if expiry <= current_time]
    if expired_ips:
        for ip in expired_ips:
            logging.info(f"移除已过期的IP封禁: {ip}")
            del ban_dict[ip]
        if save_ban_list(ban_dict):
            return reload_nginx(last_reload_time)
    return last_reload_time

# 打印当前IP统计信息（调试模式）
def print_ip_stats(request_records):
    if not args.debug:
        return
    
    # 检查是否有活跃站点
    if not request_records:
        return
    
    current_time = datetime.now()
    logging.debug("----------当前站点IP请求统计（%d秒内）----------" % TIME_WINDOW)
    
    # 按站点分别打印IP统计
    for site, ips in sorted(request_records.items()):
        # 跳过没有活跃IP的站点
        if not ips:
            continue
            
        logging.debug(f"\n站点: {site}")
        
        # 对当前站点的IP按请求数排序
        sorted_ips = sorted(ips.items(), key=lambda x: len(x[1]), reverse=True)
        for ip, timestamps in sorted_ips:
            # 过滤最近时间窗口内的请求
            recent = [t for t in timestamps if (current_time - t).total_seconds() <= TIME_WINDOW]
            if recent:
                logging.debug(f"  IP: {ip} - 请求数: {len(recent)} - 阈值: {REQUEST_THRESHOLD}")
    
    logging.debug("----------------------------------------")

# 主监控函数
def monitor_logs():
    # 按站点分别存储每个IP的请求时间戳: site -> ip -> [timestamps]
    request_records = defaultdict(lambda: defaultdict(list))
    changes_made = False
    
    # 加载现有封禁列表
    ban_dict = load_ban_list()
    
    # 上次检查过期封禁的时间
    last_cleanup_time = time.time()
    
    # 上次重载Nginx的时间
    last_reload_time = time.time() - MIN_RELOAD_INTERVAL  # 确保第一次可以立即重载
    
    # 上次输出调试统计的时间（调试模式下）
    last_stats_time = time.time()
    
    # 获取所有日志文件
    log_files = get_log_files(LOG_DIR)
    
    # 站点名称映射
    site_names = {file: extract_site_name(file) for file in log_files}
    
    # 统计周期性指标
    stats = {
        "total_requests": 0,
        "filtered_requests": 0,
        "banned_ips": 0,
        "start_time": datetime.now()
    }
    
    logging.info(f"开始监控日志文件，过滤模式: {FILTER_PATTERN}, 使用IP头: {REAL_IP_HEADER}")
    logging.info(f"封禁阈值: {REQUEST_THRESHOLD}个请求/{TIME_WINDOW}秒, 封禁时长: {BLOCK_DURATION}秒")
    logging.info(f"监控 {len(site_names)} 个站点: {', '.join(set(site_names.values()))}")
    if args.debug:
        logging.debug(f"调试模式已启用 - 将显示详细的IP请求统计")
    
    try:
        while True:
            # 定期刷新日志文件列表
            if time.time() - last_cleanup_time >= 60:  # 每分钟刷新一次文件列表
                new_log_files = get_log_files(LOG_DIR)
                # 合并新发现的日志文件
                for file, pos in new_log_files.items():
                    if file not in log_files:
                        log_files[file] = pos
                        site_names[file] = extract_site_name(file)
                        logging.info(f"添加新站点日志: {file} -> {site_names[file]}")
            
            changes_in_files = False
            
            # 检查所有日志文件的变化
            for log_file in list(log_files.keys()):
                # 检查日志文件是否存在
                if not os.path.exists(log_file):
                    logging.warning(f"日志文件已移除: {log_file}")
                    site = site_names[log_file]
                    del log_files[log_file]
                    del site_names[log_file]
                    continue
                
                # 获取日志文件对应的站点名称
                site = site_names[log_file]
                
                # 获取当前日志文件大小
                try:
                    current_size = os.path.getsize(log_file)
                except:
                    logging.warning(f"无法获取文件大小: {log_file}")
                    continue
                
                # 如果文件被轮转（大小减小），从头开始读取
                if current_size < log_files[log_file]:
                    logging.info(f"日志文件已轮转: {log_file}，从头开始读取")
                    log_files[log_file] = 0
                
                # 如果文件没有变化，跳过此文件
                if current_size == log_files[log_file]:
                    continue
                
                changes_in_files = True
                
                # 读取新的日志条目
                try:
                    with open(log_file, 'r') as f:
                        f.seek(log_files[log_file])
                        new_lines = f.readlines()
                        log_files[log_file] = f.tell()
                except Exception as e:
                    logging.error(f"读取日志文件时出错: {log_file} - {e}")
                    continue
                
                # 处理新的日志条目
                for line in new_lines:
                    stats["total_requests"] += 1
                    
                    # 跳过不匹配过滤模式的请求
                    if FILTER_PATTERN not in line:
                        continue
                    
                    stats["filtered_requests"] += 1
                    
                    # 解析日志条目
                    match = re.match(LOG_PATTERN, line)
                    if match:
                        ip_str, time_str, request, status, size, referrer, user_agent = match.groups()
                        
                        # 解析日志中的时间戳
                        try:
                            # 典型格式: 10/Apr/2025:11:33:44 +0800
                            log_time = datetime.strptime(time_str.split()[0], "%d/%b/%Y:%H:%M:%S")
                        except:
                            # 如果解析失败，使用当前时间
                            log_time = datetime.now()
                        
                        # 处理IP地址
                        ip_key = ip_str
                        if ':' in ip_str:  # IPv6
                            ip_key = ipv6_to_subnet(ip_str)
                            if args.debug and ip_key != ip_str:
                                logging.debug(f"IPv6地址 {ip_str} 转换为子网 {ip_key}")
                        
                        # 跳过已封禁的IP
                        if ip_key in ban_dict:
                            if args.debug:
                                logging.debug(f"跳过已封禁的IP: {ip_key}")
                            continue
                        
                        # 记录请求时间（按站点分别记录）
                        request_records[site][ip_key].append(log_time)
                        
                        if args.debug:
                            count_before = len(request_records[site][ip_key])
                        
                        # 移除时间窗口外的记录
                        current_time = datetime.now()
                        request_records[site][ip_key] = [
                            t for t in request_records[site][ip_key] 
                            if (current_time - t).total_seconds() <= TIME_WINDOW
                        ]
                        
                        if args.debug:
                            count_after = len(request_records[site][ip_key])
                            if count_before != count_after:
                                logging.debug(f"站点 {site} - IP {ip_key} 请求计数清理: {count_before} -> {count_after} (移除过期记录)")
                        
                        # 检查IP在单个站点是否超过阈值
                        if len(request_records[site][ip_key]) > REQUEST_THRESHOLD:
                            # 添加到封禁列表
                            expiry = current_time + timedelta(seconds=BLOCK_DURATION)
                            ban_dict[ip_key] = expiry
                            stats["banned_ips"] += 1
                            logging.warning(
                                f"封禁 {ip_key} 直到 {expiry.strftime('%Y-%m-%d %H:%M:%S')} - "
                                f"站点 {site} 上有 {len(request_records[site][ip_key])} 个请求在 {TIME_WINDOW} 秒内"
                            )
                            changes_made = True
                            
                            # 清除此IP的计数（所有站点）
                            for s in request_records:
                                if ip_key in request_records[s]:
                                    request_records[s][ip_key] = []
                        elif args.debug:
                            current_count = len(request_records[site][ip_key])
                            if current_count > 0 and current_count % 5 == 0:  # 每增加5个请求打印一次
                                logging.debug(f"站点 {site} - IP {ip_key} 当前请求数: {current_count}/{REQUEST_THRESHOLD}")
            
            # 如果没有文件变化，等待一会儿
            if not changes_in_files:
                time.sleep(0.1)  # 避免忙等
            
            # 如果有变更，更新封禁列表文件并重新加载Nginx
            if changes_made:
                if save_ban_list(ban_dict):
                    last_reload_time = reload_nginx(last_reload_time)
                    changes_made = False
            
            # 清理内存中的旧记录
            current_time = datetime.now()
            for site in list(request_records.keys()):
                for ip in list(request_records[site].keys()):
                    old_count = len(request_records[site][ip])
                    request_records[site][ip] = [t for t in request_records[site][ip] 
                                      if (current_time - t).total_seconds() <= TIME_WINDOW]
                    if not request_records[site][ip]:
                        if args.debug and old_count > 0:
                            logging.debug(f"从记录中移除不活跃的IP: 站点 {site} - IP {ip}")
                        del request_records[site][ip]
                # 如果站点没有活跃IP，删除站点记录
                if not request_records[site]:
                    del request_records[site]
            
            # 定期检查过期封禁并打印统计信息
            current_time_sec = time.time()
            if current_time_sec - last_cleanup_time >= CHECK_INTERVAL:
                last_reload_time = clean_expired_bans(ban_dict, last_reload_time)
                last_cleanup_time = current_time_sec
                
                # 调试模式下定期打印统计信息
                if args.debug:
                    runtime = (datetime.now() - stats["start_time"]).total_seconds() / 60
                    # 计算当前活跃IP总数
                    active_ips_count = sum(len(ips) for ips in request_records.values())
                    
                    logging.debug("----- 运行统计 -----")
                    logging.debug(f"运行时间: {runtime:.1f} 分钟")
                    logging.debug(f"总请求数: {stats['total_requests']}")
                    logging.debug(f"过滤的请求数: {stats['filtered_requests']}")
                    logging.debug(f"封禁的IP数: {stats['banned_ips']}")
                    logging.debug(f"当前活跃站点数: {len(request_records)}")
                    logging.debug(f"当前活跃IP数: {active_ips_count}")
                    logging.debug(f"当前封禁IP数: {len(ban_dict)}")
                    logging.debug("--------------------")
                    
                    # 重置统计时间
                    last_stats_time = current_time_sec
            
            # 调试模式下定期打印IP统计
            if args.debug and current_time_sec - last_stats_time >= 5:  # 每5秒打印一次统计
                print_ip_stats(request_records)
                last_stats_time = current_time_sec
                
    except KeyboardInterrupt:
        logging.info("脚本被用户终止")
        if args.debug:
            print_ip_stats(request_records)

# 处理终止信号
def signal_handler(sig, frame):
    logging.info(f"收到信号 {sig}，正在关闭")
    exit(0)

if __name__ == "__main__":
    # 设置信号处理器
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # 打印脚本信息
    print_usage_info()
    
    try:
        monitor_logs()
    except Exception as e:
        logging.critical(f"未处理的异常: {e}", exc_info=True)
        raise
