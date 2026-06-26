# Guía: Comprar Crypto en Mercado Spot (Binance)

El **Mercado Spot** es donde compras y vendes criptos contra USDT (u otras monedas). Es más barato que usar "Convertir" porque el spread es menor.

## Diferencia: Convertir vs Spot

| Operación | Comisión | Spread |
|-----------|----------|--------|
| **Convertir** | 0% visible | ~0.1-0.2% oculto en el precio |
| **Spot Límite (Maker)** | 0.1% | Tú pones el precio |
| **Spot Market (Taker)** | 0.1% | Precio del libro actual |

Convertir es más caro porque Binance te da un precio peor al que realmente hay en el mercado.

## Cómo comprar SOL en Spot (ejemplo)

### 1. Depositar USDT
- `Billetera → Fiat y Spot`
- Si compraste USDT por P2P, ya están ahí

### 2. Ir al par
- Busca `SOL` → entra a `SOL/USDT`
- Asegúrate pestaña **Spot** (no Margin/Futures)

### 3. Tipos de orden

**Market (instantáneo):**
- Pones monto en USDT (ej. $20)
- Presionas "Comprar SOL"
- Se ejecuta al mejor precio disponible

**Límite (más barato):**
- Ves el libro de órdenes (precios de otros vendedores)
- Pones un precio ligeramente arriba del mejor ask
- Esperas a que alguien te venda
- Pagas comisión Maker (0.1%) si tu orden no se ejecuta inmediatamente

### 4. Retirar a wallet externa (para DEX Multi-Red)
- `Billetera → Spot → Retirar`
- Red: **Solana** (SOL)
- Dirección: tu wallet **Phantom**
- Comisión de red: ~$0.03

## Comisiones Spot Binance

| Tipo | % |
|------|---|
| Maker (orden Límite no ejecutada al instante) | 0.1% |
| Taker (Market o Límite ejecutada al instante) | 0.1% |

## Lo que hace el bot

- **P2P**: Compra/Venta de USDT vs Bs. en anuncios Maker. Ganancia del spread entre compra y venta.
- **DEX Multi-Red**: Compra SOL (o POL/BNB) en Spot de Binance → retira a Phantom → vende en Jupiter/DexScreener por USDC. Ganancia del spread entre precio Binance vs precio DEX.

## Vocabulario

| Término | Significado |
|---------|-------------|
| **Maker** | Pones una orden que no se ejecuta al instante. Te pagan por dar liquidez. |
| **Taker** | Tomas una orden existente. Pagas por quitar liquidez. |
| **Spread** | Diferencia entre precio de compra y venta. |
| **Spot** | Compra inmediata de la cripto real (no derivados/futuros). |
| **P2P** | Persona a persona. Publicas anuncios, otros usuarios te compran/venden. |
| **Orden Límite** | Pones el precio exacto al que quieres comprar/vender. |
| **Orden Market** | Compras/vendes al mejor precio disponible ahora mismo. |
