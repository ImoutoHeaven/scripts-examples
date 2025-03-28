#!/bin/bash

# CloudFlare IP范围更新脚本 - 用于Nginx real_ip模块
# 获取IPv4和IPv6范围并生成set_real_ip_from指令

set -e  # 如果命令返回非零状态，立即退出

# 配置文件路径
CF_IP_FILE="/etc/nginx/cloudflare-real-ip.conf"
CF_IP_BACKUP="${CF_IP_FILE}.bak"
IPV4_TEMP=$(mktemp)
IPV6_TEMP=$(mktemp)
NEW_CONFIG=$(mktemp)

# 日志文件(适用于cron任务)
LOG_FILE="/var/log/cloudflare-ip-update.log"

# 记录日志的函数
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

log_message "开始更新CloudFlare IP范围"

# 获取IPv4范围
log_message "获取IPv4范围..."
if ! curl -s "https://www.cloudflare.com/ips-v4/" -L > "$IPV4_TEMP"; then
    log_message "错误: 无法获取CloudFlare IPv4范围"
    rm -f "$IPV4_TEMP" "$IPV6_TEMP" "$NEW_CONFIG"
    exit 1
fi

# 检查是否获取到IPv4内容
if [ ! -s "$IPV4_TEMP" ]; then
    log_message "错误: 获取的CloudFlare IPv4范围为空"
    rm -f "$IPV4_TEMP" "$IPV6_TEMP" "$NEW_CONFIG"
    exit 1
fi

# 获取IPv6范围
log_message "获取IPv6范围..."
if ! curl -s "https://www.cloudflare.com/ips-v6/" -L > "$IPV6_TEMP"; then
    log_message "错误: 无法获取CloudFlare IPv6范围"
    rm -f "$IPV4_TEMP" "$IPV6_TEMP" "$NEW_CONFIG"
    exit 1
fi

# 检查是否获取到IPv6内容
if [ ! -s "$IPV6_TEMP" ]; then
    log_message "错误: 获取的CloudFlare IPv6范围为空"
    rm -f "$IPV4_TEMP" "$IPV6_TEMP" "$NEW_CONFIG"
    exit 1
fi

# 创建新的配置文件
echo "# CloudFlare IP ranges for real_ip module - 自动更新于 $(date)" > "$NEW_CONFIG"
echo "" >> "$NEW_CONFIG"

# 处理IPv4范围 - 移除末尾可能的#号并去除空行
sed 's/#.*$//' "$IPV4_TEMP" | grep -v "^$" > "${IPV4_TEMP}.clean"

# 处理IPv6范围 - 移除末尾可能的#号并去除空行
sed 's/#.*$//' "$IPV6_TEMP" | grep -v "^$" > "${IPV6_TEMP}.clean"

# 添加到配置文件
while read -r ip; do
    echo "set_real_ip_from $ip;" >> "$NEW_CONFIG"
done < "${IPV4_TEMP}.clean"

while read -r ip; do
    echo "set_real_ip_from $ip;" >> "$NEW_CONFIG"
done < "${IPV6_TEMP}.clean"

# 添加real_ip_header指令
echo "" >> "$NEW_CONFIG"
echo "real_ip_header CF-Connecting-IP;" >> "$NEW_CONFIG"

# 计算IP范围数量
IPV4_COUNT=$(wc -l < "${IPV4_TEMP}.clean")
IPV6_COUNT=$(wc -l < "${IPV6_TEMP}.clean")
TOTAL_COUNT=$((IPV4_COUNT + IPV6_COUNT))

# 清理临时文件
rm -f "$IPV4_TEMP" "$IPV6_TEMP" "${IPV4_TEMP}.clean" "${IPV6_TEMP}.clean"

# 如果没有找到IP，退出并报错
if [ "$TOTAL_COUNT" -eq 0 ]; then
    log_message "错误: 未找到有效的IP范围，中止操作。"
    rm -f "$NEW_CONFIG"
    exit 1
fi

# 检查内容是否有变化(如果文件存在)
if [ -f "$CF_IP_FILE" ]; then
    if diff -q "$CF_IP_FILE" "$NEW_CONFIG" > /dev/null; then
        log_message "CloudFlare IP范围未变化，无需更新"
        rm -f "$NEW_CONFIG"
        exit 0
    fi

    # 变化了，备份现有文件
    log_message "备份当前配置文件..."
    cp "$CF_IP_FILE" "$CF_IP_BACKUP"
fi

# 应用新配置
mv "$NEW_CONFIG" "$CF_IP_FILE"

# 检查Nginx配置
log_message "检查Nginx配置..."
if ! nginx -t 2>> "$LOG_FILE"; then
    log_message "错误: Nginx配置测试失败，恢复备份..."
    if [ -f "$CF_IP_BACKUP" ]; then
        mv "$CF_IP_BACKUP" "$CF_IP_FILE"
    fi
    exit 1
fi

# 重新加载Nginx
log_message "重新加载Nginx..."
if ! systemctl reload nginx; then
    log_message "错误: 无法重新加载Nginx"
    if [ -f "$CF_IP_BACKUP" ]; then
        log_message "恢复备份..."
        mv "$CF_IP_BACKUP" "$CF_IP_FILE"
        systemctl reload nginx
    fi
    exit 1
fi

log_message "成功: 已更新CloudFlare IP范围配置，包含 $IPV4_COUNT 个IPv4范围和 $IPV6_COUNT 个IPv6范围(共 $TOTAL_COUNT 个)，并已重新加载Nginx。"
