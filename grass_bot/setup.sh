#!/bin/bash
set -e

echo "========================================"
echo "  Grass Multi-Account Bot - Setup"
echo "========================================"

# 1. System updates
sudo apt update && sudo apt upgrade -y

# 2. Install dependencies
sudo apt install -y python3 python3-pip python3-venv curl wget git

# 3. Install Docker
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
fi

# 4. Create Python virtual env
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install websocket-client requests

# 5. Verify IPv6 support
echo ""
echo "========================================"
echo "  Verificando IPv6..."
echo "========================================"
ip -6 addr show 2>/dev/null || echo "No se detecto IPv6"
echo ""
echo "Para asignar multiples IPv6 a una interfaz:"
echo "  sudo ip -6 addr add <tu_ipv6>/64 dev eth0"
echo ""
echo "========================================"
echo "  Setup completado!"
echo "========================================"
echo ""
echo "Pasos siguientes:"
echo "  1. Configura tus IPv6: sudo ip -6 addr add 2a01:.../64 dev eth0"
echo "  2. Edita config.json con tus user_ids y IPv6"
echo "  3. Ejecuta: source venv/bin/activate && python grass_manager.py"
echo "========================================"
