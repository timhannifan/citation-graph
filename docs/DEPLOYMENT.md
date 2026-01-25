# Production Deployment Guide

Deploy OpenWebUI to a production server on EC2.

## Prerequisites

- An EC2 instance with Docker and Docker Compose installed
- Ports 80 and 22 open in your security group

### Minimum Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 vCPU | 2+ vCPU |
| RAM | 2 GB | 4 GB |
| Disk | 20 GB | 40 GB |

**Recommended instance**: `t3a.small` (2 vCPU, 2GB RAM, ~$13/mo)

Based on container limits: OpenWebUI (1.5 CPU, 1.5GB) + MCP Server (0.5 CPU, 256MB) + Caddy (256MB)

## Quick Deploy

```bash
# On your server
git clone <repo-url> openweb
cd openweb

# Configure
cp env.example .env
# Edit .env with your EC2 public IP

# Start
make prod
```

## Step-by-Step Deployment

### 1. Server Setup (Amazon Linux 2023)

```bash
# Run the setup script (installs Docker, Docker Compose, and Git)
./scripts/setup-ec2-docker.sh

# Log out and back in for docker group
exit
```

### 2. Configure Environment

Edit `.env` with your EC2 public IP address:

```bash
WEBUI_SECRET_KEY=your-random-secret-key-here
SERVER_IP=YOUR_EC2_IP_ADDRESS
WEBUI_BASE_URL=http://YOUR_EC2_IP_ADDRESS
WEBUI_URL=http://YOUR_EC2_IP_ADDRESS
WEBUI_CSRF_TRUSTED_ORIGINS=http://YOUR_EC2_IP_ADDRESS
CORS_ALLOW_ORIGINS=http://YOUR_EC2_IP_ADDRESS
```

Generate a secret key:
```bash
openssl rand -hex 32
```

### 3. Deploy

```bash
make prod
```

### 4. Verify

1. Check services are running:
   ```bash
   docker-compose -f docker-compose.yaml -f docker-compose.prod.yaml ps
   ```

2. Check Caddy logs:
   ```bash
   docker-compose -f docker-compose.yaml -f docker-compose.prod.yaml logs webserver
   ```

3. Access http://YOUR_EC2_IP_ADDRESS

**Services running:**
- OpenWebUI: Main web interface
- MCP Server: Tool server at port 8090
- Caddy: Reverse proxy handling HTTP traffic

### 5. Configure OpenRouter

After accessing OpenWebUI:

1. Go to **Admin Settings** → **Connections**
2. Click **Manage OpenAI Connections** → **Add Connection**
3. Set:
   - **URL**: `https://openrouter.ai/api/v1`
   - **API Key**: Your OpenRouter API key
4. Save

## Security Notes

This setup uses HTTP (not HTTPS) since SSL certificates require a domain name. For production use with sensitive data, consider:

1. **Use a domain name**: Point a domain to your EC2 IP and update the Caddyfile for automatic HTTPS
2. **Use a VPN or SSH tunnel**: Access the server through a secure tunnel
3. **Restrict access by IP**: Configure your EC2 security group to only allow your IP

## Firewall / Security Group

Ensure your EC2 security group allows:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP | SSH access |
| 80 | TCP | Your IP or 0.0.0.0/0 | HTTP access |

## Updating

### Manual Update

```bash
cd ~/openweb
git pull origin main
docker-compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d --pull always --build
docker image prune -f
```

### Manual Deployment (GitHub Actions)

The repo includes a workflow that can be manually triggered to deploy to EC2.

**Setup GitHub Secrets:**

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Add these secrets:

| Secret | Value |
|--------|-------|
| `EC2_HOST` | Your EC2 public IP address |
| `EC2_USER` | SSH username (e.g., `ec2-user`) |
| `EC2_SSH_KEY` | Your private SSH key (contents of `.pem` file) |

**How to deploy:**

1. Go to your repo → **Actions** tab
2. Select **Deploy to Production** workflow
3. Click **Run workflow** button
4. Select the branch (usually `main`) and click **Run workflow**

The workflow will:
1. SSH to your server
2. Pull latest code
3. Pull latest Docker images
4. Restart services

## Backup

```bash
# Backup OpenWebUI data
# Note: Volume name is based on your directory name (e.g., openweb_open-webui-data)
# Check actual volume name with: docker volume ls
BACKUP_DIR="./backups/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"
docker run --rm -v openweb_open-webui-data:/data -v "$BACKUP_DIR":/backup alpine tar czf /backup/openwebui.tar.gz -C /data .
```

## Troubleshooting

### OpenWebUI Not Loading

```bash
# Check service
docker-compose -f docker-compose.yaml -f docker-compose.prod.yaml ps

# Check logs
docker-compose -f docker-compose.yaml -f docker-compose.prod.yaml logs open-webui
```

## Support

- Caddy docs: https://caddyserver.com/docs/
- OpenWebUI docs: https://docs.openwebui.com/
- OpenRouter: https://openrouter.ai/docs
