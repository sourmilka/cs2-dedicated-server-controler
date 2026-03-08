#!/bin/bash
# CS2 Dedicated Server Controller — Oracle Cloud / VPS Setup Script
# Run this on a fresh Ubuntu 22.04+ instance.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/sourmilka/cs2-dedicated-server-controler/main/deploy.sh | bash
#
# Or manually:
#   chmod +x deploy.sh && ./deploy.sh

set -e

APP_DIR="/opt/cs2-controller"
SERVICE_NAME="cs2-controller"
REPO_URL="https://github.com/sourmilka/cs2-dedicated-server-controler.git"

echo "=============================================="
echo "  CS2 Server Controller — VPS Auto-Installer"
echo "=============================================="

# --- System packages ---
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git ufw > /dev/null

# --- Firewall ---
echo "[2/6] Configuring firewall..."
sudo ufw allow 22/tcp   > /dev/null 2>&1 || true
sudo ufw allow 5000/tcp > /dev/null 2>&1 || true
sudo ufw --force enable > /dev/null 2>&1 || true

# --- Clone repo ---
echo "[3/6] Cloning repository..."
if [ -d "$APP_DIR" ]; then
    echo "  -> Updating existing installation..."
    cd "$APP_DIR"
    git pull origin main
else
    sudo git clone "$REPO_URL" "$APP_DIR"
    sudo chown -R "$USER:$USER" "$APP_DIR"
    cd "$APP_DIR"
fi

# --- Python venv ---
echo "[4/6] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt

# --- Environment file ---
echo "[5/6] Configuring environment..."
if [ ! -f "$APP_DIR/.env.production" ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > "$APP_DIR/.env.production" << EOF
# CS2 Controller Environment
# Edit this file, then restart: sudo systemctl restart $SERVICE_NAME

PORT=5000
CS2_ADMIN_PASSWORD=changeme
SECRET_KEY=$SECRET
EOF
    echo "  -> Created .env.production — EDIT THE PASSWORD:"
    echo "     sudo nano $APP_DIR/.env.production"
else
    echo "  -> .env.production already exists, keeping current values."
fi

# --- Systemd service ---
echo "[6/6] Installing systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOF
[Unit]
Description=CS2 Dedicated Server Controller
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env.production
ExecStart=$APP_DIR/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

# --- Done ---
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")
echo ""
echo "=============================================="
echo "  INSTALLED SUCCESSFULLY!"
echo "=============================================="
echo ""
echo "  URL:     http://$PUBLIC_IP:5000"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo "  Restart: sudo systemctl restart $SERVICE_NAME"
echo ""
echo "  IMPORTANT: Set your admin password!"
echo "  sudo nano $APP_DIR/.env.production"
echo "  Then: sudo systemctl restart $SERVICE_NAME"
echo ""
echo "  To update later:"
echo "  cd $APP_DIR && git pull && sudo systemctl restart $SERVICE_NAME"
echo "=============================================="
