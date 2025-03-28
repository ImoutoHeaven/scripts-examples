# Secure Alist Deployment with Dual-Layer Nginx and Cloudflare Protection

This guide explains how to set up a secure Alist deployment using a dual-layer proxy architecture with Cloudflare protection.

## Architecture Overview

This setup employs a multi-layered security approach:

1. **Cloudflare**: Acts as the outermost security layer, providing DDoS protection, caching, and SSL
2. **Front-end Server**: Only accepts connections from Cloudflare IPs and forwards to the back-end
3. **Back-end Server**: Hosts Alist and verifies requests via custom headers
4. **Cloudflare Worker**: Provides additional request verification and handling, which should be proxy urls setup for AList configuration for your storage backends.

![Architecture Diagram]
```
User → Cloudflare → Front-end Server → Back-end Server → Alist → Cloudflare Workers → Storage Backends
```

## Prerequisites

- Two servers (VPS/cloud instances) for front-end and back-end
- Domain name configured with Cloudflare
- Cloudflare account with Workers enabled
- Nginx installed on both servers
- UFW (Uncomplicated Firewall) installed on front-end server
- Alist installed on back-end server

## Installation Guide

### 1. Clone This Repository

Clone this repository to both your front-end and back-end servers.

### 2. Front-end Server Setup

#### 2.1 Configure Nginx for Stream Module

1. Make sure Nginx is installed with the stream module:
   ```bash
   nginx -V | grep with-stream
   ```
   If not shown, reinstall Nginx with stream support.

2. Configure Nginx:
   ```bash
   # Edit nginx.conf
   sudo nano /etc/nginx/nginx.conf
   
   # Add the following line between events{} and http{} sections:
   include /etc/nginx/frontend-nginx-stream.conf;
   ```

3. Copy configuration files:
   ```bash
   sudo cp frontend-nginx-stream.conf /etc/nginx/
   sudo cp frontend-nginx-http-to-https.conf /etc/nginx/sites-available/
   ```

4. Modify the configurations:
   ```bash
   sudo nano /etc/nginx/frontend-nginx-stream.conf
   # Replace <some_ip>, <some_port>, <default_ip>, <default_port> with your back-end server info
   
   sudo ln -s /etc/nginx/sites-available/frontend-nginx-http-to-https.conf /etc/nginx/sites-enabled/
   ```

#### 2.2 Setup Cloudflare IP Range Updates

1. Install the IP update scripts:
   ```bash
   sudo cp ufwv6.sh nginxv6.sh /usr/local/bin/
   sudo chmod +x /usr/local/bin/ufwv6.sh
   sudo chmod +x /usr/local/bin/nginxv6.sh
   ```

2. Create initial configuration:
   ```bash
   sudo /usr/local/bin/nginxv6.sh
   ```

3. Configure UFW:
   ```bash
   sudo ufw allow ssh
   sudo /usr/local/bin/ufwv6.sh
   sudo ufw enable
   ```

4. Setup auto-updates with cron:
   ```bash
   (crontab -l 2>/dev/null; echo "0 0 * * * /usr/local/bin/ufwv6.sh") | crontab -
   (crontab -l 2>/dev/null; echo "0 0 * * * /usr/local/bin/nginxv6.sh") | crontab -
   ```

### 3. Back-end Server Setup

#### 3.1 Configure Nginx

1. Copy configuration files:
   ```bash
   sudo cp backend-nginx-verify.conf /etc/nginx/sites-available/
   sudo cp backend-nginx-default.conf /etc/nginx/sites-available/default
   ```

2. Modify the configurations:
   ```bash
   sudo nano /etc/nginx/sites-available/backend-nginx-verify.conf
   # Replace <some_domain> with your domain
   # Replace <front_end_machine_ipv4> with your front-end server's IP
   # Set <your secret> to a strong random string
   ```

3. Create symbolic links:
   ```bash
   sudo ln -s /etc/nginx/sites-available/backend-nginx-verify.conf /etc/nginx/sites-enabled/
   ```

#### 3.2 Setup Cloudflare IP Ranges for Real IP Module

1. Install the update script:
   ```bash
   sudo cp nginx-real-ip.sh /usr/local/bin/
   sudo chmod +x /usr/local/bin/nginx-real-ip.sh
   ```

2. Create initial configuration:
   ```bash
   sudo /usr/local/bin/nginx-real-ip.sh
   ```

3. Setup auto-updates with cron:
   ```bash
   (crontab -l 2>/dev/null; echo "0 0 * * * /usr/local/bin/nginx-real-ip.sh") | crontab -
   ```

#### 3.3 Cloudflare Edge Certificate

1. In Cloudflare dashboard, go to SSL/TLS → Origin Server
2. Create a new certificate (15-year validity)
3. Save the certificate and key to `/home/cert/`:
   ```bash
   sudo mkdir -p /home/cert
   sudo nano /home/cert/edgecert.pem   # Paste certificate content
   sudo nano /home/cert/edgekey.pem    # Paste key content
   sudo chmod 600 /home/cert/*.pem
   ```

### 4. Cloudflare Worker Setup

1. In Cloudflare dashboard, go to Workers & Pages
2. Create a new worker
3. Edit the worker code with the content from `alist-cf-mod.js`
4. Replace the following variables at the top of the script:
   - `YOUR_ADDRESS`: Your backend Alist API URL (e.g., https://your-domain.com)
   - `YOUR_TOKEN`: Your Alist token
   - `YOUR_WORKER_ADDRESS`: Your worker URL
   - `YOUR_HEADER`: The header name used for verification (must match X-Your-Header in Nginx config)
   - `YOUR_HEADER_SECRET`: Secret value for verification (must match <your secret> in Nginx config)

### 5. Cloudflare Configuration

#### 5.1 DNS Settings
1. Add an AAAA record pointing to your front-end server ipv6 address (not ipv4 with A record)
2. Enable proxy (orange cloud) for the record

#### 5.2 SSL/TLS Settings
1. Set SSL/TLS mode to "Full (strict)"
2. Enable "Authenticated origin pulls" if desired

#### 5.3 Create Cloudflare Transform Rule
1. Go to Rules → Transform Rules
2. Create a new rule to add your custom header:
   - Name: "Add Secret Header"
   - When: "All incoming requests"
   - Then: "Modify request header" → "Add" → "X-Your-Header" → "<your secret>"

### 6. Restart Services

1. Front-end server:
   ```bash
   sudo nginx -t
   sudo systemctl restart nginx
   ```

2. Back-end server:
   ```bash
   sudo nginx -t
   sudo systemctl restart nginx
   ```

## Security Considerations

1. **Private Communication**: Use Tailscale, WireGuard, or other VPN solutions between front-end and back-end for added security
2. **Regular Updates**: Keep all scripts updated with the latest Cloudflare IP ranges
3. **Firewall Settings**: Only allow the necessary ports (22, 80, 443) on the front-end server
4. **Strong Secrets**: Use strong, random strings for your custom headers
5. **Monitoring**: Implement log monitoring to detect unusual access patterns

## Troubleshooting

### Checking Nginx Syntax
```bash
sudo nginx -t
```

### Viewing Logs
```bash
# Front-end logs
sudo tail -f /var/log/nginx/stream_access.log
sudo tail -f /var/log/nginx/stream_error.log

# Back-end logs 
sudo tail -f /var/log/nginx/<your-domain>.access.log
sudo tail -f /var/log/nginx/<your-domain>.error.log
```

### Common Issues

1. **403 Forbidden**: Verify Cloudflare IP ranges are updated correctly
2. **Custom Header Issues**: Confirm transform rules are properly configured in Cloudflare
3. **SSL Errors**: Check certificates and SSL settings

## Maintenance

Run the update scripts regularly to ensure Cloudflare IP ranges are current:

```bash
# Front-end server
sudo /usr/local/bin/ufwv6.sh
sudo /usr/local/bin/nginxv6.sh

# Back-end server
sudo /usr/local/bin/nginx-real-ip.sh
```
