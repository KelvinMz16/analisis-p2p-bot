#!/usr/bin/env python3
"""
IPv6 Manager - Asigna automaticamente multiples IPv6 a una interfaz
para usar con el Grass multi-account bot.

Uso:
  python ipv6_manager.py --iface eth0 --subnet 2a01:4f8:aaaa:bbbb::/64 --count 5
  python ipv6_manager.py --list
  python ipv6_manager.py --cleanup
"""
import argparse
import subprocess
import sys
import re
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_default_iface():
    code, out, _ = run("ip -4 route show default | awk '{print $5}' | head -1")
    return out or "eth0"


def list_ipv6():
    code, out, _ = run("ip -6 addr show | grep 'inet6' | grep -v '::1' | grep -v 'fe80'")
    if not out:
        print("No se encontraron IPv6 globales")
        return []
    ips = []
    for line in out.split("\n"):
        match = re.search(r'inet6\s+([0-9a-f:]+)/\d+', line)
        if match:
            ips.append(match.group(1))
    return ips


def add_ipv6(iface, subnet, count):
    # Extraer prefijo base (sin el /64)
    base = subnet.split("/")[0]
    prefix_len = subnet.split("/")[1] if "/" in subnet else "64"

    # Si base termina con ::, remover
    base = base.rstrip(":")

    print(f"Asignando {count} IPv6 a {iface} desde {subnet}...")
    for i in range(1, count + 1):
        ip = f"{base}:{i}/{prefix_len}"
        code, _, err = run(f"sudo ip -6 addr add {ip} dev {iface}")
        if code == 0:
            print(f"  [+] {ip}")
        else:
            if "already" in err:
                print(f"  [-] {ip} (ya existe)")
            else:
                print(f"  [X] {ip}: {err.strip()}")


def update_config_with_ips(iface, count, subnet):
    """Actualiza config.json con las nuevas IPv6"""
    if not os.path.exists(CONFIG_PATH):
        print(f"[ERROR] No existe {CONFIG_PATH}")
        return

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    base = subnet.split("/")[0].rstrip(":")
    accounts = config.get("accounts", [])

    for i in range(count):
        ip = f"{base}:{i + 1}"
        if i < len(accounts):
            accounts[i]["ipv6"] = ip
        else:
            accounts.append({
                "label": f"cuenta_{i + 1}",
                "user_id": "TU_USER_ID",
                "ipv6": ip,
            })

    config["accounts"] = accounts
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nConfig.json actualizado con {count} IPv6")
    print("No olvides editar config.json y poner los user_id correctos!")


def cleanup_ipv6(iface, subnet):
    base = subnet.split("/")[0].rstrip(":")
    code, out, _ = run(f"ip -6 addr show dev {iface} | grep '{base}'")
    if not out:
        print(f"No hay IPv6 de {subnet} en {iface}")
        return
    for line in out.split("\n"):
        match = re.search(r'inet6\s+(\S+)/(\d+)', line)
        if match:
            ip = match.group(1)
            prefix = match.group(2)
            code, _, _ = run(f"sudo ip -6 addr del {ip}/{prefix} dev {iface}")
            if code == 0:
                print(f"  [-] Eliminada {ip}/{prefix}")


def main():
    parser = argparse.ArgumentParser(description="IPv6 Manager para Grass Bot")
    parser.add_argument("--iface", help="Interfaz de red (ej: eth0)")
    parser.add_argument("--subnet", help="Subred IPv6 (ej: 2a01:4f8:aaaa:bbbb::/64)")
    parser.add_argument("--count", type=int, default=1, help="Numero de IPv6 a asignar")
    parser.add_argument("--list", action="store_true", help="Listar IPv6 actuales")
    parser.add_argument("--cleanup", action="store_true", help="Limpiar IPv6 de una subred")
    parser.add_argument("--update-config", action="store_true", help="Actualizar config.json con las IPv6")

    args = parser.parse_args()

    iface = args.iface or get_default_iface()

    if args.list:
        ips = list_ipv6()
        print(f"IPv6 globales en {iface}:")
        for ip in ips:
            print(f"  {ip}")
        return

    if args.cleanup:
        if not args.subnet:
            print("Usa --subnet para especificar la subred a limpiar")
            sys.exit(1)
        cleanup_ipv6(iface, args.subnet)
        return

    if not args.subnet:
        print("Usa --subnet para especificar la subred (ej: 2a01:4f8:aaaa:bbbb::/64)")
        sys.exit(1)

    add_ipv6(iface, args.subnet, args.count)

    if args.update_config:
        update_config_with_ips(iface, args.count, args.subnet)

    print("\nHecho!")


if __name__ == "__main__":
    main()
