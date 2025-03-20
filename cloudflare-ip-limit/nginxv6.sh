#!/bin/bash

# 优化的CloudFlare IPv6更新脚本
# 仅在成功获取新数据时更新配置，只保留一个备份文件

set -e  # 如果命令返回非零状态，立即退出

# CloudFlare IPv6 配置文件路径
CF_IPV6_FILE="/etc/nginx/cloudflare-ipv6.conf"
CF_IPV6_BACKUP="${CF_IPV6_FILE}.bak"
TEMP_FILE=$(mktemp)

echo "正在获取 CloudFlare IPv6 范围..."
if ! curl -s "https://www.cloudflare.com/ips-v6/#" -L | grep -v "#" > "$TEMP_FILE"; then
    echo "错误: 无法获取 CloudFlare IPv6 范围"
    rm -f "$TEMP_FILE"
    exit 1
fi

# 检查是否获取到内容
if [ ! -s "$TEMP_FILE" ]; then
    echo "错误: 获取的 CloudFlare IPv6 范围为空"
    rm -f "$TEMP_FILE"
    exit 1
fi

# 创建新的配置文件内容
NEW_CONFIG=$(mktemp)
echo "# CloudFlare IPv6 ranges - 自动更新于 $(date)" > "$NEW_CONFIG"
echo "" >> "$NEW_CONFIG"

while read -r ipv6_range; do
    if [ -n "$ipv6_range" ]; then
        echo "allow $ipv6_range;" >> "$NEW_CONFIG"
    fi
done < "$TEMP_FILE"

# 添加拒绝其他所有 IP 的指令
echo "deny all;" >> "$NEW_CONFIG"

# 删除临时文件
rm -f "$TEMP_FILE"

# 检查内容是否有变化(如果文件存在)
if [ -f "$CF_IPV6_FILE" ]; then
    if diff -q "$CF_IPV6_FILE" "$NEW_CONFIG" > /dev/null; then
        echo "CloudFlare IPv6 范围未变化，无需更新"
        rm -f "$NEW_CONFIG"
        exit 0
    fi

    # 变化了，备份现有文件
    echo "备份当前配置文件..."
    cp "$CF_IPV6_FILE" "$CF_IPV6_BACKUP"
fi

# 应用新配置
mv "$NEW_CONFIG" "$CF_IPV6_FILE"

# 检查 Nginx 配置
echo "检查 Nginx 配置..."
if ! nginx -t; then
    echo "错误: Nginx 配置测试失败，恢复备份..."
    if [ -f "$CF_IPV6_BACKUP" ]; then
        mv "$CF_IPV6_BACKUP" "$CF_IPV6_FILE"
    fi
    exit 1
fi

# 重新加载 Nginx
echo "重新加载 Nginx..."
if ! systemctl reload nginx; then
    echo "错误: 无法重新加载 Nginx"
    if [ -f "$CF_IPV6_BACKUP" ]; then
        echo "恢复备份..."
        mv "$CF_IPV6_BACKUP" "$CF_IPV6_FILE"
        systemctl reload nginx
    fi
    exit 1
fi

# 计算 IP 范围数量
IP_COUNT=$(grep -c "allow" "$CF_IPV6_FILE")
echo "成功: 已更新 CloudFlare IPv6 范围配置，包含 $IP_COUNT 个 IPv6 范围，并已重新加载 Nginx。"
