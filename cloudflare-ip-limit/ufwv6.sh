#!/bin/bash
# Script to update UFW rules with latest Cloudflare IPv6 ranges
# For ports 80 (HTTP) and 443 (HTTPS)
# Log file
LOG_FILE="/var/log/cf_ipv6_ufw_update.log"
# Function to log messages
log_message() {
    echo "$(date): $1" >> "$LOG_FILE"
    echo "$1"
}
log_message "Starting Cloudflare IPv6 range update for UFW"
# Download the latest Cloudflare IPv6 ranges
log_message "Downloading Cloudflare IPv6 ranges..."
CF_IPV6_URL="https://www.cloudflare.com/ips-v6/"
CF_IPV6_TMP="/tmp/cf_ipv6_ranges.txt"
if ! curl -s "$CF_IPV6_URL" -o "$CF_IPV6_TMP" -L; then
    log_message "Error: Failed to download Cloudflare IPv6 ranges"
    exit 1
fi
# Remove trailing '#' if present in the file
sed -i 's/#$//' "$CF_IPV6_TMP"
# Check if the file has content
if [ ! -s "$CF_IPV6_TMP" ]; then
    log_message "Error: Downloaded file is empty"
    exit 1
fi
log_message "Successfully downloaded Cloudflare IPv6 ranges"

# 更简单、更直接的方法：使用ufw的直接命令删除特定规则
log_message "Removing all existing rules for ports 80 and 443..."

# 获取当前状态
STATUS=$(ufw status | grep -E "(80|443)/tcp")
log_message "Current rules for ports 80 and 443:"
log_message "$STATUS"

# 删除80端口的所有规则
log_message "Deleting all rules for port 80/tcp..."
# 删除IPv4规则
ufw delete allow 80/tcp 2>/dev/null
ufw delete deny 80/tcp 2>/dev/null
# 删除IPv6规则
ufw delete allow in on any to any port 80 proto tcp from ::/0 2>/dev/null
ufw delete deny in on any to any port 80 proto tcp from ::/0 2>/dev/null
# 删除特定源的规则
for src in $(ufw status | grep "80/tcp" | awk '{print $3}' | sort | uniq); do
    if [[ "$src" != "Anywhere" && "$src" != "Anywhere (v6)" ]]; then
        log_message "Deleting rule for 80/tcp from $src"
        ufw delete allow from $src to any port 80 proto tcp 2>/dev/null
    fi
done

# 删除443端口的所有规则
log_message "Deleting all rules for port 443/tcp..."
# 删除IPv4规则
ufw delete allow 443/tcp 2>/dev/null
ufw delete deny 443/tcp 2>/dev/null
# 删除IPv6规则
ufw delete allow in on any to any port 443 proto tcp from ::/0 2>/dev/null
ufw delete deny in on any to any port 443 proto tcp from ::/0 2>/dev/null
# 删除特定源的规则
for src in $(ufw status | grep "443/tcp" | awk '{print $3}' | sort | uniq); do
    if [[ "$src" != "Anywhere" && "$src" != "Anywhere (v6)" ]]; then
        log_message "Deleting rule for 443/tcp from $src"
        ufw delete allow from $src to any port 443 proto tcp 2>/dev/null
    fi
done

# 直接尝试删除v6规则，防止上面的方法没有覆盖
log_message "Making sure IPv6 rules are deleted..."
yes | ufw delete allow from ::/0 to any port 443 proto tcp 2>/dev/null
yes | ufw delete allow from ::/0 to any port 80 proto tcp 2>/dev/null

# 添加Cloudflare IPv6的允许规则
log_message "Adding allow rules for Cloudflare IPv6 ranges..."
while read -r IPV6_RANGE; do
    if [ -n "$IPV6_RANGE" ]; then
        log_message "Adding allow rule for $IPV6_RANGE to ports 80 and 443"
        ufw allow from "$IPV6_RANGE" to any port 80 proto tcp > /dev/null 2>&1
        ufw allow from "$IPV6_RANGE" to any port 443 proto tcp > /dev/null 2>&1
    fi
done < "$CF_IPV6_TMP"

# Reload UFW to apply changes
log_message "Reloading UFW to apply changes..."
ufw reload > /dev/null 2>&1

# 验证规则更新
log_message "Verifying UFW rules after update:"
ufw status | grep -E "(80|443)/tcp" >> "$LOG_FILE"

log_message "Cloudflare IPv6 range update completed successfully"
# Clean up
rm -f "$CF_IPV6_TMP"
exit 0
