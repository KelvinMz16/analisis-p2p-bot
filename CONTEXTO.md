# Contexto del Proyecto — Análisis P2P Bot

## Objetivo Original
Generar $1+/día desde un VPS Kamatera (crédito $100, expira ~24 Jul 2026) sin inversión de capital, usando bots automatizados.

## Constraints
- Venezuela, sin tarjeta internacional
- IP datacenter (Kamatera, Miami)
- Sin proxies pagados
- Sin capital inicial
- PC local no puede estar 24/7

## Stack
- VPS: 103.90.161.123 (root / Conejo86), 2GB RAM, 20GB SSD
- Python 3.10/3.11
- Kamatera crédito $100 expira ~24 Jul 2026

## Lo que se probó — Resultados

### ✅ Funciona desde datacenter
| Proyecto | Resultado | Ganancia |
|----------|-----------|----------|
| OKX Racer (Telegram) | ✅ Corre en VPS, balance 500 pts | Especulativo (airdrops) |
| Tomarket (Telegram) | ✅ API accesible (api-web.tomarket.ai), login falla por sesión Telegram | Especulativo |
| Bot P2P Binance | ✅ Corre pero mercado plano, sin spread | $0/mes |
| AIOZ DePIN v1.2.6 | ✅ Conectado, pero `ai_status: Offline`, no asigna storage | $0/mes |
| Bitget.com | ✅ API accesible (sin Cloudflare) | No implementado |
| Gate.io API | ✅ `api.gateio.ws` accesible | No implementado |

### ❌ Bloqueado (Cloudflare o IP datacenter)
| Proyecto | Motivo |
|----------|--------|
| Blum | Cloudflare |
| NotPixel | Cloudflare |
| Seed | Cloudflare |
| MemeFi | Cloudflare |
| Bybit SpaceS | API 000, repo falso |
| Bybit Coinsweeper | API 530 Cloudflare |
| Grass.io | No paga en datacenter (0% Network Quality) |
| Honeygain / EarnApp / TraffMonetizer | $0.01-0.03/día desde datacenter |
| Datagram | `nats: Authorization Violation` server-side |
| Mysterium | Mínimo retiro $2, inalcanzable desde 1 IP |

### 💡 Aprendizajes clave
1. **IP datacenter** es el principal limitante — Cloudflare bloquea, DePIN no paga, bandwidth sharing da $0.01/día
2. **Sin capital** no se puede hacer trading, staking, ni ningún yield real
3. **Exchanges grandes** (OKX, Bitget, Gate.io) NO usan Cloudflare — sus mini apps Telegram son accesibles
4. **Airdrops Telegram** son la única oportunidad real desde VPS: gratis, 24/7, especulativos
5. **Tunnelbroker IPv6** no ayuda — la reputación de subred es la misma (ASN Kamatera)
6. **PC residencial** multiplica opciones (Grass $0.20-0.50/día + airdrops bloqueados) pero requiere 24/7

## Estado actual de los bots en el VPS
- Screen `farmbot`: OKX Racer + Tomarket (SESIÓN TELEGRAM INVALIDA — requiere re-auth)
- Screen `p2p`: Bot P2P Binance (corriendo, mercado plano)
- Screen `datagram`: Datagram (conectado pero no funcional)
- Systemd `aioz-depin`: AIOZ (conectado, ocioso)
- Sesión Telegram bloqueada por FloodWait ~22h (demasiados intentos de código)

## Para reactivar sesión Telegram
1. Esperar que termine FloodWait (~22h desde último intento)
2. Usar script `sign_in_pipe.py` que envía código y espera input
3. Pedir al usuario el código que le llega a su Telegram
4. La sesión se guarda en `sessions/session_1.session`

## Pendiente para explorar
- [ ] Bitget Mini App (@BitgetOfficialBot) — daily check-in, puntos → USDT
- [ ] Gate.io Mini App (@gate_official_bot) — Rewards Center
- [ ] Escribir módulo Bitget para telegram-airdop framework

## Conclusión dura
Sin capital + IP datacenter + PC local apagado = no hay forma de generar $1/día estable.
Lo único realista son airdrops Telegram especulativos (OKX Racer, Tomarket, Bitget, Gate.io).
El VPS no cuesta nada (crédito $100) — dejarlo corriendo hasta julio no pierde nada.
