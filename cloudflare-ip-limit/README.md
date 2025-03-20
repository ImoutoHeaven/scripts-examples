# Secure Web Hosting with Nginx Stream Proxy

This repository provides a solution for securing your web hosting infrastructure using a two-tiered architecture with Nginx stream proxy and UFW (Uncomplicated Firewall).

## Architecture Overview

This setup creates a secure two-tiered architecture:

1. **Frontend Machine**: Acts as a reverse proxy using Nginx's stream module to forward TCP traffic to the backend. Only accepts connections from CloudFlare IPs.

2. **Backend Machine**: Hosts the actual web server (Nginx), secured by UFW to only accept connections from the frontend machine.

```
Internet Users → CloudFlare → Frontend Nginx Stream Proxy → Backend Web Server
                    ↑               ↑                           ↑
                    │               │                           │
           IP Filtering        Only accepts               Only accepts
           at CloudFlare      CloudFlare IPs             Frontend IP
```

## Quick Setup Guide

### Frontend Machine Setup

1. Install required packages:
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install nginx nginx-extras curl ufw -y
   ```

2. Create necessary directories:
   ```bash
   sudo mkdir -p /etc/nginx
   sudo touch /etc/nginx/cloudflare-ipv6.conf
   ```

3. Copy the configuration files from this repository:
   ```bash
   # Copy Nginx stream configuration
   sudo cp nginx-stream-example.conf /etc/nginx/nginx-stream-example.conf
   
   # Copy IPv6 update scripts
   sudo cp nginxv6.sh /usr/local/bin/
   sudo cp ufwv6.sh /usr/local/bin/
   ```

4. Update the configuration to use your backend server IP:
   ```bash
   # Replace placeholders in the configuration file
   sudo sed -i 's/<some_ip>:<some_port>/YOUR_BACKEND_IP:443/g' /etc/nginx/nginx-stream-example.conf
   sudo sed -i 's/<default_ip>:<default_port>/YOUR_BACKEND_IP:443/g' /etc/nginx/nginx-stream-example.conf
   sudo sed -i 's/<some_ip>:<some_addr>/YOUR_BACKEND_IP:80/g' /etc/nginx/nginx-stream-example.conf
   ```

5. Include the stream configuration in the main Nginx config:
   ```bash
   # Add the include directive to nginx.conf
   sudo sed -i '/events {/a include /etc/nginx/nginx-stream-example.conf;' /etc/nginx/nginx.conf
   ```

6. Make the scripts executable:
   ```bash
   sudo chmod +x /usr/local/bin/nginxv6.sh
   sudo chmod +x /usr/local/bin/ufwv6.sh
   ```

7. Create log directories:
   ```bash
   sudo mkdir -p /var/log/nginx
   sudo touch /var/log/nginx/stream_error.log
   sudo touch /var/log/nginx/stream_access_80.log
   sudo touch /var/log/nginx/stream_access_443.log
   ```

8. Run the scripts to populate the CloudFlare IP configurations:
   ```bash
   sudo /usr/local/bin/nginxv6.sh
   sudo /usr/local/bin/ufwv6.sh
   ```

9. Set up cron jobs to keep CloudFlare IPs updated:
   ```bash
   # Add to crontab
   (crontab -l 2>/dev/null; echo "0 0 * * * /usr/local/bin/nginxv6.sh >> /var/log/nginxv6.log 2>&1") | crontab -
   (crontab -l 2>/dev/null; echo "0 1 * * * /usr/local/bin/ufwv6.sh >> /var/log/ufwv6.log 2>&1") | crontab -
   ```

10. Configure UFW to allow SSH and enable the firewall:
    ```bash
    sudo ufw allow ssh
    sudo ufw enable
    ```

11. Restart Nginx:
    ```bash
    sudo systemctl restart nginx
    ```

### Backend Machine Setup

1. Install required packages:
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install nginx ufw -y
   ```

2. Copy the Nginx configuration for handling real IPs:
   ```bash
   # Assume you have your own site configuration
   # Add the CloudFlare real IP handling to your site config
   sudo cp target_machine_nginx_http_site_example.conf /etc/nginx/snippets/cloudflare-real-ip.conf
   ```

3. Update the configuration with your frontend server IP:
   ```bash
   sudo sed -i 's/<front_end_machine_ipv4>/YOUR_FRONTEND_IP/g' /etc/nginx/snippets/cloudflare-real-ip.conf
   ```

4. Include the CloudFlare real IP configuration in your site config:
   ```bash
   # Add to your site configuration
   echo 'include /etc/nginx/snippets/cloudflare-real-ip.conf;' | sudo tee -a /etc/nginx/sites-available/default
   ```

5. Configure UFW to only allow connections from the frontend machine:
   ```bash
   # Allow SSH
   sudo ufw allow ssh
   
   # Allow the frontend machine for HTTP and HTTPS
   sudo ufw allow from YOUR_FRONTEND_IP to any port 80 proto tcp
   sudo ufw allow from YOUR_FRONTEND_IP to any port 443 proto tcp
   
   # Enable UFW
   sudo ufw enable
   ```

6. Restart Nginx:
   ```bash
   sudo systemctl restart nginx
   ```

## Alternative Security Options

### Using Tailscale for Secure Communication

For enhanced security, you can use Tailscale to create a private network between your frontend and backend servers:

1. Install Tailscale on both machines:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   ```

2. Set up Tailscale on both machines:
   ```bash
   sudo tailscale up
   ```

3. Configure UFW on the backend to only allow the Tailscale IP of the frontend:
   ```bash
   # Get Tailscale IP of frontend machine
   TAILSCALE_IP=$(tailscale ip -4)
   
   # Update UFW rules
   sudo ufw allow from $TAILSCALE_IP to any port 80 proto tcp
   sudo ufw allow from $TAILSCALE_IP to any port 443 proto tcp
   ```

4. Update the Nginx stream configuration on the frontend to use the Tailscale IP of the backend.

### Using CloudFlare Tunnels

For maximum security (at the cost of more resources), you can use CloudFlare Tunnels to completely eliminate the need for inbound ports:

1. Install the CloudFlare Tunnel client on your backend machine:
   ```bash
   wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared-linux-amd64.deb
   ```

2. Set up and configure CloudFlare Tunnels according to CloudFlare documentation.

3. With this configuration, you can completely close ports 80 and 443 on both machines:
   ```bash
   sudo ufw delete allow 80/tcp
   sudo ufw delete allow 443/tcp
   ```

## File Descriptions

- `nginx-stream-example.conf`: Nginx stream module configuration for the frontend server
- `nginxv6.sh`: Script to update CloudFlare IPv6 allowlist for Nginx
- `ufwv6.sh`: Script to update UFW rules with CloudFlare IPv6 ranges
- `target_machine_nginx_http_site_example.conf`: Example configuration for the backend Nginx server

## Maintenance

- The cron jobs will automatically update the CloudFlare IP ranges daily
- Check logs in `/var/log/nginx/` for any issues
- Monitor UFW logs in `/var/log/ufw.log`

## Security Benefits

- Backend server remains hidden from direct internet access
- Traffic is filtered twice (CloudFlare IPs at frontend, frontend IP at backend)
- CloudFlare WAF protection is maintained
- Automatic updating of CloudFlare IP allowlists

## Troubleshooting

If you experience issues:

1. Check Nginx logs:
   ```bash
   sudo tail -f /var/log/nginx/error.log
   sudo tail -f /var/log/nginx/stream_error.log
   ```

2. Verify UFW status:
   ```bash
   sudo ufw status verbose
   ```

3. Test connectivity:
   ```bash
   # From frontend to backend
   telnet BACKEND_IP 80
   telnet BACKEND_IP 443
   ```

4. Verify script execution:
   ```bash
   sudo tail -f /var/log/nginxv6.log
   sudo tail -f /var/log/ufwv6.log
   ```
