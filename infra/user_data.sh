#!/bin/bash
# Vyom EC2 bootstrap — runs once on first boot.
#
# This only sets up the OS-level pieces (nginx, python venv, systemd unit,
# nginx routing). It does NOT deploy application code or start vyom-api —
# that happens in a separate manual step (scp the source + write
# /etc/vyom/vyom.env), since code changes more often than the box itself.
set -euo pipefail

# t3.micro has only 1GB RAM — nginx + FastAPI + two loaded PyTorch models
# need more than that. A swap file trades some latency for not OOM-killing
# the app process; fine for a low-traffic portfolio deployment.
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo "/swapfile none swap sw 0 0" >> /etc/fstab

dnf update -y
dnf install -y nginx python3.11 python3.11-pip git gcc gcc-c++ make

mkdir -p /opt/vyom /etc/vyom /var/www/vyom
python3.11 -m venv /opt/vyom/venv
/opt/vyom/venv/bin/pip install --upgrade pip

cat > /etc/systemd/system/vyom-api.service <<'EOF'
[Unit]
Description=Vyom FastAPI backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/vyom
EnvironmentFile=/etc/vyom/vyom.env
ExecStart=/opt/vyom/venv/bin/uvicorn src.vyom.api.app:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5
User=ec2-user

[Install]
WantedBy=multi-user.target
EOF

rm -f /etc/nginx/conf.d/default.conf

cat > /etc/nginx/conf.d/vyom.conf <<'EOF'
server {
    listen 80 default_server;
    server_name _;

    root /var/www/vyom;
    index index.html;

    # Backend routes — proxied to the FastAPI process on localhost. Kept as
    # explicit prefixes (matching the routers actually mounted in app.py)
    # rather than a catch-all, so unmatched paths fall through to the static
    # frontend below.
    location /query {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;        # required for SSE streaming (/query/stream)
        proxy_read_timeout 300s;
    }
    location /feedback {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
    location /health {
        proxy_pass http://127.0.0.1:8000;
    }
    location /ingest {
        proxy_pass http://127.0.0.1:8000;
    }
    location /docs {
        proxy_pass http://127.0.0.1:8000;
    }
    location /openapi.json {
        proxy_pass http://127.0.0.1:8000;
    }
    location /redoc {
        proxy_pass http://127.0.0.1:8000;
    }

    # Static frontend (Next.js `output: export`) — everything else.
    location / {
        try_files $uri $uri.html $uri/ /index.html;
    }
}
EOF

chown -R ec2-user:ec2-user /opt/vyom /etc/vyom /var/www/vyom

systemctl daemon-reload
systemctl enable nginx
systemctl enable vyom-api
systemctl start nginx
