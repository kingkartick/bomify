#!/usr/bin/env bash
# One-time setup for a fresh Amazon Linux 2023 EC2 instance.
# Run as ec2-user:  bash ec2-setup.sh
set -euo pipefail

# 2 GB swap: a 1 GB free-tier instance cannot build the frontend or run the API without it
if ! swapon --show | grep -q /swapfile; then
  sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# Docker + compose plugin + git
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

echo "Done. Log out and back in so the docker group applies, then deploy the app."
