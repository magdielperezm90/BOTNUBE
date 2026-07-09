# Panel Bot QQQ (simulado)

Bot de trading SIMULADO con dos estrategias sobre QQQ:
Cruce Dorado (SMA 50/200) y Reversion RSI-2. No usa dinero real.

- `bot/actualizar.py` corre a diario en GitHub Actions y actualiza `data.json`
- `index.html` es la PWA (desplegada en Vercel) que muestra el panel

Para actualizar a mano: `py bot/actualizar.py`
