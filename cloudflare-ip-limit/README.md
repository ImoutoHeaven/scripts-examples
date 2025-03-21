# Secure Nginx Proxy Setup with Cloudflare Protection

This repository contains configuration files and scripts for setting up a secure website infrastructure using a two-tier architecture with Cloudflare protection.

## Architecture Overview

The setup consists of two main components:

1. **Frontend Machine**: Acts as a reverse proxy to filter and forward legitimate traffic
2. **Backend Machine**: Hosts the actual web application (e.g., Alist)

```
Internet → Cloudflare → Frontend Machine → Backend Machine
```

This architecture provides multiple layers of security:

- **Cloudflare WAF**: Protects against common web attacks
- **Frontend filtering**: Only allows Cloudflare IPs to connect
- **Backend restriction**: Only accepts connections from the frontend

## Security Features

- ✅ Custom HTTP header verification between Cloudflare and Frontend
- ✅ IP restriction at Frontend (only Cloudflare)
- ✅ IP restriction at Backend (only Frontend)
- ✅ SNI-based routing for multiple domains
- ✅ Bot blocking for search engines
- ✅ Automatic Cloudflare IPv6 range updates
- ✅ TLS protection with Cloudflare Edge certificates
- ✅ HTTP to HTTPS redirection

## Setup Instructions

### Prerequisites

- Two servers (VPS or physical)
- Domain name(s) configured in Cloudflare (Full/Strict SSL mode)
- Ubuntu/Debian-based OS (for UFW instructions)

### Frontend Machine Setup

1. Install required packages:

```bash
apt-get update
apt-get install nginx nginx-extras ufw
```

2. Deploy configuration files:

- Copy `frontend-nginx-http-to-https.conf` to `/etc/nginx/sites-enabled/`
- Copy `frontend-nginx-stream.conf` to `/etc/nginx/`

3. Edit `nginx.conf` to include the stream configuration:

```bash
# Add this line between events{} and http{} blocks
include /etc/nginx/frontend-nginx-stream.conf;
```

4. Update the stream configuration with your domains and backend IPs:

```
map $ssl_preread_server_name $backend {
    your-domain.com    backend-ip:443;
    another-domain.com backend-ip:443;
    default            backend-ip:443;
}
```

5. Setup scheduled jobs for Cloudflare IPv6 updates:

```bash
# Copy the scripts
cp nginxv6.sh ufwv6.sh /usr/local/bin/
chmod +x /usr/local/bin/nginxv6.sh /usr/local/bin/ufwv6.sh

# Add to crontab
(crontab -l 2>/dev/null; echo "0 0 * * * /usr/local/bin/nginxv6.sh") | crontab -
(crontab -l 2>/dev/null; echo "0 0 * * * /usr/local/bin/ufwv6.sh") | crontab -
```

6. Configure UFW (firewall):

```bash
# Allow SSH (important to avoid locking yourself out)
ufw allow ssh

# Run the ufwv6.sh script to allow Cloudflare IPv6 ranges
/usr/local/bin/ufwv6.sh

# Enable UFW
ufw enable
```

### Backend Machine Setup

1. Install required packages:

```bash
apt-get update
apt-get install nginx ufw
```

2. Deploy configuration files:

- Copy `backend-nginx-default.conf` to `/etc/nginx/sites-enabled/`
- Copy `backend-nginx-verify.conf` to `/etc/nginx/sites-enabled/`

3. Update `backend-nginx-verify.conf` with your domain and secret:

```
server_name your-domain.com;
...
if ($http_x_your_header != "your-secret-value") {
    return 403;
}
```

4. Create Cloudflare Edge certificates:

- Generate SSL certificates in Cloudflare dashboard
- Place them in `/home/cert/edgecert.pem` and `/home/cert/edgekey.pem`

5. Configure UFW to only allow frontend connection:

```bash
# Allow SSH (important!)
ufw allow ssh

# Allow connections from frontend
ufw allow from frontend-ip to any port 80
ufw allow from frontend-ip to any port 443

# Enable UFW
ufw enable
```

6. Configure Cloudflare for your domain:

- Set SSL mode to "Full (strict)"
- Add a rule to transform request headers:
  - Destination: "Origin"
  - Add request header: "X-Your-Header: your-secret-value"

## Alternative Approaches

### Using Tailscale

You can further secure the communication between frontend and backend by using Tailscale:

1. Install Tailscale on both machines
2. Connect them to your Tailscale network
3. Configure the frontend to use the Tailscale IP of the backend
4. Block ports 80/443 on the backend's public interface

### Using Cloudflare Tunnel

For even greater security (but higher resource usage):

1. Install Cloudflare Tunnel on the frontend machine
2. Configure the tunnel to point to your backend
3. Block all inbound connections to ports 80/443 on both machines

## Maintenance

- The automatic IPv6 update scripts will run daily
- Monitor logs in `/var/log/nginx/` and `/var/log/cf_ipv6_ufw_update.log`
- Check Cloudflare analytics for attack patterns

## Security Considerations

- Keep all systems updated
- Regularly rotate your secret header value
- Use strong passwords for SSH
- Consider implementing fail2ban
- Add additional security headers in Nginx configurations

## Troubleshooting

### Common Issues

- **403 Forbidden**: Check if the request has the proper X-Your-Header
- **Connection refused**: Check if UFW is blocking the connection
- **Certificate errors**: Verify Edge certificate paths and expiration

### Debug Commands

```bash
# Test Nginx configuration
nginx -t

# Check UFW status
ufw status

# View Nginx access logs
tail -f /var/log/nginx/your-domain.com.access.log

# Check active connections
netstat -tuln | grep -E ':(80|443)'
```
