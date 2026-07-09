# ============================================================
# BOT EN LA NUBE - Se ejecuta a diario en GitHub Actions
# Actualiza data.json con las dos estrategias SIMULADAS:
#   1) Cruce Dorado (SMA 50/200) sobre QQQ
#   2) Reversion RSI-2 (con filtro SMA 200) sobre QQQ
#   + Referencia: comprar y mantener
#
# Tambien puede ejecutarse a mano en la PC:  py bot/actualizar.py
# TODO SIMULADO: no toca dinero real.
# ============================================================

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKER = "QQQ"
CAPITAL_INICIAL = 10000.0
COSTO_OPERACION = 0.0005      # 0.05% por lado
RSI2_ENTRADA = 10
RSI2_SALIDA = 60
MAX_HISTORIAL = 1500          # ~6 años de puntos diarios
MAX_OPS = 100

ARCHIVO_DATA = Path(__file__).resolve().parent.parent / "data.json"


def descargar():
    df = yf.download(TICKER, period="2y", interval="1d",
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError("No se pudieron descargar datos.")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Close"]].dropna()


def rsi(serie, periodo):
    delta = serie.diff()
    g = delta.clip(lower=0).ewm(alpha=1 / periodo, adjust=False).mean()
    p = (-delta.clip(upper=0)).ewm(alpha=1 / periodo, adjust=False).mean()
    return 100 - 100 / (1 + g / p)


def estado_inicial():
    return {
        "version": 1,
        "ticker": TICKER,
        "capital_inicial": CAPITAL_INICIAL,
        "actualizado": "",
        "ultima_vela": "",
        "precio": 0.0,
        "indicadores": {},
        "cruce": {"efectivo": CAPITAL_INICIAL, "unidades": 0.0, "operaciones": []},
        "rsi2": {"efectivo": CAPITAL_INICIAL, "unidades": 0.0, "operaciones": []},
        "bh": {"unidades": 0.0, "iniciado": False},
        "historial": [],
    }


def cargar():
    if ARCHIVO_DATA.exists():
        with open(ARCHIVO_DATA, "r", encoding="utf-8") as f:
            return json.load(f)
    return estado_inicial()


def guardar(data):
    with open(ARCHIVO_DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def registrar(cartera, tipo, precio, unidades, valor, fecha):
    cartera["operaciones"].insert(0, {
        "fecha": fecha, "tipo": tipo,
        "precio": round(precio, 2),
        "unidades": round(unidades, 4),
        "valor": round(valor, 2),
    })
    del cartera["operaciones"][MAX_OPS:]


def comprar(cartera, precio, fecha, motivo):
    invertible = cartera["efectivo"] * (1 - COSTO_OPERACION)
    unidades = invertible / precio
    cartera["unidades"] = unidades
    cartera["efectivo"] = 0.0
    registrar(cartera, f"COMPRA ({motivo})", precio, unidades,
              unidades * precio, fecha)


def vender(cartera, precio, fecha, motivo):
    unidades = cartera["unidades"]
    valor = unidades * precio * (1 - COSTO_OPERACION)
    cartera["efectivo"] = valor
    cartera["unidades"] = 0.0
    registrar(cartera, f"VENTA ({motivo})", precio, unidades, valor, fecha)


def velas_cerradas(df):
    """Descarta la vela de hoy si el mercado de EE.UU. aun no cierra
    (cierre 4pm ET ~ 21:00 UTC; usamos 21:30 UTC como margen)."""
    ahora = datetime.now(timezone.utc)
    ultima = df.index[-1].date()
    if ultima >= ahora.date() and (ahora.hour, ahora.minute) < (21, 30):
        return df.iloc[:-1]
    return df


def main():
    data = cargar()
    df = velas_cerradas(descargar())

    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["RSI2"] = rsi(df["Close"], 2)
    df["ROC10"] = (df["Close"] / df["Close"].shift(10) - 1) * 100
    df = df.dropna()

    fila = df.iloc[-1]
    precio = float(fila["Close"])
    sma50, sma200, rsi2 = float(fila["SMA50"]), float(fila["SMA200"]), float(fila["RSI2"])
    roc10 = float(fila["ROC10"])
    fecha_vela = str(df.index[-1].date())
    senal_cruce = sma50 > sma200

    vela_nueva = fecha_vela != data.get("ultima_vela", "")
    if vela_nueva:
        # ---- Estrategia 1: Cruce Dorado ----
        c = data["cruce"]
        if senal_cruce and c["unidades"] == 0:
            comprar(c, precio, fecha_vela, "Cruce Dorado")
        elif not senal_cruce and c["unidades"] > 0:
            vender(c, precio, fecha_vela, "Cruce de la Muerte")

        # ---- Estrategia 2: Reversion RSI-2 ----
        r = data["rsi2"]
        if r["unidades"] == 0 and precio > sma200 and rsi2 < RSI2_ENTRADA:
            comprar(r, precio, fecha_vela, f"RSI2 {rsi2:.0f} en tendencia alcista")
        elif r["unidades"] > 0 and (rsi2 > RSI2_SALIDA or precio < sma200):
            motivo = "RSI2 recuperado" if rsi2 > RSI2_SALIDA else "Perdio la SMA200"
            vender(r, precio, fecha_vela, motivo)

        # ---- Referencia: comprar y mantener ----
        if not data["bh"]["iniciado"]:
            data["bh"]["unidades"] = CAPITAL_INICIAL * (1 - COSTO_OPERACION) / precio
            data["bh"]["iniciado"] = True

        # ---- Historial para el grafico ----
        data["historial"].append({
            "fecha": fecha_vela,
            "cruce": round(data["cruce"]["efectivo"] + data["cruce"]["unidades"] * precio, 2),
            "rsi2": round(data["rsi2"]["efectivo"] + data["rsi2"]["unidades"] * precio, 2),
            "bh": round(data["bh"]["unidades"] * precio, 2),
            "roc10": round(roc10, 2),
        })
        del data["historial"][:-MAX_HISTORIAL]
        data["ultima_vela"] = fecha_vela

    # ---- Estado e indicadores (siempre se refrescan) ----
    data["precio"] = round(precio, 2)
    data["actualizado"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data["indicadores"] = {
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "margen_pct": round((sma50 / sma200 - 1) * 100, 2),
        "rsi2": round(rsi2, 1),
        "roc10": round(roc10, 2),
        "tendencia": "alcista" if senal_cruce else "bajista",
        "cruce_posicion": "COMPRADO" if data["cruce"]["unidades"] > 0 else "EN EFECTIVO",
        "rsi2_posicion": "COMPRADO" if data["rsi2"]["unidades"] > 0 else "EN EFECTIVO",
        "valor_cruce": round(data["cruce"]["efectivo"] + data["cruce"]["unidades"] * precio, 2),
        "valor_rsi2": round(data["rsi2"]["efectivo"] + data["rsi2"]["unidades"] * precio, 2),
        "valor_bh": round(data["bh"]["unidades"] * precio, 2) if data["bh"]["iniciado"] else 0.0,
    }

    guardar(data)
    print(f"OK | vela {fecha_vela} ({'nueva' if vela_nueva else 'ya procesada'}) | "
          f"{TICKER} ${precio:.2f} | margen {data['indicadores']['margen_pct']:+.2f}% | "
          f"RSI2 {rsi2:.1f}")


if __name__ == "__main__":
    main()
