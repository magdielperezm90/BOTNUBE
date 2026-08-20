// =====================================================================
//  MAGMAX v1.1 - Narrador de estructura de mercado
//
//  v1.1: panel movible (PosicionPanel) + alertas de sonido opcionales
//        (solo en tiempo real; la carga del historico no suena).
//  v1.3: ARREGLO DE LA ESTRUCTURA. Antes, al romperse un swing se sacaba
//        de la pila que decide la tendencia -> la pila casi nunca juntaba
//        dos validos y el panel decia RANGO el 95% del tiempo (medido).
//        Ahora la pila de tendencia NO se toca al romper; solo se anula la
//        REFERENCIA de ruptura. Y si los swings no forman patron limpio
//        (HH+HL o LH+LL) el estado es TRANSICION en vez de heredar el
//        anterior. Reparto medido: 31% alcista / 28% bajista / 41% rango.
//  v1.2: PARPADEO DE ACCION. Cuando hay algo accionable (BOS/CHoCH nuevo
//        o retest dado), un aviso grande parpadea y la zona de retest
//        pulsa. Corre con un reloj propio (DispatcherTimer), porque el
//        indicador calcula al cierre de vela y ahi no se puede parpadear.
//
//  Contesta dos preguntas en un panel, con numeros medidos:
//    QUE ESTA PASANDO   -> estado de la estructura (swings 15m confirmados)
//    QUE PUEDE PASAR    -> los dos escenarios con su frecuencia HISTORICA
//
//  NO da señales de entrada. Para eso esta MomentumVolumen.
//  Conviven en el mismo grafico.
//
//  CONCEPTOS (paquete de 30 laminas de estructura, 18-ago-2026):
//    - HH/HL = alcista, LH/LL = bajista (cadena de swings)
//    - BOS   = ruptura a favor de la tendencia (continuacion)
//    - CHoCH = primera ruptura en contra (posible reversion)
//    - RETEST = el regreso al nivel roto (la entrada segun 12 de 30 laminas)
//    - SWEEP = mecha que barre un swing y cierra de regreso (trampa)
//
//  BASES MEDIDAS (motor del lab, MNQ 1m, jun-2025 -> ago-2026, 1,128 eventos):
//    retest del nivel roto en <=60 velas ......... 84% (contando TODAS las rupturas)
//    BOS arriba -> siguiente evento BOS arriba ... 62%
//    BOS abajo  -> siguiente evento BOS abajo .... 59%
//    CHoCH arriba -> confirma con BOS arriba ..... 89% (n=19, muestra chica)
//    CHoCH abajo  -> confirma con BOS abajo ...... 67% (n=15, muestra chica)
//    sweep -> reversion >=1 ATR en <=30 velas .... 69%
//  El panel tambien mide EN VIVO estas tasas sobre el grafico cargado,
//  para que compares la base historica contra lo que tienes enfrente.
// =====================================================================
#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Windows.Media;
using System.Xml.Serialization;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.Tools;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.DrawingTools;
#endregion

namespace NinjaTrader.NinjaScript.Indicators
{
	public class MAGMAX : Indicator
	{
		private const string VERSION = "v1.3";

		// ---- bases medidas (ver cabecera). Se muestran, no se inventan. ----
		private const int BASE_RETEST     = 84;
		private const int BASE_CONT_UP    = 62;
		private const int BASE_CONT_DOWN  = 59;
		private const int BASE_CHOCH_UP   = 89;
		private const int BASE_CHOCH_DOWN = 67;
		private const int BASE_SWEEP      = 69;

		// ---- pilas de swings confirmados (los dos ultimos por lado) ----
		private List<double> pilaSH = new List<double>();   // solo para leer la tendencia
		private List<double> pilaSL = new List<double>();
		private double refSH = double.NaN;                  // nivel vivo para detectar ruptura
		private double refSL = double.NaN;

		// ---- estado narrado ----
		private int    tendencia = 0;          // 1 alcista | -1 bajista | 0 rango
		private string ultimoEvento = "";      // "BOS↑" "BOS↓" "CHoCH↑" "CHoCH↓"
		private int    barraEvento = -1;
		private double nivelEvento = 0;
		private bool   reversionPendiente = false;
		private int    dirPendiente = 0;

		// ---- retest pendiente ----
		private double retestNivel = 0;
		private int    retestBarra = -1;
		private int    retestDir = 0;          // 1 = roto hacia arriba (retest por abajo)
		private bool   retestTocado = false;
		private int    idZona = 0;

		// ---- sweeps pendientes de resolver ----
		private class Sweep { public int Barra; public int Dir; public double Ref; }
		private List<Sweep> sweeps = new List<Sweep>();
		private int barraUltimoSweep = -1;
		private int dirUltimoSweep = 0;

		// ---- parpadeo de accion ----
		private System.Windows.Threading.DispatcherTimer timerParpadeo;
		private bool faseParpadeo = false;
		private bool accionActiva = false;
		private bool bannerPuesto = false;
		private int barraAccion = -1;
		private string textoAccion = "";
		private DateTime zonaT1, zonaT2;
		private double zonaY1, zonaY2;
		private Brush zonaBorde;
		private bool zonaViva = false;

		// ---- contadores en vivo (se miden sobre el grafico cargado) ----
		private int nEventos = 0;
		private int nRetestResueltos = 0, nRetestTocados = 0;
		private int nBOSup = 0, nBOSupSigueUp = 0;
		private int nBOSdn = 0, nBOSdnSigueDn = 0;
		private int nSweeps = 0, nSweepsReversion = 0;
		private string eventoPrevio = "";

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description					= "Narrador de estructura: que esta pasando y que puede pasar, con frecuencias medidas. " + VERSION;
				Name						= "MAGMAX";
				Calculate					= Calculate.OnBarClose;
				IsOverlay					= true;
				DisplayInDataBox			= false;
				DrawOnPricePanel			= true;
				PaintPriceMarkers			= false;
				IsSuspendedWhileInactive	= true;

				// --- estructura ---
				MinutosEstructura			= 15;
				FuerzaSwing					= 5;
				ToleranciaTicks				= 2;

				// --- retest y sweep ---
				VentanaRetest				= 60;
				VentanaSweep				= 30;
				UmbralReversionATR			= 1.0;
				PeriodoATR					= 14;

				// --- visual ---
				MostrarPanel				= true;
				PosicionPanel				= 2;      // 0 arr-izq | 1 arr-der | 2 abj-izq | 3 abj-der
				AlertaEventos				= true;
				AlertaRetest				= true;
				AlertaSweep					= false;  // ~13 sweeps al dia: ruidoso, apagado
				UsarParpadeo				= true;
				VelasAccion					= 10;
				VelocidadParpadeoMs			= 400;
				PosicionBanner				= 0;      // arriba-izquierda (libre tras quitar los Labels)
				ColorBanner					= Brushes.Gold;
				MostrarZonasRetest			= true;
				MostrarSweeps				= true;
				MostrarEtiquetasEvento		= true;
				MostrarBasesHistoricas		= true;
				ColorAlcista				= Brushes.MediumSeaGreen;
				ColorBajista				= Brushes.IndianRed;
				ColorZonaRetest				= Brushes.Goldenrod;
				ColorSweep					= Brushes.MediumPurple;
			}
			else if (State == State.Configure)
			{
				AddDataSeries(BarsPeriodType.Minute, MinutosEstructura);
			}
			else if (State == State.Realtime)
			{
				if (UsarParpadeo && ChartControl != null)
					ChartControl.Dispatcher.InvokeAsync(() =>
					{
						timerParpadeo = new System.Windows.Threading.DispatcherTimer();
						timerParpadeo.Interval = TimeSpan.FromMilliseconds(Math.Max(150, VelocidadParpadeoMs));
						timerParpadeo.Tick += AlTickParpadeo;
						timerParpadeo.Start();
					});
			}
			else if (State == State.Terminated)
			{
				if (timerParpadeo != null && ChartControl != null)
					ChartControl.Dispatcher.InvokeAsync(() =>
					{
						if (timerParpadeo != null)
						{
							timerParpadeo.Stop();
							timerParpadeo.Tick -= AlTickParpadeo;
							timerParpadeo = null;
						}
					});
			}
		}

		private void AlTickParpadeo(object o, EventArgs e)
		{
			try
			{
				if (!accionActiva)
				{
					if (bannerPuesto)
						TriggerCustomEvent(x =>
						{
							RemoveDrawObject("bannerAccion");
							RestaurarZona();
							bannerPuesto = false;
						}, null);
					return;
				}
				faseParpadeo = !faseParpadeo;
				TriggerCustomEvent(x => PintarAccion(), null);
			}
			catch { }
		}

		private TextPosition PosBanner()
		{
			return PosicionBanner == 0 ? TextPosition.TopLeft
				 : PosicionBanner == 1 ? TextPosition.TopRight
				 : PosicionBanner == 2 ? TextPosition.BottomLeft
				 : TextPosition.BottomRight;
		}

		private void PintarAccion()
		{
			Draw.TextFixed(this, "bannerAccion", textoAccion, PosBanner(),
				faseParpadeo ? ColorBanner : Brushes.Transparent,
				new SimpleFont("Consolas", 16) { Bold = true },
				Brushes.Transparent, Brushes.Black, 70);
			bannerPuesto = true;
			if (zonaViva)
				Draw.Rectangle(this, "zn" + idZona, false, zonaT1, zonaY1, zonaT2, zonaY2,
					zonaBorde, ColorZonaRetest, faseParpadeo ? 55 : 12);
		}

		private void RestaurarZona()
		{
			if (zonaViva)
				Draw.Rectangle(this, "zn" + idZona, false, zonaT1, zonaY1, zonaT2, zonaY2,
					zonaBorde, ColorZonaRetest, 12);
		}

		protected override void OnBarUpdate()
		{
			// ================= serie de estructura (15m): confirmar swings =================
			if (BarsInProgress == 1)
			{
				int F = FuerzaSwing;
				if (CurrentBars[1] < 2 * F + 1) return;

				bool alto = true, bajo = true;
				for (int k = 1; k <= F; k++)
				{
					if (Highs[1][F] <= Highs[1][F + k] || Highs[1][F] <= Highs[1][F - k]) alto = false;
					if (Lows[1][F]  >= Lows[1][F + k]  || Lows[1][F]  >= Lows[1][F - k])  bajo = false;
					if (!alto && !bajo) break;
				}
				if (alto) { Apilar(pilaSH, Highs[1][F]); refSH = Highs[1][F]; }
				if (bajo) { Apilar(pilaSL, Lows[1][F]);  refSL = Lows[1][F];  }

				if (pilaSH.Count == 2 && pilaSL.Count == 2)
				{
					bool HH = pilaSH[1] > pilaSH[0], HL = pilaSL[1] > pilaSL[0];
					bool LH = pilaSH[1] < pilaSH[0], LL = pilaSL[1] < pilaSL[0];
					// estricto: si no hay patron limpio, es transicion. No hereda.
					tendencia = (HH && HL) ? 1 : (LH && LL) ? -1 : 0;
				}
				return;
			}

			// ================= serie primaria (1m): eventos y narracion =================
			if (CurrentBars[0] < Math.Max(PeriodoATR, 20)) return;

			double tol = ToleranciaTicks * TickSize;
			double atr = ATR(PeriodoATR)[0];
			double sh  = refSH;   // referencia viva, independiente de la pila de tendencia
			double sl  = refSL;

			// ---------- sweeps: mecha perfora, cierre regresa ----------
			if (!double.IsNaN(sh) && High[0] > sh + tol && Close[0] < sh)
				RegistrarSweep(-1);
			if (!double.IsNaN(sl) && Low[0]  < sl - tol && Close[0] > sl)
				RegistrarSweep(1);

			for (int q = sweeps.Count - 1; q >= 0; q--)
			{
				Sweep s = sweeps[q];
				if (CurrentBar - s.Barra > VentanaSweep) { sweeps.RemoveAt(q); continue; }
				if ((Close[0] - s.Ref) * s.Dir >= atr * UmbralReversionATR)
				{
					nSweepsReversion++;
					sweeps.RemoveAt(q);
				}
			}

			// ---------- rupturas estructurales con el cierre ----------
			if (!double.IsNaN(sh) && Close[0] > sh)
			{
				bool esBOS = tendencia >= 0;
				NuevoEvento(esBOS ? "BOS↑" : "CHoCH↑", sh, 1, esBOS);
				refSH = double.NaN;              // consumida; la pila NO se toca
				if (!esBOS) { reversionPendiente = true; dirPendiente = 1; }
			}
			if (!double.IsNaN(sl) && Close[0] < sl)
			{
				bool esBOS = tendencia <= 0;
				NuevoEvento(esBOS ? "BOS↓" : "CHoCH↓", sl, -1, esBOS);
				refSL = double.NaN;
				if (!esBOS) { reversionPendiente = true; dirPendiente = -1; }
			}

			// ---------- resolver retest pendiente ----------
			if (retestBarra >= 0 && !retestTocado && CurrentBar > retestBarra)
			{
				bool toca = retestDir == 1 ? Low[0] <= retestNivel + tol
										   : High[0] >= retestNivel - tol;
				if (toca)
				{
					retestTocado = true;
					nRetestTocados++; nRetestResueltos++;
					barraAccion = CurrentBar;
					textoAccion = ">>> RETEST DADO en " + retestNivel.ToString("0.00") + " <<<";
					if (State == State.Realtime && AlertaRetest)
						Alert("mgxRt" + idZona, Priority.Medium,
							"MAGMAX: RETEST dado en " + retestNivel.ToString("0.00"),
							NinjaTrader.Core.Globals.InstallDir + @"\sounds\Alert3.wav",
							10, Brushes.Black, ColorZonaRetest);
					if (MostrarZonasRetest)
						Draw.Text(this, "rt" + idZona, "RETEST", 0,
							retestDir == 1 ? Low[0] - 4 * TickSize : High[0] + 4 * TickSize,
							ColorZonaRetest);
				}
				else if (CurrentBar - retestBarra > VentanaRetest)
				{
					nRetestResueltos++;
					retestBarra = -1;
				}
			}

			// ---------- vigencia del parpadeo ----------
			accionActiva = UsarParpadeo && barraAccion >= 0 && CurrentBar - barraAccion <= VelasAccion;
			if (!accionActiva && bannerPuesto)
			{
				RemoveDrawObject("bannerAccion");
				RestaurarZona();
				bannerPuesto = false;
			}

			// ---------- panel ----------
			if (MostrarPanel) PintarPanel(atr);
		}

		private void Apilar(List<double> pila, double p)
		{
			pila.Add(p);
			if (pila.Count > 2) pila.RemoveAt(0);
		}

		private void RegistrarSweep(int dirReversion)
		{
			nSweeps++;
			sweeps.Add(new Sweep { Barra = CurrentBar, Dir = dirReversion, Ref = Close[0] });
			barraUltimoSweep = CurrentBar; dirUltimoSweep = dirReversion;
			if (State == State.Realtime && AlertaSweep)
				Alert("mgxSw" + CurrentBar, Priority.Low,
					"MAGMAX: sweep, posible reversion " + (dirReversion == 1 ? "arriba" : "abajo"),
					NinjaTrader.Core.Globals.InstallDir + @"\sounds\Alert4.wav",
					10, Brushes.Black, ColorSweep);
			if (MostrarSweeps)
				Draw.Diamond(this, "sw" + CurrentBar, false, 0,
					dirReversion == 1 ? Low[0] - 3 * TickSize : High[0] + 3 * TickSize,
					ColorSweep);
		}

		private void NuevoEvento(string tipo, double nivel, int dir, bool esBOS)
		{
			// transiciones medidas en vivo: BOS -> ¿siguiente en la misma direccion?
			if (eventoPrevio == "BOS↑") { nBOSup++; if (tipo == "BOS↑") nBOSupSigueUp++; }
			if (eventoPrevio == "BOS↓") { nBOSdn++; if (tipo == "BOS↓") nBOSdnSigueDn++; }
			eventoPrevio = tipo;

			nEventos++;
			ultimoEvento = tipo; barraEvento = CurrentBar; nivelEvento = nivel;
			if (esBOS && reversionPendiente && dir == dirPendiente)
				reversionPendiente = false;   // CHoCH confirmado; la tendencia la fijan los swings

			// cerrar retest anterior si seguia pendiente (no tocado = no)
			if (retestBarra >= 0 && !retestTocado) nRetestResueltos++;

			// parpadeo: evento nuevo = posible accion (el retest suele venir)
			RestaurarZona();
			barraAccion = CurrentBar;
			textoAccion = ">>> " + tipo + " en " + nivel.ToString("0.00") + "  -  espera el retest <<<";

			// abrir zona de retest nueva
			idZona++;
			retestNivel = nivel; retestBarra = CurrentBar; retestDir = dir; retestTocado = false;

			Brush b = dir == 1 ? ColorAlcista : ColorBajista;
			if (State == State.Realtime && AlertaEventos)
				Alert("mgxEv" + idZona, Priority.High,
					"MAGMAX: " + tipo + " en " + nivel.ToString("0.00"),
					NinjaTrader.Core.Globals.InstallDir + @"\sounds\Alert2.wav",
					10, Brushes.Black, b);
			if (MostrarEtiquetasEvento)
				Draw.Text(this, "ev" + idZona, tipo, 0,
					dir == 1 ? nivel - 6 * TickSize : nivel + 6 * TickSize, b);
			zonaT1 = Time[0]; zonaT2 = Time[0].AddMinutes(VentanaRetest);
			zonaY1 = nivel - ToleranciaTicks * TickSize;
			zonaY2 = nivel + ToleranciaTicks * TickSize;
			zonaBorde = b; zonaViva = MostrarZonasRetest;
			if (MostrarZonasRetest)
				Draw.Rectangle(this, "zn" + idZona, false, zonaT1, zonaY1, zonaT2, zonaY2,
					b, ColorZonaRetest, 12);
		}

		private void PintarPanel(double atr)
		{
			string estado =
				reversionPendiente ? (dirPendiente == 1 ? "REVERSION↑ PENDIENTE" : "REVERSION↓ PENDIENTE")
				: tendencia == 1   ? "ALCISTA (HH+HL)"
				: tendencia == -1  ? "BAJISTA (LH+LL)"
				: "RANGO / TRANSICION";

			string t = "MAGMAX " + VERSION + "   estructura " + MinutosEstructura + "m";
			t += "\nESTRUCTURA: " + estado;

			if (barraEvento >= 0)
				t += string.Format("\nPASANDO:  {0} hace {1} velas en {2}",
					ultimoEvento, CurrentBar - barraEvento, nivelEvento.ToString("0.00"));
			else
				t += "\nPASANDO:  esperando el primer evento estructural";

			// -------- escenarios con frecuencia --------
			if (barraEvento >= 0)
			{
				bool arriba = ultimoEvento.EndsWith("↑");
				double invalida = arriba
					? (pilaSL.Count > 0 ? pilaSL[pilaSL.Count - 1] : double.NaN)
					: (pilaSH.Count > 0 ? pilaSH[pilaSH.Count - 1] : double.NaN);

				if (ultimoEvento.StartsWith("BOS"))
				{
					int baseCont = arriba ? BASE_CONT_UP : BASE_CONT_DOWN;
					string rt = retestTocado ? "retest DADO en " + retestNivel.ToString("0.00")
						: string.Format("retest de {0} (base {1}%)", retestNivel.ToString("0.00"), BASE_RETEST);
					t += "\nPOSIBLE:  " + rt;
					t += string.Format("\n          continuacion {0} (base {1}%)", arriba ? "arriba" : "abajo", baseCont);
				}
				else
				{
					int baseConf = arriba ? BASE_CHOCH_UP : BASE_CHOCH_DOWN;
					t += string.Format("\nPOSIBLE:  confirmar reversion con BOS{0} (base {1}%, muestra chica)",
						arriba ? "↑" : "↓", baseConf);
				}
				if (!double.IsNaN(invalida))
					t += string.Format("\nINVALIDA: cierre {0} de {1}",
						arriba ? "debajo" : "encima", invalida.ToString("0.00"));
			}

			if (barraUltimoSweep >= 0 && CurrentBar - barraUltimoSweep <= VentanaSweep)
				t += string.Format("\nSWEEP:    hace {0} velas, reversion {1} (base {2}%)",
					CurrentBar - barraUltimoSweep, dirUltimoSweep == 1 ? "arriba" : "abajo", BASE_SWEEP);

			// -------- lo medido EN ESTE grafico --------
			if (MostrarBasesHistoricas && nEventos >= 10)
			{
				t += string.Format("\n--- en este grafico: {0} eventos ---", nEventos);
				if (nRetestResueltos >= 10)
					t += string.Format("\nretest {0}%  ({1}/{2})",
						(int)Math.Round(100.0 * nRetestTocados / nRetestResueltos), nRetestTocados, nRetestResueltos);
				if (nBOSup >= 10)
					t += string.Format("   BOS↑ sigue↑ {0}%", (int)Math.Round(100.0 * nBOSupSigueUp / nBOSup));
				if (nBOSdn >= 10)
					t += string.Format("   BOS↓ sigue↓ {0}%", (int)Math.Round(100.0 * nBOSdnSigueDn / nBOSdn));
				if (nSweeps >= 10)
					t += string.Format("\nsweeps {0}, reversion {1}%", nSweeps,
						(int)Math.Round(100.0 * nSweepsReversion / nSweeps));
			}

			TextPosition pos = PosicionPanel == 0 ? TextPosition.TopLeft
							 : PosicionPanel == 1 ? TextPosition.TopRight
							 : PosicionPanel == 2 ? TextPosition.BottomLeft
							 : TextPosition.BottomRight;
			Draw.TextFixed(this, "panelMAGMAX", t, pos,
				Brushes.Gainsboro, new SimpleFont("Consolas", 13),
				Brushes.Transparent, Brushes.Black, 60);
		}

		#region Propiedades
		[NinjaScriptProperty] [Range(5, 240)]
		[Display(Name = "Minutos de la estructura", Order = 1, GroupName = "1 Estructura")]
		public int MinutosEstructura { get; set; }

		[NinjaScriptProperty] [Range(2, 20)]
		[Display(Name = "Fuerza del swing (velas por lado)", Order = 2, GroupName = "1 Estructura")]
		public int FuerzaSwing { get; set; }

		[NinjaScriptProperty] [Range(0, 20)]
		[Display(Name = "Tolerancia de toque (ticks)", Order = 3, GroupName = "1 Estructura")]
		public int ToleranciaTicks { get; set; }

		[NinjaScriptProperty] [Range(5, 480)]
		[Display(Name = "Ventana del retest (velas)", Order = 1, GroupName = "2 Retest y sweep")]
		public int VentanaRetest { get; set; }

		[NinjaScriptProperty] [Range(5, 480)]
		[Display(Name = "Ventana del sweep (velas)", Order = 2, GroupName = "2 Retest y sweep")]
		public int VentanaSweep { get; set; }

		[NinjaScriptProperty] [Range(0.2, 5.0)]
		[Display(Name = "Reversion del sweep (multiplos de ATR)", Order = 3, GroupName = "2 Retest y sweep")]
		public double UmbralReversionATR { get; set; }

		[NinjaScriptProperty] [Range(2, 100)]
		[Display(Name = "Periodo del ATR", Order = 4, GroupName = "2 Retest y sweep")]
		public int PeriodoATR { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Mostrar panel", Order = 1, GroupName = "3 Visual")]
		public bool MostrarPanel { get; set; }

		[NinjaScriptProperty] [Range(0, 3)]
		[Display(Name = "Posicion del panel (0 arr-izq, 1 arr-der, 2 abj-izq, 3 abj-der)", Order = 10, GroupName = "3 Visual")]
		public int PosicionPanel { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Sonido en BOS y CHoCH", Order = 1, GroupName = "4 Alertas")]
		public bool AlertaEventos { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Sonido cuando el retest se da", Order = 2, GroupName = "4 Alertas")]
		public bool AlertaRetest { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Sonido en sweeps (ruidoso)", Order = 3, GroupName = "4 Alertas")]
		public bool AlertaSweep { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Parpadear cuando haya posible accion", Order = 1, GroupName = "5 Parpadeo")]
		public bool UsarParpadeo { get; set; }

		[NinjaScriptProperty] [Range(1, 120)]
		[Display(Name = "Cuantas velas dura el parpadeo", Order = 2, GroupName = "5 Parpadeo")]
		public int VelasAccion { get; set; }

		[NinjaScriptProperty] [Range(150, 2000)]
		[Display(Name = "Velocidad del parpadeo (ms)", Order = 3, GroupName = "5 Parpadeo")]
		public int VelocidadParpadeoMs { get; set; }

		[NinjaScriptProperty] [Range(0, 3)]
		[Display(Name = "Posicion del aviso (0 arr-izq, 1 arr-der, 2 abj-izq, 3 abj-der)", Order = 4, GroupName = "5 Parpadeo")]
		public int PosicionBanner { get; set; }

		[XmlIgnore]
		[Display(Name = "Color del aviso", Order = 5, GroupName = "5 Parpadeo")]
		public Brush ColorBanner { get; set; }
		[Browsable(false)]
		public string ColorBannerSerializable
		{ get { return Serialize.BrushToString(ColorBanner); } set { ColorBanner = Serialize.StringToBrush(value); } }

		[NinjaScriptProperty]
		[Display(Name = "Mostrar zonas de retest", Order = 2, GroupName = "3 Visual")]
		public bool MostrarZonasRetest { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Mostrar sweeps (rombos)", Order = 3, GroupName = "3 Visual")]
		public bool MostrarSweeps { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Mostrar etiquetas BOS/CHoCH", Order = 4, GroupName = "3 Visual")]
		public bool MostrarEtiquetasEvento { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Mostrar tasas medidas en el grafico", Order = 5, GroupName = "3 Visual")]
		public bool MostrarBasesHistoricas { get; set; }

		[XmlIgnore]
		[Display(Name = "Color alcista", Order = 6, GroupName = "3 Visual")]
		public Brush ColorAlcista { get; set; }
		[Browsable(false)]
		public string ColorAlcistaSerializable
		{ get { return Serialize.BrushToString(ColorAlcista); } set { ColorAlcista = Serialize.StringToBrush(value); } }

		[XmlIgnore]
		[Display(Name = "Color bajista", Order = 7, GroupName = "3 Visual")]
		public Brush ColorBajista { get; set; }
		[Browsable(false)]
		public string ColorBajistaSerializable
		{ get { return Serialize.BrushToString(ColorBajista); } set { ColorBajista = Serialize.StringToBrush(value); } }

		[XmlIgnore]
		[Display(Name = "Color de la zona de retest", Order = 8, GroupName = "3 Visual")]
		public Brush ColorZonaRetest { get; set; }
		[Browsable(false)]
		public string ColorZonaRetestSerializable
		{ get { return Serialize.BrushToString(ColorZonaRetest); } set { ColorZonaRetest = Serialize.StringToBrush(value); } }

		[XmlIgnore]
		[Display(Name = "Color del sweep", Order = 9, GroupName = "3 Visual")]
		public Brush ColorSweep { get; set; }
		[Browsable(false)]
		public string ColorSweepSerializable
		{ get { return Serialize.BrushToString(ColorSweep); } set { ColorSweep = Serialize.StringToBrush(value); } }
		#endregion
	}
}
