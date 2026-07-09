# ============================================================
# BOT EN LA NUBE - Se ejecuta a diario en GitHub Actions
# Actualiza data.json con TRES estrategias SIMULADAS:
#   1) Cruce Dorado (SMA 50/200) sobre QQQ
#   2) Reversion RSI-2 (con filtro SMA 200) sobre QQQ
#   3) CAZADOR DIARIO: RSI-2 escaneando 20 tickers, max 5 posiciones
#   + Referencia: comprar y mantener QQQ
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
TICKERS_CAZA = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
                "NFLX", "JPM", "XOM", "UNH", "V", "KO", "DIS",
                "SPY", "QQQ", "IWM", "XLK", "XLF"]

CAPITAL_INICIAL = 10000.0
COSTO_OPERACION = 0.0005      # 0.05% por lado (QQQ)
COSTO_CAZA = 0.001            # 0.1% por lado (acciones individuales)
RSI2_ENTRADA = 10
RSI2_SALIDA = 60
MAX_POSICIONES = 5
MAX_HISTORIAL = 1500
MAX_OPS = 100

ARCHIVO_DATA = Path(__file__).resolve().parent.parent / "data.json"


def descargar():
    """Descarga 2 años de cierres diarios de los 20 tickers (incluye QQQ)."""
    frame = yf.download(TICKERS_CAZA, period="2y", interval="1d",
                        auto_adjust=True, progress=False)
    if frame is None or frame.empty:
        raise RuntimeError("No se pudieron descargar datos.")
    cierres = frame["Close"] if isinstance(frame.columns, pd.MultiIndex) else frame
    return cierres.dropna(how="all")


def rsi(serie, periodo):
    delta = serie.diff()
    g = delta.clip(lower=0).ewm(alpha=1 / periodo, adjust=False).mean()
    p = (-delta.clip(upper=0)).ewm(alpha=1 / periodo, adjust=False).mean()
    return 100 - 100 / (1 + g / p)


def cazador_inicial():
    return {"efectivo": CAPITAL_INICIAL, "posiciones": {}, "operaciones": []}


def estado_inicial():
    return {
        "version": 2,
        "ticker": TICKER,
        "capital_inicial": CAPITAL_INICIAL,
        "actualizado": "",
        "ultima_vela": "",
        "precio": 0.0,
        "indicadores": {},
        "cruce": {"efectivo": CAPITAL_INICIAL, "unidades": 0.0, "operaciones": []},
        "rsi2": {"efectivo": CAPITAL_INICIAL, "unidades": 0.0, "operaciones": []},
        "cazador": cazador_inicial(),
        "bh": {"unidades": 0.0, "iniciado": False},
        "historial": [],
    }


def cargar():
    if ARCHIVO_DATA.exists():
        with open(ARCHIVO_DATA, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "cazador" not in data:      # migracion desde la version anterior
            data["cazador"] = cazador_inicial()
        return data
    return estado_inicial()


def guardar(data):
    with open(ARCHIVO_DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def registrar(cartera, op):
    cartera["operaciones"].insert(0, op)
    del cartera["operaciones"][MAX_OPS:]


def comprar_qqq(cartera, precio, fecha, motivo):
    invertible = cartera["efectivo"] * (1 - COSTO_OPERACION)
    unidades = invertible / precio
    cartera["unidades"] = unidades
    cartera["efectivo"] = 0.0
    registrar(cartera, {"fecha": fecha, "tipo": f"COMPRA ({motivo})",
                        "precio": round(precio, 2), "unidades": round(unidades, 4),
                        "valor": round(unidades * precio, 2)})


def vender_qqq(cartera, precio, fecha, motivo):
    unidades = cartera["unidades"]
    valor = unidades * precio * (1 - COSTO_OPERACION)
    cartera["efectivo"] = valor
    cartera["unidades"] = 0.0
    registrar(cartera, {"fecha": fecha, "tipo": f"VENTA ({motivo})",
                        "precio": round(precio, 2), "unidades": round(unidades, 4),
                        "valor": round(valor, 2)})


def velas_cerradas(cierres):
    ahora = datetime.now(timezone.utc)
    ultima = cierres.index[-1].date()
    if ultima >= ahora.date() and (ahora.hour, ahora.minute) < (21, 30):
        return cierres.iloc[:-1]
    return cierres


def valor_cazador(caz, precios):
    total = caz["efectivo"]
    for tk, pos in caz["posiciones"].items():
        p = precios.get(tk)
        if p is not None and not pd.isna(p):
            total += pos["unidades"] * float(p)
        else:
            total += pos["costo"]
    return total


def operar_cazador(caz, precios, rsi2_fila, sma200_fila, fecha):
    """Un dia del cazador: primero salidas, luego entradas (max 5 posiciones)."""
    # --- Salidas ---
    for tk in list(caz["posiciones"].keys()):
        p, r, s = precios.get(tk), rsi2_fila.get(tk), sma200_fila.get(tk)
        if p is None or pd.isna(p) or pd.isna(r) or pd.isna(s):
            continue
        if float(r) > RSI2_SALIDA or float(p) < float(s):
            pos = caz["posiciones"].pop(tk)
            valor = pos["unidades"] * float(p) * (1 - COSTO_CAZA)
            caz["efectivo"] += valor
            pnl = round(valor - pos["costo"], 2)
            motivo = "rebote completado" if float(r) > RSI2_SALIDA else "perdio la SMA200"
            registrar(caz, {"fecha": fecha, "tipo": f"VENTA ({motivo})", "ticker": tk,
                            "precio": round(float(p), 2),
                            "unidades": round(pos["unidades"], 4),
                            "valor": round(valor, 2), "pnl": pnl})

    # --- Entradas: caidas fuertes en tendencia alcista, la mas fuerte primero ---
    candidatos = []
    for tk in TICKERS_CAZA:
        if tk in caz["posiciones"]:
            continue
        p, r, s = precios.get(tk), rsi2_fila.get(tk), sma200_fila.get(tk)
        if p is None or pd.isna(p) or pd.isna(r) or pd.isna(s):
            continue
        if float(p) > float(s) and float(r) < RSI2_ENTRADA:
            candidatos.append((float(r), tk))
    candidatos.sort()

    for r_val, tk in candidatos:
        if len(caz["posiciones"]) >= MAX_POSICIONES:
            break
        total = valor_cazador(caz, precios)
        monto = min(total / MAX_POSICIONES, caz["efectivo"])
        if monto < 100:
            break
        p = float(precios[tk])
        unidades = monto * (1 - COSTO_CAZA) / p
        caz["efectivo"] -= monto
        caz["posiciones"][tk] = {"unidades": round(unidades, 6), "costo": round(monto, 2),
                                 "entrada": round(p, 2), "fecha": fecha,
                                 "precio_actual": round(p, 2)}
        registrar(caz, {"fecha": fecha, "tipo": f"COMPRA (RSI2 {r_val:.0f})", "ticker": tk,
                        "precio": round(p, 2), "unidades": round(unidades, 4),
                        "valor": round(monto, 2), "pnl": ""})


def main():
    data = cargar()
    cierres = velas_cerradas(descargar())

    # Indicadores por ticker (para el cazador)
    rsi2_todos = cierres.apply(lambda c: rsi(c, 2))
    sma200_todos = cierres.rolling(200).mean()

    # Serie de QQQ (para las estrategias principales)
    df = cierres[[TICKER]].rename(columns={TICKER: "Close"}).dropna()
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

    precios_hoy = cierres.iloc[-1].to_dict()

    vela_nueva = fecha_vela != data.get("ultima_vela", "")
    if vela_nueva:
        # ---- 1: Cruce Dorado ----
        c = data["cruce"]
        if senal_cruce and c["unidades"] == 0:
            comprar_qqq(c, precio, fecha_vela, "Cruce Dorado")
        elif not senal_cruce and c["unidades"] > 0:
            vender_qqq(c, precio, fecha_vela, "Cruce de la Muerte")

        # ---- 2: Reversion RSI-2 en QQQ ----
        r = data["rsi2"]
        if r["unidades"] == 0 and precio > sma200 and rsi2 < RSI2_ENTRADA:
            comprar_qqq(r, precio, fecha_vela, f"RSI2 {rsi2:.0f} en tendencia alcista")
        elif r["unidades"] > 0 and (rsi2 > RSI2_SALIDA or precio < sma200):
            motivo = "RSI2 recuperado" if rsi2 > RSI2_SALIDA else "Perdio la SMA200"
            vender_qqq(r, precio, fecha_vela, motivo)

        # ---- 3: Cazador diario ----
        operar_cazador(data["cazador"], precios_hoy,
                       rsi2_todos.iloc[-1].to_dict(),
                       sma200_todos.iloc[-1].to_dict(), fecha_vela)

        # ---- Referencia ----
        if not data["bh"]["iniciado"]:
            data["bh"]["unidades"] = CAPITAL_INICIAL * (1 - COSTO_OPERACION) / precio
            data["bh"]["iniciado"] = True

        data["historial"].append({
            "fecha": fecha_vela,
            "cruce": round(data["cruce"]["efectivo"] + data["cruce"]["unidades"] * precio, 2),
            "rsi2": round(data["rsi2"]["efectivo"] + data["rsi2"]["unidades"] * precio, 2),
            "cazador": round(valor_cazador(data["cazador"], precios_hoy), 2),
            "bh": round(data["bh"]["unidades"] * precio, 2),
            "roc10": round(roc10, 2),
        })
        del data["historial"][:-MAX_HISTORIAL]
        data["ultima_vela"] = fecha_vela

    # ---- Refrescar precio actual de las posiciones abiertas del cazador ----
    for tk, pos in data["cazador"]["posiciones"].items():
        p = precios_hoy.get(tk)
        if p is not None and not pd.isna(p):
            pos["precio_actual"] = round(float(p), 2)

    # ---- Estado e indicadores ----
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
        "valor_cazador": round(valor_cazador(data["cazador"], precios_hoy), 2),
        "valor_bh": round(data["bh"]["unidades"] * precio, 2) if data["bh"]["iniciado"] else 0.0,
    }

    # ---- Serie para la grafica de la estrategia (ultimos 250 dias) ----
    cola = df.tail(250)
    data["grafico"] = [
        {"f": str(ix.date()), "c": round(float(r["Close"]), 2),
         "s50": round(float(r["SMA50"]), 2), "s200": round(float(r["SMA200"]), 2)}
        for ix, r in cola.iterrows()
    ]

    guardar(data)
    caz = data["cazador"]
    print(f"OK | vela {fecha_vela} ({'nueva' if vela_nueva else 'ya procesada'}) | "
          f"{TICKER} ${precio:.2f} | margen {data['indicadores']['margen_pct']:+.2f}% | "
          f"RSI2 {rsi2:.1f} | cazador: {len(caz['posiciones'])}/{MAX_POSICIONES} posiciones, "
          f"${data['indicadores']['valor_cazador']:,.2f}")


if __name__ == "__main__":
    main()
