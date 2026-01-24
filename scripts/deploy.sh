#!/bin/bash
# Deploy to EC2 via git
# Usage: ./scripts/deploy.sh [branch]
#   branch defaults to 'main'

set -e

BRANCH="${1:-main}"
SERVER="${EC2_USER:-ec2-user}@${EC2_HOST}"

if [ -z "$EC2_HOST" ]; then
    echo "Error: EC2_HOST environment variable not set"
    echo "Usage: EC2_HOST=your-ec2-ip ./scripts/deploy.sh [branch]"
    exit 1
fi

echo "=== Deploying branch: $BRANCH to $SERVER ==="

ssh $SERVER << EOF
cd ~/openweb
git fetch origin
git checkout $BRANCH
git pull origin $BRANCH
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d --pull always --build
docker image prune -f
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml ps
EOF

echo "=== Deployment complete! ==="
