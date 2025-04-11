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
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

# 解析命令行参数
parser = argparse.ArgumentParser(description='Nginx日志监控与自适应IP封禁工具')
parser.add_argument('--debug', action='store_true', help='启用调试模式，输出更详细的IP计数统计和封禁判断信息')
parser.add_argument('--log-dir', default='/var/log/nginx', help='日志文件目录路径')
parser.add_argument('--filter', default='/api/fs/link', help='请求路径过滤模式')
parser.add_argument('--ip-header', default='CF-CONNECTING-IP', 
                    help='包含真实IP的HTTP头名称(如CF-CONNECTING-IP, X-REAL-IP, X-FORWARDED-FOR等)')
parser.add_argument('--burst-limit', type=int, default=100, help='短期爆发请求数阈值，允许10秒内的高流量爆发')
parser.add_argument('--avg-limit', type=float, default=5.0, help='长期平均TPS限制')
parser.add_argument('--short-window', type=int, default=10, help='短期爆发检测时间窗口（秒）')
parser.add_argument('--long-window', type=int, default=60, help='长期平均检测时间窗口（秒）')
parser.add_argument('--block-duration', type=int, default=1200, help='封禁持续时间（秒）')
parser.add_argument('--warning-duration', type=int, default=120, help='警告封禁持续时间（秒）')
parser.add_argument('--http-conf', default='/etc/nginx/limit-http.conf', help='HTTP块封禁配置文件路径')
parser.add_argument('--location-conf', default='/etc/nginx/limit-location.conf', help='Location块封禁配置文件路径')
parser.add_argument('--stats-interval', type=int, default=60, help='统计信息输出间隔（秒）')
args = parser.parse_args()

# 配置参数
LOG_DIR = args.log_dir
HTTP_CONF_FILE = args.http_conf
LOCATION_CONF_FILE = args.location_conf
BURST_LIMIT = args.burst_limit  # 短期爆发请求限制
AVG_LIMIT = args.avg_limit  # 长期平均TPS限制
SHORT_WINDOW = args.short_window  # 短期检测窗口（秒）
LONG_WINDOW = args.long_window  # 长期检测窗口（秒）
BLOCK_DURATION = args.block_duration  # 严重违规的封禁持续时间（秒）
WARNING_DURATION = args.warning_duration  # 警告封禁持续时间（秒）
CHECK_INTERVAL = 5  # 检查过期封禁的间隔（秒）
FILTER_PATTERN = args.filter  # 只监控包含此模式的请求
MIN_RELOAD_INTERVAL = 300  # 最小重载Nginx间隔（秒）
REAL_IP_HEADER = args.ip_header  # 真实IP的HTTP头
STATS_INTERVAL = args.stats_interval  # 统计信息输出间隔（秒）

# 封禁类型
BAN_TYPE_WARNING = "warning"  # 警告级别封禁
BAN_TYPE_BLOCK = "block"  # 完全封禁

# 新增: 待重载队列相关变量
pending_reload = False  # 是否有待执行的重载
pending_reload_time = 0  # 预计执行重载的时间
pending_ban_updates = False  # 标记是否有待更新的封禁

# 新增: 封禁统计相关变量
ban_statistics = {}  # 用于跟踪已封禁IP的响应统计
global_statistics = {
    "total_200_after_ban": 0,   # 封禁后返回200状态码的总次数
    "total_429_after_ban": 0,   # 封禁后返回429状态码的总次数
    "reload_count": 0,          # Nginx重载次数
    "total_warnings": 0,        # 总警告次数
    "total_blocks": 0,          # 总完全封禁次数
    "failed_blocks": 0,         # 失败的封禁次数 (有200响应)
    "effective_blocks": 0       # 有效的封禁次数 (只有429响应)
}

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

# 自适应速率限制器
class AdaptiveRateLimiter:
    def __init__(self, ip, short_window=SHORT_WINDOW, long_window=LONG_WINDOW, burst_limit=BURST_LIMIT, avg_limit=AVG_LIMIT):
        self.ip = ip
        self.short_window = short_window  # 短期窗口（秒）
        self.long_window = long_window    # 长期窗口（秒）
        self.burst_limit = burst_limit    # 短期爆发请求限制
        self.avg_limit = avg_limit        # 长期平均TPS限制
        self.request_history = []         # 请求时间戳历史
        self.warning_count = 0            # 警告计数
        self.last_warning_time = None     # 上次警告时间
        self.warned_until = None          # 警告状态持续到
        self.sites = set()                # 该IP访问过的站点
        self.regular_pattern_flag = False # 标记是否检测到规律模式但未超TPS限制
    
    def add_request(self, timestamp, site):
        """添加新请求并清理过期记录"""
        self.request_history.append(timestamp)
        self.sites.add(site)
        # 清理超出长期窗口的记录
        cutoff = timestamp - timedelta(seconds=self.long_window)
        self.request_history = [t for t in self.request_history if t >= cutoff]
    
    def evaluate(self, current_time):
        """评估IP行为并返回应采取的动作"""
        if not self.request_history:
            return "allow"
            
        # 如果当前处于警告状态
        if self.warned_until and current_time < self.warned_until:
            return "warning"  # 维持警告状态
            
        # 计算短期窗口内的请求数
        short_cutoff = current_time - timedelta(seconds=self.short_window)
        short_requests = [t for t in self.request_history if t >= short_cutoff]
        short_count = len(short_requests)
        
        # 计算长期窗口内的平均TPS
        time_span = (current_time - self.request_history[0]).total_seconds() if self.request_history else 0
        # 确保时间跨度至少为1秒避免除零错误
        effective_time_span = max(1.0, time_span)
        long_tps = len(self.request_history) / effective_time_span
        
        # 短期爆发检查
        if short_count > self.burst_limit:
            self.warning_count += 1
            if self.warning_count >= 3:
                logging.warning(f"IP {self.ip} 多次超过爆发限制 ({short_count}/{self.burst_limit})，执行完全封禁")
                return "block"
            else:
                logging.warning(f"IP {self.ip} 请求爆发超过限制 ({short_count}/{self.burst_limit})，发出警告 (#{self.warning_count})")
                self.warned_until = current_time + timedelta(seconds=WARNING_DURATION)
                return "warning"
        
        # 长期平均检查（只有在有足够样本时才检查）
        if time_span >= self.long_window * 0.3 and len(self.request_history) > 15:
            if long_tps > self.avg_limit:
                logging.warning(f"IP {self.ip} 长期TPS超过限制 ({long_tps:.2f}/{self.avg_limit})，执行封禁")
                return "block"
        
        # 请求模式分析 - 修改后只有当TPS也超限时才封禁
        if len(self.request_history) >= 20:  # 至少有20个请求才进行模式分析
            pattern_score = self.analyze_request_pattern()
            
            # 只有当模式异常且TPS超限时才封禁
            if pattern_score > 0.85 and long_tps > self.avg_limit:
                logging.warning(f"IP {self.ip} 请求模式异常 (得分:{pattern_score:.2f}) 且 TPS过高 ({long_tps:.2f}/{self.avg_limit})，执行封禁")
                return "block"
            elif pattern_score > 0.85:
                # 记录规律模式但不封禁
                if not self.regular_pattern_flag:
                    logging.info(f"检测到规律请求模式: IP {self.ip} (得分:{pattern_score:.2f}) 但TPS在限制内 ({long_tps:.2f}/{self.avg_limit})，允许通过")
                    self.regular_pattern_flag = True
        
        return "allow"
    
    def analyze_request_pattern(self):
        """分析请求模式，返回0-1之间的异常分数"""
        if len(self.request_history) < 10:
            return 0.0  # 样本太少，无法判断
        
        # 计算请求间隔
        intervals = []
        for i in range(1, len(self.request_history)):
            interval = (self.request_history[i] - self.request_history[i-1]).total_seconds()
            intervals.append(interval)
        
        if not intervals:
            return 0.0
        
        # 计算间隔的标准差
        try:
            mean_interval = sum(intervals) / len(intervals)
            if mean_interval < 0.001:  # 防止除零错误
                mean_interval = 0.001
                
            # 计算变异系数（标准差/平均值）- 衡量相对分散程度
            std_dev = statistics.stdev(intervals) if len(intervals) > 1 else 0
            cv = std_dev / mean_interval
            
            # 正常用户行为的特征是间隔有一定的随机性，CV通常较高
            # 爬虫的特征是间隔非常规律，CV通常很低（接近0）
            
            # 转换成异常分数 (0-1)
            # CV值越小，越可能是爬虫，分数越高
            regularity_score = max(0, min(1, 1.0 - min(cv, 1.0)))
            
            # 极短间隔的规律请求更可疑，但不再增加额外权重
            # 移除基于请求数量的加权，专注于请求模式
            
            return min(1.0, regularity_score)
            
        except (statistics.StatisticsError, ZeroDivisionError):
            # 处理统计计算中可能出现的错误
            return 0.3  # 返回中等程度的怀疑分数
    
    def get_stats(self):
        """获取此IP的统计信息，用于调试"""
        if not self.request_history:
            return "无请求记录"
            
        now = datetime.now()
        short_cutoff = now - timedelta(seconds=self.short_window)
        short_requests = [t for t in self.request_history if t >= short_cutoff]
        short_count = len(short_requests)
        
        time_span = (now - self.request_history[0]).total_seconds()
        tps = len(self.request_history) / max(1.0, time_span)
        
        status = "正常"
        if self.warned_until and now < self.warned_until:
            time_left = (self.warned_until - now).total_seconds()
            status = f"警告中 ({time_left:.0f}秒)"
            
        pattern_score = self.analyze_request_pattern() if len(self.request_history) >= 10 else 0
        pattern_flag = "是" if self.regular_pattern_flag else "否"
        
        stats = (
            f"站点: {', '.join(self.sites)}, "
            f"状态: {status}, "
            f"短期: {short_count}/{self.burst_limit}, "
            f"TPS: {tps:.2f}/{self.avg_limit}, "
            f"模式得分: {pattern_score:.2f}, "
            f"规律模式: {pattern_flag}, "
            f"警告次数: {self.warning_count}, "
            f"总请求: {len(self.request_history)}"
        )
        return stats

# 新增: 封禁IP统计跟踪类
class BanStatistics:
    def __init__(self, ip, ban_type, expiry):
        self.ip = ip
        self.ban_type = ban_type
        self.expiry = expiry
        self.first_seen = datetime.now()
        self.last_seen = datetime.now()
        self.status_200_count = 0  # 成功状态计数（封禁失效）
        self.status_429_count = 0  # 限流状态计数（封禁有效）
        self.other_status_count = 0  # 其他状态码计数
        self.total_requests = 0  # 封禁期间的总请求数
    
    def update(self, status_code, timestamp=None):
        """更新状态码统计"""
        if timestamp is None:
            timestamp = datetime.now()
        
        self.last_seen = timestamp
        self.total_requests += 1
        
        if status_code == 200:
            self.status_200_count += 1
        elif status_code == 429:
            self.status_429_count += 1
        else:
            self.other_status_count += 1
    
    def get_stats(self):
        """获取统计信息摘要"""
        effectiveness = "有效" if self.status_200_count == 0 and self.status_429_count > 0 else \
                        "部分有效" if self.status_200_count > 0 and self.status_429_count > 0 else \
                        "无效" if self.status_200_count > 0 and self.status_429_count == 0 else "未知"
        
        duration = (self.last_seen - self.first_seen).total_seconds()
        remaining = (self.expiry - datetime.now()).total_seconds()
        
        return {
            "ip": self.ip,
            "ban_type": self.ban_type,
            "effectiveness": effectiveness,
            "status_200": self.status_200_count,
            "status_429": self.status_429_count,
            "other_status": self.other_status_count,
            "total_requests": self.total_requests,
            "duration_seconds": duration,
            "remaining_seconds": max(0, remaining)
        }

# 脚本说明信息
def print_usage_info():
    logging.info("=== Nginx 自适应IP封禁监控器 ===")
    logging.info(f"配置文件:")
    logging.info(f"  - HTTP块配置: {HTTP_CONF_FILE} (包含map指令，请放在http块中)")
    logging.info(f"  - Location块配置: {LOCATION_CONF_FILE} (包含if条件，请放在location块中)")
    logging.info(f"监控设置:")
    logging.info(f"  - 使用的IP头: {REAL_IP_HEADER}")
    logging.info(f"  - 监控路径: 包含 {FILTER_PATTERN} 的请求")
    logging.info(f"  - 短期爆发限制: {BURST_LIMIT}个请求/{SHORT_WINDOW}秒")
    logging.info(f"  - 长期平均限制: {AVG_LIMIT} TPS (在 {LONG_WINDOW}秒 窗口内)")
    logging.info(f"  - 警告封禁时长: {WARNING_DURATION}秒")
    logging.info(f"  - 完全封禁时长: {BLOCK_DURATION}秒")
    logging.info(f"  - Nginx重载冷却时间: {MIN_RELOAD_INTERVAL}秒")
    logging.info(f"  - 统计信息输出间隔: {STATS_INTERVAL}秒")
    logging.info(f"封禁规则:")
    logging.info(f"  - 短期爆发超限 > {BURST_LIMIT}个请求/{SHORT_WINDOW}秒: 发出警告")
    logging.info(f"  - 连续3次短期爆发超限: 执行完全封禁")
    logging.info(f"  - 长期TPS > {AVG_LIMIT}: 执行完全封禁")
    logging.info(f"  - 规律请求模式 + TPS > {AVG_LIMIT}: 执行完全封禁")
    logging.info(f"  - 规律请求模式但TPS <= {AVG_LIMIT}: 允许通过")
    logging.info(f"统计功能:")
    logging.info(f"  - 追踪已封禁IP的状态码统计 (200/429)")
    logging.info(f"  - IPv4按/32精度统计，IPv6按/64子网统计")
    logging.info(f"  - 定期输出封禁有效性报告")
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

        # 将被完全封禁的IP添加到原始封禁映射中(完全封禁才会出现在ip_is_banned中)
        for ip, ban_info in ban_dict.items():
            ban_type = ban_info['type']
            if ban_type == BAN_TYPE_BLOCK:  # 只有完全封禁才添加到原始映射
                expiry = ban_info['expiry'].strftime('%Y-%m-%d %H:%M:%S')
                http_config += f'    # 封禁到: {expiry} - 类型: {ban_type}\n'
                http_config += f'    "{ip}" 1;\n'
        
        # 关闭第一个map指令
        http_config += "}\n\n"

        # 创建一个单独的封禁级别映射（独立的map指令）
        http_config += f"""# IP封禁级别映射表 - 0=不封禁, 1=警告, 2=完全封禁
map ${real_ip_var} $ip_ban_level {{
    default 0;
"""

        # IPv4 和 IPv6 地址添加到级别映射
        for ip, ban_info in sorted(ban_dict.items()):
            expiry = ban_info['expiry'].strftime('%Y-%m-%d %H:%M:%S')
            ban_type = ban_info['type']
            ban_level = "1" if ban_type == BAN_TYPE_WARNING else "2"
            
            http_config += f'    # 封禁到: {expiry} - 类型: {ban_type}\n'
            
            # 处理CIDR格式的IPv6
            if ':' in ip and '/' in ip:
                http_config += f'    "{ip}" {ban_level}; # IPv6子网\n'
            else:
                http_config += f'    "{ip}" {ban_level};\n'
        
        # 关闭级别映射
        http_config += "}\n"

        # 组合两个条件：IP头存在且IP被封禁
        http_config += """
# 最终封禁决定 - 只有当IP头存在且IP在封禁列表中时才封禁
map $has_real_ip $is_banned_ip {
    0       0;  # IP头不存在，强制不封禁
    1       $ip_is_banned;  # IP头存在，使用封禁结果
}

# 最终封禁级别 - 只有当IP头存在时才返回封禁级别
map $has_real_ip $ban_level {
    0       0;  # IP头不存在，强制不封禁
    1       $ip_ban_level;  # IP头存在，使用封禁级别
}
"""

        # 2. 创建Location块配置文件（使用if条件）
        location_config = f"""# 自动生成的IP封禁配置（Location块） - 请勿手动编辑
# 最后更新: {current_time}
# 使用的真实IP头: {REAL_IP_HEADER}
# 总封禁IP数: {len(ban_dict)}

# 应用封禁规则
if ($ban_level = 2) {{
    # 完全封禁
    return 429;
}}

if ($ban_level = 1) {{
    # 警告级别封禁 - 429状态码但有不同的响应头
    add_header X-Rate-Limit-Warning "请减缓请求速率，您已接近封禁阈值" always;
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
            
            # 查找所有封禁IP及其级别 - 使用修复后的格式
            # 统一格式：封禁时间+类型+IP+级别;
            pattern = r'#\s+封禁到:\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+-\s+类型:\s+(\w+)\s*\n\s*"([^"]+)"\s+(\d);'
            matches = re.finditer(pattern, content)
            
            for match in matches:
                expiry_str = match.group(1)
                ban_type = match.group(2)
                ip = match.group(3)
                level = match.group(4)
                
                try:
                    expiry = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
                    # 检查是否已存在，避免重复添加
                    if ip not in ban_dict:
                        ban_dict[ip] = {
                            'expiry': expiry,
                            'type': ban_type
                        }
                        
                        # 初始化统计对象
                        ban_statistics[ip] = BanStatistics(ip, ban_type, expiry)
                        
                        if args.debug:
                            logging.debug(f"加载已封禁IP: {ip}, 类型: {ban_type}, 到期时间: {expiry_str}")
                except Exception as e:
                    logging.error(f"解析封禁时间出错: {ip}, {e}")
                    
    except FileNotFoundError:
        # 如果文件不存在则创建空的封禁列表
        save_ban_list({})
    
    logging.info(f"已加载 {len(ban_dict)} 个现有封禁IP")
    return ban_dict

# 重新加载Nginx配置
def reload_nginx(last_reload_time):
    global pending_reload, pending_reload_time, pending_ban_updates, global_statistics
    current_time = time.time()
    
    # 检查是否符合最小重载间隔
    if current_time - last_reload_time < MIN_RELOAD_INTERVAL:
        time_left = int(MIN_RELOAD_INTERVAL - (current_time - last_reload_time))
        logging.info(f"延迟Nginx重载: 将在 {time_left} 秒后执行")
        # 设置待执行重载标志和预计执行时间
        pending_reload = True
        pending_reload_time = last_reload_time + MIN_RELOAD_INTERVAL
        return last_reload_time
    
    try:
        # 首先测试配置
        test_result = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
        if test_result.returncode != 0:
            logging.error(f"Nginx配置测试失败: {test_result.stderr}")
            return last_reload_time
        
        # 重载配置
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        global_statistics["reload_count"] += 1
        logging.info(f"Nginx配置已重新加载 (总重载次数: {global_statistics['reload_count']})")
        
        # 更新全局重载时间
        last_reload_timestamp = datetime.now()
        
        # 重置待重载标志
        pending_reload = False
        pending_ban_updates = False
        return current_time  # 更新上次重载时间
    except subprocess.CalledProcessError as e:
        logging.error(f"重新加载Nginx配置失败: {e}")
        return last_reload_time

# 更新封禁时间使其基于实际重载时间计算
def update_ban_expiry_times(ban_dict):
    current_time = datetime.now()
    # 更新所有IP的封禁时间，从当前时间开始计算
    for ip in ban_dict:
        ban_type = ban_dict[ip]['type']
        duration = WARNING_DURATION if ban_type == BAN_TYPE_WARNING else BLOCK_DURATION
        ban_dict[ip]['expiry'] = current_time + timedelta(seconds=duration)
        
        # 同时更新统计对象中的过期时间
        if ip in ban_statistics:
            ban_statistics[ip].expiry = ban_dict[ip]['expiry']
            
        if args.debug:
            logging.debug(f"更新IP {ip} 的封禁过期时间: {ban_dict[ip]['expiry'].strftime('%Y-%m-%d %H:%M:%S')}")
    return ban_dict

# 清理过期的IP封禁
def clean_expired_bans(ban_dict, last_reload_time):
    global pending_ban_updates
    current_time = datetime.now()
    expired_ips = [ip for ip, ban_info in ban_dict.items() if ban_info['expiry'] <= current_time]
    if expired_ips:
        # 在移除前记录和输出过期IP的统计信息
        for ip in expired_ips:
            if ip in ban_statistics:
                stats = ban_statistics[ip].get_stats()
                logging.info(f"封禁过期统计 - IP: {ip}, 类型: {stats['ban_type']}, "
                            f"有效性: {stats['effectiveness']}, "
                            f"429次数: {stats['status_429']}, 200次数: {stats['status_200']}, "
                            f"总请求: {stats['total_requests']}")
                del ban_statistics[ip]
            logging.info(f"移除已过期的IP封禁: {ip}")
            del ban_dict[ip]
        if save_ban_list(ban_dict):
            pending_ban_updates = True
            return reload_nginx(last_reload_time)
    return last_reload_time

# 新增：更新封禁IP的响应统计
def update_ban_response_stats(ip, status_code, timestamp=None):
    """更新已封禁IP的响应状态码统计"""
    global global_statistics
    
    # 标准化IPv6地址为子网
    if ':' in ip:  # IPv6地址
        ip = ipv6_to_subnet(ip)
    
    if ip in ban_statistics:
        ban_statistics[ip].update(status_code, timestamp)
        
        # 更新全局统计
        if status_code == 200:
            global_statistics["total_200_after_ban"] += 1
        elif status_code == 429:
            global_statistics["total_429_after_ban"] += 1
        
        # 记录特别的事件 - 封禁后出现200响应
        if status_code == 200:
            logging.warning(f"检测到封禁失效! IP {ip} 在封禁期间收到200响应")
            return True  # 标记发现了封禁失效情况
    return False

# 新增：打印封禁统计信息
def print_ban_stats():
    """输出当前所有封禁IP的统计信息"""
    if not ban_statistics:
        logging.info("当前没有活跃的IP封禁")
        return
    
    # 计算有效和无效的封禁数量
    effective_bans = 0
    ineffective_bans = 0
    partial_bans = 0
    warning_bans = 0
    block_bans = 0
    
    for ip, stats_obj in ban_statistics.items():
        stats = stats_obj.get_stats()
        if stats["effectiveness"] == "有效":
            effective_bans += 1
        elif stats["effectiveness"] == "无效":
            ineffective_bans += 1
        elif stats["effectiveness"] == "部分有效":
            partial_bans += 1
            
        if stats["ban_type"] == BAN_TYPE_WARNING:
            warning_bans += 1
        elif stats["ban_type"] == BAN_TYPE_BLOCK:
            block_bans += 1
    
    total_bans = len(ban_statistics)
    
    # 更新全局统计
    global_statistics["effective_blocks"] = effective_bans
    global_statistics["failed_blocks"] = ineffective_bans + partial_bans
    
    logging.info(f"=== IP封禁统计 (总数: {total_bans}) ===")
    logging.info(f"- 完全有效封禁: {effective_bans} ({effective_bans/total_bans*100:.1f}%)")
    logging.info(f"- 部分有效封禁: {partial_bans} ({partial_bans/total_bans*100:.1f}%)")
    logging.info(f"- 无效封禁: {ineffective_bans} ({ineffective_bans/total_bans*100:.1f}%)")
    logging.info(f"- 警告级别: {warning_bans}, 完全封禁: {block_bans}")
    logging.info(f"- 总计封禁后200响应: {global_statistics['total_200_after_ban']}")
    logging.info(f"- 总计封禁后429响应: {global_statistics['total_429_after_ban']}")
    
    # 如果有无效或部分有效的封禁，列出详情
    if ineffective_bans > 0 or partial_bans > 0:
        logging.info("=== 问题封禁详情 ===")
        for ip, stats_obj in ban_statistics.items():
            stats = stats_obj.get_stats()
            if stats["effectiveness"] in ["无效", "部分有效"]:
                logging.info(f"IP: {ip}, 类型: {stats['ban_type']}, "
                            f"状态码 - 200: {stats['status_200']}, 429: {stats['status_429']}, "
                            f"剩余时间: {stats['remaining_seconds']:.0f}秒")
    
    logging.info("=" * 30)

# 打印当前IP统计信息（调试模式）
def print_ip_stats(rate_limiters):
    if not args.debug:
        return
    
    # 检查是否有活跃IP
    if not rate_limiters:
        return
    
    current_time = datetime.now()
    logging.debug("----------当前活跃IP统计----------")
    
    # 按IP请求数排序
    sorted_ips = sorted(rate_limiters.items(), 
                        key=lambda x: len(x[1].request_history) if x[1].request_history else 0, 
                        reverse=True)
    
    # 只显示前20个最活跃的IP
    for ip, limiter in sorted_ips[:20]:
        stats = limiter.get_stats()
        logging.debug(f"IP: {ip} - {stats}")
    
    # 统计规律模式但未封禁的IP数量
    regular_pattern_count = sum(1 for _, limiter in rate_limiters.items() if limiter.regular_pattern_flag)
    if regular_pattern_count > 0:
        logging.debug(f"检测到 {regular_pattern_count} 个具有规律模式但TPS在限制内的IP（可能是良好爬虫）")
    
    logging.debug("-----------------------------------")

# 新增：打印全局运行统计信息
def print_global_stats(stats):
    """打印全局统计信息摘要"""
    runtime = (datetime.now() - stats["start_time"]).total_seconds() / 60
    logging.info(f"=== 全局运行统计 (运行时间: {runtime:.1f}分钟) ===")
    logging.info(f"- 总请求数: {stats['total_requests']}")
    logging.info(f"- 过滤的请求数: {stats['filtered_requests']}")
    logging.info(f"- 总警告次数: {stats['total_warnings']}")
    logging.info(f"- 总封禁次数: {stats['total_blocks']}")
    logging.info(f"- Nginx重载次数: {stats['reload_count']}")
    logging.info(f"- 当前封禁统计: 有效 {global_statistics['effective_blocks']}, "
                f"失效 {global_statistics['failed_blocks']}")
    logging.info(f"- 封禁效果: 429响应 {global_statistics['total_429_after_ban']}, "
                f"200响应 {global_statistics['total_200_after_ban']}")
    
    # 计算封禁有效率
    if stats['total_blocks'] > 0:
        effective_rate = global_statistics['effective_blocks'] / stats['total_blocks'] * 100
        logging.info(f"- 封禁有效率: {effective_rate:.1f}%")
    
    logging.info("=" * 30)

# 主监控函数
def monitor_logs():
    global pending_reload, pending_reload_time, pending_ban_updates, global_statistics
    
    # 存储每个IP的速率限制器
    rate_limiters = {}
    changes_made = False
    
    # 加载现有封禁列表
    ban_dict = load_ban_list()
    
    # 上次检查过期封禁的时间
    last_cleanup_time = time.time()
    
    # 上次重载Nginx的时间
    last_reload_time = time.time() - MIN_RELOAD_INTERVAL  # 确保第一次可以立即重载
    
    # 上次输出调试统计的时间（调试模式下）
    last_stats_time = time.time()
    
    # 上次输出封禁统计的时间
    last_ban_stats_time = time.time()
    
    # 获取所有日志文件
    log_files = get_log_files(LOG_DIR)
    
    # 站点名称映射
    site_names = {file: extract_site_name(file) for file in log_files}
    
    # 统计周期性指标
    stats = {
        "total_requests": 0,
        "filtered_requests": 0,
        "banned_ips": 0,
        "warned_ips": 0,
        "regular_pattern_ips": 0,
        "total_warnings": 0,  # 新增：总警告次数
        "total_blocks": 0,    # 新增：总封禁次数
        "start_time": datetime.now()
    }
    
    logging.info(f"开始监控日志文件，过滤模式: {FILTER_PATTERN}, 使用IP头: {REAL_IP_HEADER}")
    logging.info(f"短期爆发限制: {BURST_LIMIT}个请求/{SHORT_WINDOW}秒, 长期平均限制: {AVG_LIMIT} TPS")
    logging.info(f"监控 {len(site_names)} 个站点: {', '.join(set(site_names.values()))}")
    logging.info(f"规律模式爬虫处理策略: 只要TPS不超过{AVG_LIMIT}，即使是规律性请求也允许通过")
    logging.info(f"封禁统计功能已启用，将跟踪封禁IP的200/429响应数")
    if args.debug:
        logging.debug(f"调试模式已启用 - 将显示详细的IP请求统计")
    
    try:
        while True:
            # 检查是否有待执行的重载请求
            current_time = time.time()
            if pending_reload and current_time >= pending_reload_time:
                logging.info("执行延迟的Nginx重载")
                if pending_ban_updates:
                    # 更新所有封禁IP的过期时间
                    ban_dict = update_ban_expiry_times(ban_dict)
                    # 保存更新后的封禁列表
                    save_ban_list(ban_dict)
                # 执行重载
                last_reload_time = reload_nginx(pending_reload_time - MIN_RELOAD_INTERVAL)
            
            # 定期刷新日志文件列表
            if current_time - last_cleanup_time >= 60:  # 每分钟刷新一次文件列表
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
                    
                    # 解析日志条目，即使不匹配过滤模式也需要记录状态码
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
                        
                        # 检查是否为已封禁IP的响应
                        try:
                            status_code = int(status)
                            # 对所有封禁过的IP进行响应跟踪
                            if ip_key in ban_dict:
                                ban_failure = update_ban_response_stats(ip_key, status_code, log_time)
                                # 如果发现封禁失效（200响应），尝试立即重载Nginx
                                if ban_failure and not pending_reload:
                                    logging.warning(f"检测到封禁失效，尝试重新加载Nginx配置")
                                    # 只有在允许的情况下才重载
                                    if current_time - last_reload_time >= MIN_RELOAD_INTERVAL:
                                        last_reload_time = reload_nginx(last_reload_time)
                        except ValueError:
                            # 状态码不是数字，忽略
                            pass
                    
                    # 跳过不匹配过滤模式的请求
                    if FILTER_PATTERN not in line:
                        continue
                    
                    stats["filtered_requests"] += 1
                    
                    # 完整解析匹配过滤模式的日志条目
                    if match:                        
                        # 跳过已封禁的IP的过滤请求（仅限计数，而不进行评估）
                        if ip_key in ban_dict:
                            if args.debug:
                                logging.debug(f"跳过已封禁的IP过滤请求: {ip_key}")
                            continue
                        
                        # 为该IP创建或获取速率限制器
                        if ip_key not in rate_limiters:
                            rate_limiters[ip_key] = AdaptiveRateLimiter(ip_key)
                        
                        # 记录请求
                        rate_limiters[ip_key].add_request(log_time, site)
                        
                        # 评估IP行为
                        current_time_dt = datetime.now()
                        action = rate_limiters[ip_key].evaluate(current_time_dt)
                        
                        # 更新规律模式IP统计
                        if rate_limiters[ip_key].regular_pattern_flag:
                            stats["regular_pattern_ips"] += 1
                        
                        # 根据评估结果采取行动
                        if action != "allow":
                            # 确定封禁类型和持续时间
                            if action == "warning":
                                ban_type = BAN_TYPE_WARNING
                                duration = WARNING_DURATION
                                stats["warned_ips"] += 1
                                stats["total_warnings"] += 1
                                global_statistics["total_warnings"] = stats["total_warnings"]
                                logging.warning(f"警告IP {ip_key} - 请求过于频繁 (持续{duration}秒)")
                            else:  # action == "block"
                                ban_type = BAN_TYPE_BLOCK
                                duration = BLOCK_DURATION
                                stats["banned_ips"] += 1
                                stats["total_blocks"] += 1
                                global_statistics["total_blocks"] = stats["total_blocks"]
                                logging.warning(f"封禁IP {ip_key} - 疑似高频爬虫 (持续{duration}秒)")
                            
                            # 添加到封禁列表
                            expiry = current_time_dt + timedelta(seconds=duration)
                            ban_dict[ip_key] = {
                                'expiry': expiry,
                                'type': ban_type
                            }
                            
                            # 创建新的统计对象
                            ban_statistics[ip_key] = BanStatistics(ip_key, ban_type, expiry)
                            
                            changes_made = True
                            pending_ban_updates = True
            
            # 如果没有文件变化，等待一会儿
            if not changes_in_files:
                time.sleep(0.1)  # 避免忙等
            
            # 如果有变更，更新封禁列表文件并重新加载Nginx
            if changes_made:
                if save_ban_list(ban_dict):
                    last_reload_time = reload_nginx(last_reload_time)
                    changes_made = False
            
            # 清理内存中的不活跃IP记录
            current_time_dt = datetime.now()
            inactive_cutoff = current_time_dt - timedelta(seconds=LONG_WINDOW * 2)
            inactive_ips = []
            
            for ip, limiter in rate_limiters.items():
                if not limiter.request_history or limiter.request_history[-1] < inactive_cutoff:
                    inactive_ips.append(ip)
            
            for ip in inactive_ips:
                if args.debug:
                    logging.debug(f"从内存中移除不活跃的IP: {ip}")
                del rate_limiters[ip]
            
            # 定期检查过期封禁并打印统计信息
            current_time = time.time()
            if current_time - last_cleanup_time >= CHECK_INTERVAL:
                last_reload_time = clean_expired_bans(ban_dict, last_reload_time)
                last_cleanup_time = current_time
                
                # 调试模式下定期打印统计信息
                if args.debug:
                    runtime = (datetime.now() - stats["start_time"]).total_seconds() / 60
                    
                    # 更新规律模式IP计数
                    regular_pattern_count = sum(1 for _, limiter in rate_limiters.items() if limiter.regular_pattern_flag)
                    
                    logging.debug("----- 运行统计 -----")
                    logging.debug(f"运行时间: {runtime:.1f} 分钟")
                    logging.debug(f"总请求数: {stats['total_requests']}")
                    logging.debug(f"过滤的请求数: {stats['filtered_requests']}")
                    logging.debug(f"警告的IP数: {stats['warned_ips']}")
                    logging.debug(f"封禁的IP数: {stats['banned_ips']}")
                    logging.debug(f"规律模式但允许的IP数: {regular_pattern_count}")
                    logging.debug(f"当前监控的IP数: {len(rate_limiters)}")
                    logging.debug(f"当前封禁IP数: {len(ban_dict)}")
                    logging.debug(f"是否有待执行的重载: {pending_reload}")
                    if pending_reload:
                        time_left = int(pending_reload_time - current_time)
                        logging.debug(f"重载倒计时: {time_left}秒")
                    logging.debug("--------------------")
                    
                    # 重置统计时间
                    last_stats_time = current_time
            
            # 定期输出封禁统计信息
            if current_time - last_ban_stats_time >= STATS_INTERVAL:
                print_ban_stats()
                print_global_stats(stats)
                last_ban_stats_time = current_time
            
            # 调试模式下定期打印IP统计
            if args.debug and current_time - last_stats_time >= 5:  # 每5秒打印一次统计
                print_ip_stats(rate_limiters)
                last_stats_time = current_time
                
    except KeyboardInterrupt:
        logging.info("脚本被用户终止")
        # 在终止前输出最终统计
        print_ban_stats()
        print_global_stats(stats)
        if args.debug:
            print_ip_stats(rate_limiters)

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
