#!/usr/bin/env bash
# ===================================================
#  🔀 RouterAI Development Script
#  Usage: ./dev.sh [command]
# ===================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}ℹ️  $*${NC}"; }
ok()    { echo -e "${GREEN}✅ $*${NC}"; }
err()   { echo -e "${RED}❌ $*${NC}"; exit 1; }

ensure_venv() {
    if [[ ! -d "$VENV_DIR" ]]; then
        info "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi
    "$PIP" install -q -r requirements.txt
}

cmd_install() {
    ensure_venv
    "$PIP" install -q pytest pytest-cov ruff httpx[http2]
    ok "Dependencies installed"
}

cmd_run() {
    ensure_venv
    info "Starting RouterAI (FastAPI on port 8900)..."
    info "Dashboard: http://127.0.0.1:8900"
    info "API Docs:  http://127.0.0.1:8900/docs"
    info "Proxy:     http://127.0.0.1:8900/v1"
    "$PYTHON" src/server.py
}

cmd_test() {
    ensure_venv
    "$PIP" install -q pytest pytest-cov httpx[http2] 2>/dev/null
    info "Running tests..."
    "$VENV_DIR/bin/pytest" tests/ -v --tb=short
}

cmd_lint() {
    ensure_venv
    "$PIP" install -q ruff 2>/dev/null
    info "Linting..."
    "$VENV_DIR/bin/ruff" check src/ tests/
    ok "Lint passed"
}

cmd_format() {
    ensure_venv
    "$PIP" install -q ruff 2>/dev/null
    info "Formatting..."
    "$VENV_DIR/bin/ruff" format src/ tests/
    ok "Formatted"
}

cmd_docker_build() {
    info "Building Docker image..."
    docker build -t routerai:dev .
    ok "Docker image built"
}

cmd_docker_run() {
    info "Starting with Docker Compose..."
    docker compose up -d
    ok "Running at http://127.0.0.1:8900"
}

cmd_docker_stop() {
    docker compose down
    ok "Stopped"
}

cmd_clean() {
    rm -rf "$VENV_DIR" .pytest_cache .mypy_cache .ruff_cache htmlcov
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    ok "Cleaned"
}

case "${1:-help}" in
    install)    cmd_install ;;
    run)        cmd_run ;;
    test)       cmd_test ;;
    lint)       cmd_lint ;;
    format)     cmd_format ;;
    docker-build)  cmd_docker_build ;;
    docker-run)    cmd_docker_run ;;
    docker-stop)   cmd_docker_stop ;;
    clean)      cmd_clean ;;
    help|*)
        echo ""
        echo "🔀 RouterAI Dev Script"
        echo "━━━━━━━━━━━━━━━━━━━━"
        echo "  ./dev.sh install      — Install deps + dev tools"
        echo "  ./dev.sh run          — Run FastAPI server (port 8900)"
        echo "  ./dev.sh test         — Run tests"
        echo "  ./dev.sh lint         — Lint code"
        echo "  ./dev.sh format      — Auto-format code"
        echo "  ./dev.sh docker-build — Build Docker image"
        echo "  ./dev.sh docker-run   — Start with Docker Compose"
        echo "  ./dev.sh docker-stop  — Stop Docker"
        echo "  ./dev.sh clean        — Remove venv + caches"
        echo ""
        ;;
esac
