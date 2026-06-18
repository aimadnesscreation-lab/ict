# Local Machine Setup (Linux Mint)

This guide covers setting up the ICT trading system to run as a **background systemd service** on your Linux Mint machine. No terminal window needed — it starts on boot, restarts on crash, and logs everything automatically.

---

## Prerequisites

- Python 3.12+
- Node.js 18+ (for dashboard)
- Git
- Binance API keys (for live execution)

---

## One-Time Setup

### 1. Clone & install

```bash
cd ~/Documents
git clone <your-repo-url> trading
cd trading

# Python virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Dashboard dependencies
cd dashboard
npm install
cd ..
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env   # add your BINANCE_API_KEY, BINANCE_SECRET, DISCORD_WEBHOOK_URL
```

### 3. Create the systemd service

```bash
sudo tee /etc/systemd/system/ict-trading.service << 'EOF'
[Unit]
Description=ICT Trading Platform
After=network-online.target

[Service]
Type=simple
User=zainu
WorkingDirectory=/home/zainu/Documents/trading
ExecStart=/home/zainu/Documents/trading/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ict-trading
sudo systemctl start ict-trading
```

### 4. Verify it's running

```bash
sudo systemctl status ict-trading
curl http://localhost:8000/api/health
```

---

## Daily Operations

```bash
# View live logs
sudo journalctl -u ict-trading -f

# Restart after a git pull
git pull
sudo systemctl restart ict-trading

# Stop the service
sudo systemctl stop ict-trading

# Check recent logs
sudo journalctl -u ict-trading --since "30 min ago" --no-pager
```

---

## Development Workflow

```
GCloud Shell (develop)              Linux Mint (run)
────────────────────────────         ─────────────────────────
  git add -A
  git commit -m "fix: ..."
  git push                  ──►      git pull
                                     sudo systemctl restart ict-trading
                                     # close terminal — runs forever
```

---

## Accessing the Dashboard

Once the service is running:

| URL | What |
|-----|------|
| `http://localhost:8000/dashboard` | Full dashboard |
| `http://localhost:8000/api/health` | System health |
| `http://localhost:8000/signals` | Recent signals |

To access from another device on your network (phone, tablet):

```bash
# Find your local IP
ip addr show | grep "inet 192"

# Then open http://192.168.x.x:8000/dashboard from any device on your network
```

---

## Troubleshooting

```bash
# Service won't start
sudo journalctl -u ict-trading --since "10 min ago" --no-pager

# Python module not found
# Make sure venv is active and deps are installed:
source ~/Documents/trading/venv/bin/activate
pip install -r ~/Documents/trading/requirements.txt

# Port 8000 already in use
sudo ss -tlnp | grep 8000   # find what's using it
sudo systemctl stop ict-trading  # then fix the conflict

# Binance connection failed
# Check your .env file has correct API keys
# Run the connection test:
source ~/Documents/trading/venv/bin/activate
python ~/Documents/trading/test_live_connection.py
```
