# ============================================================
# BOT EN LA NUBE v3 - CAZADOR SMC (Smart Money Concepts)
# Estrategia UNICA, validada en 3 universos (PF 2.01 / 1.36 / 1.28):
#   - Velas DIARIAS, solo largos, 20 tickers
#   - ENTRA: CHoCH alcista (cierre rompe el ultimo swing high
#     viniendo de estructura bajista) con precio sobre su SMA200
#   - SALE: CHoCH bajista o perdida de la SMA200
#   - Maximo 5 posiciones (20% del capital cada una)
#   - Si hay mas señales que huecos: la ruptura mas fuerte primero
#   + Referencia: comprar y mantener QQQ
# Corre a diario en GitHub Actions. TODO SIMULADO.
# A mano:  py bot/actualizar.py
# ============================================================

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
           "NFLX", "JPM", "XOM", "UNH", "V", "KO", "DIS",
           "SPY", "QQQ", "IWM", "XLK", "XLF"]

CAPITAL_INICIAL = 10000.0
COSTO = 0.001              # 0.1% por lado
MAX_POSICIONES = 5
FRACTAL = 2
MAX_HISTORIAL = 1500
MAX_OPS = 100

ARCHIVO_DATA = Path(__file__).resolve().parent.parent / "data.json"


def descargar():
    frame = yf.download(TICKERS, period="2y", interval="1d",
                        auto_adjust=True, progress=False)
    if frame is None or frame.empty:
        raise RuntimeError("No se pudieron descargar datos.")
    return frame


def velas_cerradas(frame):
    ahora = datetime.now(timezone.utc)
    ultima = frame.index[-1].date()
    if ultima >= ahora.date() and (ahora.hour, ahora.minute) < (21, 30):
        return frame.iloc[:-1]
    return frame


def señales_ticker(df):
    """(deseo, fuerza) para un ticker: la maquina de estructura SMC."""
    df = df.dropna()
    if len(df) < 220:
        return None, None
    H, L, C = df["High"].values, df["Low"].values, df["Close"].values
    sma200 = df["Close"].rolling(200).mean().values
    n = len(df)

    sh, sl = [], []
    for i in range(FRACTAL, n - FRACTAL):
        if all(H[i] > H[i - k] for k in range(1, FRACTAL + 1)) and \
           all(H[i] > H[i + k] for k in range(1, FRACTAL + 1)):
            sh.append((i, H[i]))
        if all(L[i] < L[i - k] for k in range(1, FRACTAL + 1)) and \
           all(L[i] < L[i + k] for k in range(1, FRACTAL + 1)):
            sl.append((i, L[i]))

    deseo = [0] * n
    fuerza = [0.0] * n
    dentro, direccion = 0, 0
    ish = isl = 0
    ult_sh = ult_sl = None
    for i in range(n):
        while ish < len(sh) and sh[ish][0] + FRACTAL <= i:
            ult_sh = sh[ish][1]; ish += 1
        while isl < len(sl) and sl[isl][0] + FRACTAL <= i:
            ult_sl = sl[isl][1]; isl += 1

        choch_alcista = ult_sh is not None and direccion <= 0 and C[i] > ult_sh
        choch_bajista = ult_sl is not None and direccion >= 0 and C[i] < ult_sl
        if choch_alcista:
            direccion = 1
        elif choch_bajista:
            direccion = -1
        bias_ok = not pd.isna(sma200[i]) and C[i] > sma200[i]

        if dentro == 0 and choch_alcista and bias_ok:
            dentro = 1
            fuerza[i] = (C[i] / ult_sh - 1) * 100
        elif dentro == 1 and (choch_bajista or
                              (not pd.isna(sma200[i]) and C[i] < sma200[i])):
            dentro = 0
        deseo[i] = dentro

    return (pd.Series(deseo, index=df.index),
            pd.Series(fuerza, index=df.index))


def estado_inicial():
    return {
        "version": 3,
        "capital_inicial": CAPITAL_INICIAL,
        "actualizado": "",
        "ultima_vela": "",
        "precio_qqq": 0.0,
        "indicadores": {},
        "smc": {"efectivo": CAPITAL_INICIAL, "posiciones": {}, "operaciones": []},
        "bh": {"unidades": 0.0, "iniciado": False},
        "historial": [],
    }


def cargar():
    if ARCHIVO_DATA.exists():
        with open(ARCHIVO_DATA, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version", 0) >= 3:
            return data
    return estado_inicial()   # borron y cuenta nueva para la v3


def guardar(data):
    with open(ARCHIVO_DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def registrar(cartera, op):
    cartera["operaciones"].insert(0, op)
    del cartera["operaciones"][MAX_OPS:]


def valor_smc(smc, precios):
    total = smc["efectivo"]
    for tk, pos in smc["posiciones"].items():
        p = precios.get(tk)
        total += pos["unidades"] * float(p) if (p is not None and not pd.isna(p)) else pos["costo"]
    return total


def main():
    data = cargar()
    frame = velas_cerradas(descargar())
    cierres = frame["Close"]

    # Señales SMC por ticker
    deseos, fuerzas = {}, {}
    for tk in TICKERS:
        try:
            df_tk = pd.DataFrame({c: frame[c][tk] for c in ("Open", "High", "Low", "Close")})
        except KeyError:
            continue
        d, f = señales_ticker(df_tk)
        if d is not None:
            deseos[tk] = d
            fuerzas[tk] = f

    fecha_vela = str(cierres.index[-1].date())
    precios_hoy = cierres.iloc[-1].to_dict()
    qqq = cierres["QQQ"].dropna()
    precio_qqq = float(qqq.iloc[-1])
    roc10 = float((qqq.iloc[-1] / qqq.iloc[-11] - 1) * 100) if len(qqq) > 11 else 0.0

    vela_nueva = fecha_vela != data.get("ultima_vela", "")
    if vela_nueva:
        smc = data["smc"]

        # ---- VENTAS: la estructura se rompio o se perdio el bias ----
        for tk in list(smc["posiciones"].keys()):
            d = deseos.get(tk)
            p = precios_hoy.get(tk)
            if d is None or p is None or pd.isna(p):
                continue
            if int(d.iloc[-1]) == 0:
                pos = smc["posiciones"].pop(tk)
                valor = pos["unidades"] * float(p) * (1 - COSTO)
                smc["efectivo"] += valor
                registrar(smc, {"fecha": fecha_vela, "tipo": "VENTA (estructura rota)",
                                "ticker": tk, "precio": round(float(p), 2),
                                "unidades": round(pos["unidades"], 4),
                                "valor": round(valor, 2),
                                "pnl": round(valor - pos["costo"], 2)})

        # ---- COMPRAS: CHoCH alcista nuevo, la ruptura mas fuerte primero ----
        candidatos = []
        for tk, d in deseos.items():
            if tk in smc["posiciones"] or len(d) < 2:
                continue
            p = precios_hoy.get(tk)
            if p is None or pd.isna(p):
                continue
            if int(d.iloc[-1]) == 1 and int(d.iloc[-2]) == 0:
                candidatos.append((-float(fuerzas[tk].iloc[-1]), tk))
        candidatos.sort()
        for neg_f, tk in candidatos:
            if len(smc["posiciones"]) >= MAX_POSICIONES:
                break
            total = valor_smc(smc, precios_hoy)
            monto = min(total / MAX_POSICIONES, smc["efectivo"])
            if monto < 100:
                break
            p = float(precios_hoy[tk])
            unidades = monto * (1 - COSTO) / p
            smc["efectivo"] -= monto
            smc["posiciones"][tk] = {"unidades": round(unidades, 6),
                                     "costo": round(monto, 2),
                                     "entrada": round(p, 2), "fecha": fecha_vela,
                                     "precio_actual": round(p, 2)}
            registrar(smc, {"fecha": fecha_vela,
                            "tipo": f"COMPRA (CHoCH +{-neg_f:.1f}%)", "ticker": tk,
                            "precio": round(p, 2), "unidades": round(unidades, 4),
                            "valor": round(monto, 2), "pnl": ""})

        # ---- Referencia: comprar y mantener QQQ ----
        if not data["bh"]["iniciado"]:
            data["bh"]["unidades"] = CAPITAL_INICIAL * (1 - COSTO) / precio_qqq
            data["bh"]["iniciado"] = True

        data["historial"].append({
            "fecha": fecha_vela,
            "smc": round(valor_smc(data["smc"], precios_hoy), 2),
            "bh": round(data["bh"]["unidades"] * precio_qqq, 2),
            "roc10": round(roc10, 2),
        })
        del data["historial"][:-MAX_HISTORIAL]
        data["ultima_vela"] = fecha_vela

    # ---- refrescar precios de posiciones abiertas ----
    for tk, pos in data["smc"]["posiciones"].items():
        p = precios_hoy.get(tk)
        if p is not None and not pd.isna(p):
            pos["precio_actual"] = round(float(p), 2)

    # ---- cuantos tickers estan hoy en estructura alcista (contexto) ----
    alcistas = sum(1 for d in deseos.values() if int(d.iloc[-1]) == 1)

    data["precio_qqq"] = round(precio_qqq, 2)
    data["actualizado"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data["indicadores"] = {
        "roc10": round(roc10, 2),
        "valor_smc": round(valor_smc(data["smc"], precios_hoy), 2),
        "valor_bh": round(data["bh"]["unidades"] * precio_qqq, 2) if data["bh"]["iniciado"] else 0.0,
        "tickers_alcistas": alcistas,
        "tickers_total": len(deseos),
    }

    guardar(data)
    smc = data["smc"]
    print(f"OK | vela {fecha_vela} ({'nueva' if vela_nueva else 'ya procesada'}) | "
          f"QQQ ${precio_qqq:.2f} | SMC: {len(smc['posiciones'])}/{MAX_POSICIONES} posiciones, "
          f"${data['indicadores']['valor_smc']:,.2f} | "
          f"{alcistas}/{len(deseos)} tickers en estructura alcista")


if __name__ == "__main__":
    main()
