# Cloudflare-Protected Nginx Proxy Architecture

A secure web server architecture using Cloudflare as the edge network, with a two-tier proxy setup to enhance security and prevent direct access to backend services.

## Architecture Overview

This project implements a secure multi-tier architecture for web services with the following components:

1. **Cloudflare** - Acts as the edge network and provides WAF, DDoS protection, and edge certificates
2. **Frontend Server** - Receives traffic from Cloudflare and forwards it to the backend
3. **Backend Server** - Hosts the actual web application (Alist in this example)

```
                   ┌────────────┐     ┌───────────────┐     ┌───────────────┐
                   │            │     │               │     │               │
Internet ─────────▶│ Cloudflare ├────▶│ Frontend      ├────▶│ Backend       │
                   │            │     │ Nginx Proxy   │     │ Nginx + Alist │
                   └────────────┘     └───────────────┘     └───────────────┘
                        WAF            Stream Proxy          Application Server
                        DDoS Protection
                        Edge Certificates
```

### Security Features

- **IP Filtering**: Only Cloudflare IPs can access the frontend server
- **Header Verification**: Custom headers verify traffic originated from Cloudflare
- **Firewall Rules**: UFW restricts connections between servers
- **SNI-based Routing**: Frontend supports multiple backends based on SNI
- **Bot Protection**: Blocks common web crawlers
- **Automatic Updates**: Scripts automatically update Cloudflare IP ranges

## Installation

### Prerequisites

- Two servers (frontend and backend) with Ubuntu/Debian
- Domain name configured in Cloudflare with proxied AAAA records
- Nginx and UFW installed on both servers

### Frontend Server Setup

1. Install required packages:

```bash
apt update
apt install nginx nginx-extras curl ufw
```

2. Configure Nginx stream module:

```bash
# Copy the frontend-nginx-stream.conf to /etc/nginx/
cp frontend-nginx-stream.conf /etc/nginx/

# Edit nginx.conf to include the stream configuration
vim /etc/nginx/nginx.conf
# Add between events{} and http{} blocks:
include /etc/nginx/frontend-nginx-stream.conf;
```

3. Create the CloudFlare IPv6 configuration file:

```bash
touch /etc/nginx/cloudflare-ipv6.conf
chmod +x nginxv6.sh
./nginxv6.sh
```

4. Configure UFW to only allow Cloudflare IPs:

```bash
# Allow SSH
ufw allow ssh

# Run the UFW update script
chmod +x ufwv6.sh
./ufwv6.sh

# Enable UFW
ufw enable
```

5. Setup cron jobs to keep Cloudflare IP ranges updated:

```bash
crontab -e
# Add these lines:
0 0 * * * /path/to/nginxv6.sh
0 0 * * * /path/to/ufwv6.sh
```

### Backend Server Setup

1. Install required packages:

```bash
apt update
apt install nginx ufw
```

2. Configure Nginx:

```bash
# Copy config files
cp backend-nginx-default.conf /etc/nginx/sites-available/default
cp backend-nginx-verify.conf /etc/nginx/sites-available/<your-domain>

# Edit configuration files and replace placeholders:
# <some_domain> - Your domain name
# <your secret> - A secret string for header verification
# <front_end_machine_ipv4> - IP address of your frontend server

# Enable site configuration
ln -s /etc/nginx/sites-available/<your-domain> /etc/nginx/sites-enabled/
```

3. Install Alist (or your preferred application):

```bash
# Alist installation instructions: https://alist.nn.ci/guide/install/
```

4. Configure UFW to only allow the frontend server:

```bash
# Allow SSH
ufw allow ssh

# Allow frontend server access
ufw allow from <frontend-ip> to any port 80
ufw allow from <frontend-ip> to any port 443

# Enable UFW
ufw enable
```

### Cloudflare Configuration

1. Set up your domain in Cloudflare with proxied AAAA records pointing to your frontend server

2. Enable Full (Strict) SSL mode

3. Create an Edge Certificate for your domain and download the certificate and key:
   - Place them in `/home/cert/edgecert.pem` and `/home/cert/edgekey.pem` on your backend server

4. Create a Transform Rule in Cloudflare:
   - Go to Rules → Transform Rules
   - Create a new rule that adds a custom header:
     - Header name: `X-Your-Header`
     - Value: `<your secret>` (same as configured in backend-nginx-verify.conf)

## Usage

After setup is complete, your application should be accessible through your domain, with traffic flowing through:

1. Client → Cloudflare (Edge Network)
2. Cloudflare → Frontend Server (Stream Proxy)
3. Frontend Server → Backend Server (Application)

## Alternative Configurations

### Using Tailscale for Secure Backend Communication

For enhanced security, you can use Tailscale to create a private network between your frontend and backend servers:

1. Install Tailscale on both servers:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   ```

2. Connect both servers to your Tailscale network:
   ```bash
   tailscale up
   ```

3. Update your frontend proxy configuration to use the Tailscale IP of your backend server

4. Update UFW rules on the backend to only allow connections from the Tailscale network

### Using Cloudflare Tunnel

For environments where you cannot expose ports 80/443 to the internet:

1. Install cloudflared on your backend server:
   ```bash
   curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   dpkg -i cloudflared.deb
   ```

2. Authenticate and create a tunnel:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create <tunnel-name>
   ```

3. Configure the tunnel to point to your local application:
   ```bash
   # config.yml
   tunnel: <tunnel-id>
   credentials-file: /root/.cloudflared/<tunnel-id>.json
   
   ingress:
     - hostname: <your-domain>
       service: http://localhost:5244  # Alist port
     - service: http_status:404
   ```

4. Run the tunnel:
   ```bash
   cloudflared tunnel run <tunnel-name>
   ```

5. Create a systemd service to ensure the tunnel runs on startup

## Maintenance

- Regularly check logs for unauthorized access attempts:
  ```bash
  tail -f /var/log/nginx/*.log
  ```

- Verify UFW rules are correctly applied:
  ```bash
  ufw status verbose
  ```

- Test Nginx configuration after making changes:
  ```bash
  nginx -t
  ```

- Check that the Cloudflare IP update scripts are running:
  ```bash
  grep "Cloudflare" /var/log/syslog
  ```

## Security Considerations

- **Edge Certificates**: The 15-year Cloudflare Edge certificates don't require manual renewal
- **Header Verification**: Prevents direct access to your backend server
- **Bot Protection**: Blocks common web crawlers to reduce server load
- **IP Restrictions**: Only Cloudflare and authorized IPs can access your servers
- **Stream Proxy**: Enables TCP forwarding without exposing backend details

## Troubleshooting

### Common Issues

1. **Connection refused errors**:
   - Check that your UFW rules allow traffic between the servers
   - Verify Nginx is running on both servers
   - Check that the backend application is running

2. **403 Forbidden errors**:
   - Verify the Cloudflare header is being properly set
   - Check that your IP ranges are up-to-date
   - Ensure the correct SNI is being used

3. **SSL errors**:
   - Verify that your certificates are properly installed
   - Check that the certificate paths in the Nginx configuration are correct
   - Ensure Cloudflare is set to Full (Strict) SSL mode

### Log Locations

- Frontend Nginx logs: `/var/log/nginx/stream_*.log`
- Backend Nginx logs: `/var/log/nginx/<your-domain>.*.log`
- Cloudflare IP update logs: `/var/log/cf_ipv6_ufw_update.log`
