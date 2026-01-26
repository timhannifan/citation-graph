#!/bin/bash
# Setup script to install Docker and Docker Compose on EC2 Amazon Linux 2023
# Uses Amazon's Docker package + standalone docker-compose

set -e

echo "=== Installing Docker on EC2 Amazon Linux 2023 ==="

# Install Docker from Amazon Linux repos (this works!)
echo "Installing Docker from Amazon Linux repos..."
sudo yum install -y docker

# Start and enable Docker
echo "Starting Docker service..."
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
echo "Adding user to docker group..."
sudo usermod -aG docker $USER

# Install Docker Compose as standalone binary
echo "Installing Docker Compose standalone..."
DOCKER_COMPOSE_VERSION="v2.24.5"
sudo curl -L "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
    -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Install Docker Buildx
echo "Installing Docker Buildx..."
BUILDX_VERSION="v0.17.1"
mkdir -p ~/.docker/cli-plugins
curl -SL "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64" \
    -o ~/.docker/cli-plugins/docker-buildx
chmod +x ~/.docker/cli-plugins/docker-buildx

# Verify installations
echo ""
echo "=== Verifying installations ==="
git --version
docker --version
docker-compose --version
docker buildx version

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "IMPORTANT: You need to log out and log back in for group changes to take effect."
echo "After logging back in, verify with: docker ps"
echo ""
echo "NOTE: Use 'docker-compose' (with hyphen) instead of 'docker compose' (with space)"
