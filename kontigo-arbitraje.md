# Análisis Arbitraje Kontigo → Binance P2P

## Fecha
24 Jun 2026

## Objetivo
Comprar USDT baratos en Kontigo (vía Pago Móvil en Bs), transferirlos a Binance y venderlos en P2P con margen.

## Comisiones Reales de Kontigo
| Método | Comisión |
|--------|----------|
| Débito automático | 0.5% |
| Pago Móvil manual | 1.5% |
| Crypto | 0% |
| Efectivo (taquilla) | 1.25% |
| Tarjeta | 5.3% + $0.50 |

## Comisiones de Retiro (Kontigo → Binance)
- Red más barata: Polygon / Arbitrum (~$0.30)
- TRC-20: ~$1
- Ethereum: más cara

## Binance P2P (Venta)
- Comisión Maker: 0%
- Comisión por operación: ~0.2%

## ⚠️ Restricción Importante
Binance **prohibió** (Ene 2026) recibir pagos P2P en cuentas bancarias asociadas a Kontigo ("Oha Technology").
- Penalizaciones: 24h → 1 semana → pérdida de insignia
- Solución: recibir los Bs de la venta en cuenta personal (BDV, Banesco, Mercantil), no en la cuenta asociada a Kontigo

## Simulación $94 con Pago Móvil
| Concepto | Bs |
|----------|----|
| Kontigo debita (tasa aparente 783.25) | 73,625.96 |
| + Pago Móvil del banco (0.3%) | +220.88 |
| Costo real | 73,846.84 |
| Tasa efectiva | 785.60/USDT |
| Comisión Kontigo | ~1.5% adicional |

**Resultado:** A 801 de venta P2P, la operación da pérdida (~222 Bs). El margen es demasiado ajustado para la cantidad de comisiones intermedias.

## Conclusión
No es rentable con capital pequeño ($90) y spreads normales. Kontigo cobra ~1.5% por recargar y el spread en P2P ronda 1-2%. Las comisiones se comen todo el margen.

La única oportunidad real es esperar picos anómalos de spread en el P2P directo (>3-4%), que es justo lo que monitorea el bot.

## Alternativas No Exploradas
- Comprar directo en Binance P2P en vez de Kontigo
- Contactar comerciantes mayoristas directamente
