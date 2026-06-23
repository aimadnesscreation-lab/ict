#!/usr/bin/env bash
set -e

# ────────────────────────────────────────────────────────────
#  ICT Trading Pipeline — Local Startup Script
#  Starts the API server + dashboard with one command.
# ────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Step 1: Check prerequisites ─────────────────────────────
info "Checking prerequisites..."

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python not found. Install Python 3.10+ and try again."
    exit 1
fi

PY_VER=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
info "Python $PY_VER found ($PYTHON)"

if ! command -v node &>/dev/null; then
    err "Node.js not found. Install Node.js 18+ and try again."
    exit 1
fi
NODE_VER=$(node --version 2>&1)
info "Node $NODE_VER found"

if ! command -v npm &>/dev/null; then
    err "npm not found. Install npm and try again."
    exit 1
fi
info "npm $(npm --version) found"

# ── Step 2: Check .env ──────────────────────────────────────
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        warn ".env not found. Copying .env.example to .env..."
        cp .env.example .env
        warn "Edit .env with your Binance API credentials before running."
        warn "See setup.md for instructions."
    else
        err ".env and .env.example not found."
        exit 1
    fi
fi

if grep -q "^BINANCE_API_KEY=$" .env 2>/dev/null || grep -q "^BINANCE_API_KEY=your_" .env 2>/dev/null; then
    warn "BINANCE_API_KEY is empty or placeholder in .env"
    warn "The server will start but Binance trading will be disabled."
    warn "Edit .env with your credentials to enable live execution."
elif grep -q "^BINANCE_SECRET=$" .env 2>/dev/null || grep -q "^BINANCE_SECRET=your_" .env 2>/dev/null; then
    warn "BINANCE_SECRET is empty or placeholder in .env"
    warn "Edit .env with your credentials to enable live execution."
fi

ok ".env found"

# ── Step 3: Python virtual environment ──────────────────────
if [ ! -d "venv" ]; then
    info "Creating virtual environment..."
    $PYTHON -m venv venv
    ok "Virtual environment created"
fi

source venv/bin/activate
ok "Virtual environment activated"

# ── Step 4: Install dependencies ────────────────────────────
if [ ! -f "venv/.deps_installed" ]; then
    info "Installing Python dependencies..."
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    touch venv/.deps_installed
    ok "Python dependencies installed"
else
    info "Python dependencies already installed (skip pip install)"
fi

if [ ! -d "dashboard/node_modules" ]; then
    info "Installing dashboard dependencies..."
    cd dashboard
    npm install --silent
    cd "$SCRIPT_DIR"
    ok "Dashboard dependencies installed"
else
    info "Dashboard dependencies already installed (skip npm install)"
fi

# ── Step 5: Quick connection test ────────────────────────────
if [ -f "test_live_connection.py" ]; then
    info "Running connection test..."
    TEST_OUTPUT=$(python test_live_connection.py 2>&1) || true
    echo "$TEST_OUTPUT"
    if echo "$TEST_OUTPUT" | grep -q "✅ ALL"; then
        ok "Binance demo connection verified"
    else
        warn "Connection test did not pass all checks — check your .env credentials."
        warn "The server will start but exchange execution may not work."
    fi
else
    warn "test_live_connection.py not found — skipping connection test."
fi

# ── Step 6: Check port availability ────────────────────────────
if command -v lsof &>/dev/null; then
    if lsof -ti:8000 &>/dev/null; then
        err "Port 8000 is already in use. Stop the existing process and try again."
        exit 1
    fi
    if lsof -ti:5173 &>/dev/null; then
        err "Port 5173 is already in use. Stop the existing process and try again."
        exit 1
    fi
    ok "Ports 8000 and 5173 are available"
fi

# ── Cleanup handler ─────────────────────────────────────────
cleanup() {
    echo ""
    info "Shutting down..."
    if [ -n "$API_PID" ]; then
        kill "$API_PID" 2>/dev/null && wait "$API_PID" 2>/dev/null
        ok "API server stopped"
    fi
    if [ -n "$DASHBOARD_PID" ]; then
        kill "$DASHBOARD_PID" 2>/dev/null && wait "$DASHBOARD_PID" 2>/dev/null
        ok "Dashboard stopped"
    fi
    deactivate 2>/dev/null
    info "Goodbye."
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Step 7: Start API server ────────────────────────────────
echo ""
info "Starting API server (uvicorn api.main:app)..."
uvicorn api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Wait for API to be ready
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
    ok "API server ready at http://localhost:8000"
    
    # Show a quick health summary
    HEALTH=$(curl -s http://localhost:8000/api/health)
    ETH=$(echo "$HEALTH" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(f'\${d[\"eth_price\"]:,.0f}')" 2>/dev/null || echo "?")
    BIAS=$(echo "$HEALTH" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d['htf_bias'])" 2>/dev/null || echo "?")
    info "ETH: $ETH  |  HTF Bias: ${BIAS}"
else
    warn "API server may not be ready yet. Check http://localhost:8000/api/health"
fi

# ── Step 8: Start dashboard ─────────────────────────────────
if [ -d "dashboard" ]; then
    info "Starting dashboard (Vite dev server)..."
    cd dashboard
    VITE_API_URL=http://localhost:8000 npm run dev &
    DASHBOARD_PID=$!
    cd "$SCRIPT_DIR"
    ok "Dashboard starting at http://localhost:5173 (→ API at http://localhost:8000)"
fi

# ── Summary ──────────────────────────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  All systems running!${NC}"
echo ""
echo -e "  ${CYAN}API:${NC}        http://localhost:8000"
echo -e "  ${CYAN}Dashboard:${NC}  http://localhost:5173"
echo -e "  ${CYAN}Health:${NC}     http://localhost:8000/api/health"
echo ""
echo -e "  ${YELLOW}Press Ctrl+C to stop everything${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Keep running until Ctrl+C
wait
