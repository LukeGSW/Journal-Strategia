# app.py — Kriterion Quant Journal (UI rifinita + sidebar fix)
# Upgrade:
#   1) Pulsante "Crea nuovo account" nella pagina di login (persistenza su foglio Users)
#   2) Grafici a torta per ticker in testa al Journal (Cap.Iniziale, BTD Std, BTD Boost,
#      Premi Incassati, Premi Reinvestiti)

from __future__ import annotations
import re
import streamlit as st
import pandas as pd
import bcrypt
import plotly.graph_objects as go
from datetime import datetime
import data_manager as dm

st.set_page_config(
    page_title="Diario di Bordo Quantitativo - Kriterion Quant",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",  # sidebar aperta di default (il toggle ora è visibile)
)

# ------------------------ Preferenze UI (sidebar) ------------------------
with st.sidebar.expander("🎨 Impostazioni UI", expanded=False):
    base_font_px = st.slider("Grandezza caratteri (px)", 12, 18, 14, 1)
    row_height_px = st.slider("Densità tabella (altezza riga, px)", 28, 44, 32, 2)
    accent_color = st.color_picker("Colore accento", "#4F46E5")
    st.caption("Agiscono solo sull’aspetto grafico.")

def load_css(base_font: int, row_h: int, accent: str) -> None:
    st.markdown(f"""
    <style>
      :root {{
        --bg-grad-1:#0b1020; --bg-grad-2:#151a2c;
        --surface-0:#111827; --surface-1:#0f172a;
        --border:#2a3448; --text-0:#e5e7eb; --muted:#94a3b8;
        --accent:{accent}; --radius:14px; --fs-base:{base_font}px; --row-h:{row_h}px;
      }}

      /* Sfondo app e tipografia base */
      html, body, .main .block-container {{
        background: radial-gradient(1200px 800px at 10% 0%, var(--bg-grad-1), var(--bg-grad-2)) fixed;
      }}
      html, body {{ font-size: var(--fs-base); color: var(--text-0); }}
      .main .block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; }}

      /* Header visibile (serve per il toggle della sidebar) */
      header[data-testid="stHeader"] {{
        background: linear-gradient(180deg, rgba(15,23,42,.95) 0%, rgba(2,6,23,.9) 100%) !important;
        border-bottom: 1px solid var(--border);
        backdrop-filter: blur(6px);
      }}

      /* Titoli */
      h1 {{ font-weight:800; letter-spacing:.2px; margin:.75rem 0 1rem 0; }}
      h2 {{ font-weight:700; margin:1.25rem 0 .75rem 0; }}

      /* Card base */
      form, .kv-card {{
        background: var(--surface-0); border:1px solid var(--border);
        border-radius:var(--radius); padding:.9rem;
      }}

      /* Pulsanti */
      .stButton > button, button[kind="primary"] {{
        background: var(--accent) !important; color:#fff !important; border:1px solid transparent !important;
        border-radius:12px !important; padding:.45rem .9rem !important; font-weight:700 !important;
      }}
      .stButton > button:hover, button[kind="primary"]:hover {{ filter: brightness(1.05); transform: translateY(-1px); }}

      /* Input */
      input, textarea, select {{
        background: var(--surface-1) !important; color: var(--text-0) !important;
        border:1px solid var(--border) !important; border-radius:12px !important;
      }}

      /* Tabelle */
      .stDataFrame {{ border:1px solid var(--border); border-radius:12px; overflow:hidden; }}
      .stDataFrame thead tr th {{
        position: sticky; top: 0; z-index: 1;
        background: var(--surface-1) !important; color:#a7b0c0 !important;
        text-transform: uppercase; font-size:.8rem !important; letter-spacing:.03em;
      }}
      .stDataFrame tbody tr:nth-child(odd) td {{ background: rgba(255,255,255,0.02); }}
      .stDataFrame tbody tr:hover td {{ background: rgba(255,255,255,0.05) !important; }}
      .stDataFrame tbody td {{ height: var(--row-h) !important; vertical-align: middle; }}
      .stDataFrame tbody td:not(:first-child) {{ text-align: right; }}

      /* Sidebar: FIX overflow, spaziature, leggibilità */
      section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #0d1326 0%, #0b1020 100%) !important;
        border-right:1px solid var(--border);
        overflow-y: auto !important;           /* evita accavallamenti */
        overflow-x: hidden !important;
        padding-right: .35rem;                  /* evita scrollbar che copre contenuto */
        min-width: 18rem;                       /* evita sidebar troppo stretta */
      }}
      section[data-testid="stSidebar"] * {{
        line-height: 1.25;                      /* maggiore respiro */
        word-break: break-word;                 /* spezza parole lunghe */
      }}
      section[data-testid="stSidebar"] .stSlider > div,
      section[data-testid="stSidebar"] .stColorPicker > div {{
        padding-top: .25rem; padding-bottom: .25rem;
      }}
      section[data-testid="stSidebar"] .stExpander {{
        border: 1px solid var(--border);
        border-radius: 12px;
      }}
      section[data-testid="stSidebar"] .streamlit-expanderHeader {{
        font-weight: 700;
      }}

      /* Nascondo solo MainMenu e footer (NON l'header, serve il toggle!) */
      #MainMenu, footer {{ visibility: hidden; }}
    </style>
    """, unsafe_allow_html=True)

load_css(base_font=base_font_px, row_h=row_height_px, accent=accent_color)

# ------------------------ Utility formato ------------------------
def format_money_or_dash(value) -> str:
    try:
        if pd.isna(value) or float(value) == 0.0:
            return "-"
        return f"${float(value):,.2f}"
    except Exception:
        return "-"

def format_pct_or_dash(value) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value)*100:.2f}%"
    except Exception:
        return "-"

# ------------------------ Cassa Residua per BTD ------------------------
# Regole strategia Kriterion Quant:
#   - Strategia MENSILE  : cassa BTD iniziale = 1× capitale iniziale
#   - Strategia SETTIMANALE: cassa BTD iniziale = 2× capitale iniziale
#                            (il capitale iniziale rappresenta 1/3 del totale impiegato)
FREQUENZE = ["mensile", "settimanale"]

def get_cassa_multiplier(frequenza: str) -> float:
    s = str(frequenza).strip().lower() if frequenza is not None else ""
    if s.startswith("sett") or s in ("weekly", "w"):
        return 2.0
    return 1.0

# ------------------------ Connessioni ------------------------
SHEET_NAME = "KriterionJournalData"
WORKSHEET_TITLE = "Foglio1"
TICKERS_SHEET_TITLE = "Tickers"
USERS_SHEET_TITLE = "Users"

worksheet     = dm.get_google_sheet(SHEET_NAME, WORKSHEET_TITLE)        if "gcp_service_account" in st.secrets else None
ws_tickers    = dm.get_tickers_sheet(SHEET_NAME, TICKERS_SHEET_TITLE)   if "gcp_service_account" in st.secrets else None
ws_users      = dm.get_users_sheet(SHEET_NAME, USERS_SHEET_TITLE)       if "gcp_service_account" in st.secrets else None

# ------------------------ Costruzione credenziali (secrets + foglio Users) ------------------------
def build_credentials() -> dict:
    """Unisce gli utenti definiti nei Secrets con quelli registrati via app sul foglio Users."""
    credentials = {"usernames": {}}

    # 1) Utenti da secrets
    try:
        sec_users = st.secrets["credentials"]["usernames"]
        for uname, u in sec_users.items():
            credentials["usernames"][str(uname).strip().lower()] = {
                "name": u["name"], "email": u["email"], "password": u["password"]
            }
    except Exception:
        # ok se non ci sono utenti nei secrets, gli account verranno tutti dal foglio
        pass

    # 2) Utenti dal foglio "Users"
    try:
        users_df = dm.get_all_users(ws_users) if ws_users is not None else pd.DataFrame()
        if not users_df.empty:
            for _, r in users_df.iterrows():
                uname = str(r["username"]).strip().lower()
                if not uname or uname == "nan":
                    continue
                credentials["usernames"][uname] = {
                    "name": str(r["name"]),
                    "email": str(r["email"]),
                    "password": str(r["password"]),
                }
    except Exception as e:
        st.warning(f"Impossibile leggere il foglio Users: {e}")

    return credentials

# ------------------------ Autenticazione Semplificata ------------------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("📈 Diario di Bordo Quantitativo")
    st.subheader("Accesso Riservato")
    
    with st.form("login_form"):
        input_username = st.text_input("Username").strip()
        input_password = st.text_input("Password", type="password").strip()
        submit_button = st.form_submit_button("Accedi")
        
        if submit_button:
            # Controlla se la sezione [utenti] esiste nei Secrets e se l'username è presente
            if "utenti" in st.secrets and input_username in st.secrets["utenti"]:
                # Verifica la password in chiaro
                if input_password == st.secrets["utenti"][input_username]:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = input_username
                    st.rerun()
                else:
                    st.error("Password errata.")
            else:
                st.error("Utente non autorizzato.")
    st.stop()  # Ferma il rendering del resto della pagina se non loggato

# Variabile per filtrare i dati nel resto del codice
username = st.session_state["username"]

# Gestione Sidebar post-login
st.sidebar.title(f"Benvenuto, *{username}*")
if st.sidebar.button("Logout"):
    st.session_state["logged_in"] = False
    st.session_state["username"] = None
    st.rerun()
st.sidebar.markdown("---")

st.title("📈 Diario di Bordo Quantitativo")

# ------------------------ Connessioni Database ------------------------
if worksheet is None or ws_tickers is None:
    st.error("🚨 Connessione ai worksheet non riuscita. Verifica le credenziali GCP in secrets.")
    st.stop()

# ------------------------ Metriche ------------------------
def compute_aggregates(user_ops: pd.DataFrame) -> pd.DataFrame:
    if user_ops.empty:
        return pd.DataFrame(columns=["ticker", "inc", "reinv", "std", "bst"])
    agg = (
        user_ops.groupby("ticker")
        .agg(inc=("premioIncassato", "sum"),
             reinv=("premioReinvestito", "sum"),
             std=("btdStandard", "sum"),
             bst=("btdBoost", "sum"))
        .reset_index()
    )
    for c in ["inc", "reinv", "std", "bst"]:
        agg[c] = pd.to_numeric(agg[c], errors="coerce").fillna(0.0)
    return agg

def compute_kpi_tables(user_ops: pd.DataFrame, user_tickers_df: pd.DataFrame):
    k_cfg = user_tickers_df.copy().rename(columns={"capitaleIniziale": "Capitale Iniziale"})
    k_cfg["Capitale Iniziale"] = pd.to_numeric(k_cfg["Capitale Iniziale"], errors="coerce").fillna(0.0)

    agg = compute_aggregates(user_ops)
    kpi = k_cfg.merge(agg, how="left", on="ticker")
    for c in ["inc", "reinv", "std", "bst"]:
        kpi[c] = pd.to_numeric(kpi[c], errors="coerce").fillna(0.0)

    kpi["Investito Totale"] = kpi["reinv"] + kpi["std"] + kpi["bst"]
    kpi["Entrate Totali"] = kpi["inc"]
    kpi["Base Finanziata"] = kpi["Capitale Iniziale"] + kpi["Entrate Totali"]
    kpi["Tasso Reinvestimento"] = kpi.apply(lambda r: (r["reinv"] / r["inc"]) if r["inc"] > 0 else pd.NA, axis=1)
    kpi["Utilization"] = kpi.apply(lambda r: (r["Investito Totale"] / r["Base Finanziata"]) if r["Base Finanziata"] > 0 else pd.NA, axis=1)
    kpi["Cash Residuo"] = kpi["Base Finanziata"] - kpi["Investito Totale"]

    # Cassa BTD dedicata (mensile=1×, settimanale=2×)
    kpi["Cassa Multiplier"] = kpi["frequenza"].map(get_cassa_multiplier)
    kpi["Cassa Iniziale BTD"] = kpi["Capitale Iniziale"] * kpi["Cassa Multiplier"]
    kpi["Cassa Residua BTD"] = (kpi["Cassa Iniziale BTD"] - kpi["std"] - kpi["bst"]).clip(lower=0.0)
    kpi["Cassa BTD Consumata %"] = kpi.apply(
        lambda r: ((r["std"] + r["bst"]) / r["Cassa Iniziale BTD"]) if r["Cassa Iniziale BTD"] > 0 else pd.NA,
        axis=1,
    )

    # conteggi
    if user_ops.empty:
        counts = pd.DataFrame(columns=["ticker","n_ops","n_inc","n_reinv","n_btd_std","n_btd_bst"])
    else:
        cnt_all = user_ops.groupby("ticker").size().rename("n_ops")
        cnt_inc = user_ops[user_ops["type"]=="Incasso Premio"].groupby("ticker").size().rename("n_inc")
        cnt_rei = user_ops[user_ops["type"]=="Reinvestimento Premio"].groupby("ticker").size().rename("n_reinv")
        cnt_std = (user_ops[user_ops["btdStandard"].fillna(0.0)>0.0].groupby("ticker").size().rename("n_btd_std"))
        cnt_bst = (user_ops[user_ops["btdBoost"].fillna(0.0)>0.0].groupby("ticker").size().rename("n_btd_bst"))
        counts = pd.concat([cnt_all, cnt_inc, cnt_rei, cnt_std, cnt_bst], axis=1).fillna(0.0).reset_index()

    kpi = kpi.merge(counts, how="left", on="ticker")
    for c in ["n_ops","n_inc","n_reinv","n_btd_std","n_btd_bst"]:
        if c in kpi.columns:
            kpi[c] = pd.to_numeric(kpi[c], errors="coerce").fillna(0).astype(int)
        else:
            kpi[c] = 0

    if user_ops.empty:
        span = pd.DataFrame(columns=["ticker","first_date","last_date","giorni_attivi"])
    else:
        span = user_ops.groupby("ticker").agg(first_date=("date","min"), last_date=("date","max")).reset_index()
        span["giorni_attivi"] = (span["last_date"] - span["first_date"]).dt.days.clip(lower=0).fillna(0).astype("Int64")

    kpi = kpi.merge(span, how="left", on="ticker")

    kpi_ticker = kpi.loc[kpi["attivo"], [
        "ticker", "frequenza", "Capitale Iniziale", "Cassa Iniziale BTD",
        "Entrate Totali", "reinv","std","bst",
        "Investito Totale", "Cassa Residua BTD", "Cassa BTD Consumata %",
        "Cash Residuo", "Tasso Reinvestimento", "Utilization",
        "n_ops","n_inc","n_reinv","n_btd_std","n_btd_bst",
        "first_date","last_date","giorni_attivi"
    ]].rename(columns={
        "ticker": "Asset",
        "frequenza": "Frequenza",
        "reinv": "Premi Reinvestiti",
        "std": "BTD Standard",
        "bst": "BTD Boost",
        "n_ops": "N. Operazioni",
        "n_inc": "N. Incassi",
        "n_reinv": "N. Reinvestimenti",
        "n_btd_std": "N. BTD Std",
        "n_btd_bst": "N. BTD Boost",
        "first_date": "Primo Movimento",
        "last_date": "Ultimo Movimento",
        "giorni_attivi": "Giorni Attivi",
    }).copy()

    if kpi_ticker.empty:
        kpi_port = pd.DataFrame([{
            "Tickers Attivi": 0, "Capitale Iniziale Totale": 0.0,
            "Cassa Iniziale BTD Totale": 0.0, "Cassa Residua BTD Totale": 0.0,
            "Entrate Totali": 0.0, "Investito Totale": 0.0, "Cash Residuo Totale": 0.0,
            "Tasso Reinvestimento Portafoglio": pd.NA, "Utilization Portafoglio": pd.NA,
            "Operazioni Totali": 0
        }])
    else:
        cap0 = kpi_ticker["Capitale Iniziale"].sum()
        cassa0 = kpi_ticker["Cassa Iniziale BTD"].sum()
        cassa_res = kpi_ticker["Cassa Residua BTD"].sum()
        entr = kpi_ticker["Entrate Totali"].sum()
        invt = kpi_ticker["Investito Totale"].sum()
        cash = kpi_ticker["Cash Residuo"].sum()
        nops = kpi_ticker["N. Operazioni"].sum()
        t_rei = (kpi_ticker["Premi Reinvestiti"].sum() / entr) if entr > 0 else pd.NA
        base_fin = cap0 + entr
        utilz = (invt / base_fin) if base_fin > 0 else pd.NA
        kpi_port = pd.DataFrame([{
            "Tickers Attivi": int(kpi_ticker["Asset"].nunique()),
            "Capitale Iniziale Totale": cap0,
            "Cassa Iniziale BTD Totale": cassa0,
            "Cassa Residua BTD Totale": cassa_res,
            "Entrate Totali": entr,
            "Investito Totale": invt, "Cash Residuo Totale": cash,
            "Tasso Reinvestimento Portafoglio": t_rei, "Utilization Portafoglio": utilz,
            "Operazioni Totali": int(nops)
        }])
    return kpi_ticker, kpi_port

def compute_monthly_trend(user_ops: pd.DataFrame) -> pd.DataFrame:
    if user_ops.empty:
        return pd.DataFrame(columns=["month","Incassi","Reinvestimenti","BTD Standard","BTD Boost","Investito Totale"])
    df = user_ops.copy()
    df["month"] = pd.to_datetime(df["date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    grp = df.groupby("month").agg(
        Incassi=("premioIncassato","sum"),
        Reinvestimenti=("premioReinvestito","sum"),
        BTD_Standard=("btdStandard","sum"),
        BTD_Boost=("btdBoost","sum")
    ).reset_index()
    grp["Investito Totale"] = grp["Reinvestimenti"] + grp["BTD_Standard"] + grp["BTD_Boost"]
    grp = grp.sort_values("month")
    if len(grp) > 12: grp = grp.tail(12)
    return grp.rename(columns={"BTD_Standard":"BTD Standard","BTD_Boost":"BTD Boost"})

# ------------------------ Pie charts per ticker ------------------------
PIE_COLORS = {
    "Capitale Iniziale":  "#4F46E5",  # accent indigo
    "BTD Standard":       "#22C55E",  # green
    "BTD Boost":          "#F59E0B",  # amber
    "Premi Incassati":    "#06B6D4",  # cyan
    "Premi Reinvestiti":  "#EC4899",  # pink
    "Cassa Residua BTD":  "#64748B",  # slate (cash-like neutral)
}

def build_ticker_pie(ticker: str, cap_iniziale: float, btd_std: float, btd_boost: float,
                     premi_inc: float, premi_rei: float,
                     cassa_residua: float = 0.0,
                     frequenza: str = "mensile") -> go.Figure:
    labels = ["Capitale Iniziale", "BTD Standard", "BTD Boost",
              "Premi Incassati", "Premi Reinvestiti", "Cassa Residua BTD"]
    values = [
        max(float(cap_iniziale or 0.0), 0.0),
        max(float(btd_std or 0.0), 0.0),
        max(float(btd_boost or 0.0), 0.0),
        max(float(premi_inc or 0.0), 0.0),
        max(float(premi_rei or 0.0), 0.0),
        max(float(cassa_residua or 0.0), 0.0),
    ]
    colors = [PIE_COLORS[l] for l in labels]

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.55,
        sort=False,
        marker=dict(colors=colors, line=dict(color="#0b1020", width=2)),
        textinfo="percent",
        textfont=dict(color="#e5e7eb", size=11),
        hovertemplate="<b>%{label}</b><br>$%{value:,.2f}<br>%{percent}<extra></extra>",
    )])
    total = sum(values)
    freq_label = str(frequenza).capitalize()
    fig.update_layout(
        title=dict(text=f"<b>{ticker}</b> · <span style='color:#94a3b8;font-weight:500;font-size:12px'>{freq_label}</span>",
                   x=0.5, xanchor="center",
                   font=dict(color="#e5e7eb", size=15)),
        annotations=[dict(
            text=f"<b>${total:,.0f}</b><br><span style='font-size:10px;color:#94a3b8'>Totale</span>",
            x=0.5, y=0.5, font=dict(color="#e5e7eb", size=13), showarrow=False
        )],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=True,
        legend=dict(
            orientation="h", y=-0.18, x=0.5, xanchor="center",
            font=dict(color="#cbd5e1", size=10), bgcolor="rgba(0,0,0,0)"
        ),
        margin=dict(l=10, r=10, t=40, b=20),
        height=380,
    )
    return fig

def render_ticker_pies(user_ops: pd.DataFrame, user_tickers_df: pd.DataFrame):
    """Renderizza una griglia di pie chart, uno per ogni ticker attivo configurato."""
    if user_tickers_df is None or user_tickers_df.empty:
        st.info("Configura almeno un ticker attivo nella tab **Portafoglio** per visualizzare i grafici.")
        return

    cfg = user_tickers_df.copy()
    cfg["capitaleIniziale"] = pd.to_numeric(cfg["capitaleIniziale"], errors="coerce").fillna(0.0)
    cfg = cfg.loc[cfg["attivo"] == True].copy()
    if cfg.empty:
        st.info("Nessun ticker attivo: attiva almeno un ticker nella tab **Portafoglio**.")
        return

    agg = compute_aggregates(user_ops)
    merged = cfg.merge(agg, how="left", on="ticker")
    for c in ["inc", "reinv", "std", "bst"]:
        merged[c] = pd.to_numeric(merged[c], errors="coerce").fillna(0.0)

    # Cassa Residua BTD per ticker
    merged["cassa_mult"] = merged["frequenza"].map(get_cassa_multiplier)
    merged["cassa_iniziale"] = merged["capitaleIniziale"] * merged["cassa_mult"]
    merged["cassa_residua"] = (merged["cassa_iniziale"] - merged["std"] - merged["bst"]).clip(lower=0.0)
    merged = merged.sort_values("ticker")

    tickers = merged["ticker"].tolist()
    n = len(tickers)
    cols_per_row = 3
    for i in range(0, n, cols_per_row):
        row = st.columns(cols_per_row)
        for j, ticker in enumerate(tickers[i:i+cols_per_row]):
            r = merged.loc[merged["ticker"] == ticker].iloc[0]
            fig = build_ticker_pie(
                ticker=str(ticker),
                cap_iniziale=r["capitaleIniziale"],
                btd_std=r["std"],
                btd_boost=r["bst"],
                premi_inc=r["inc"],
                premi_rei=r["reinv"],
                cassa_residua=r["cassa_residua"],
                frequenza=r["frequenza"],
            )
            with row[j]:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.caption(
        "ℹ️ *Premi Reinvestiti* è un sottoinsieme dei *Premi Incassati* (mostrato separatamente per evidenziare la quota reimpiegata). "
        "💧 *Cassa Residua BTD* = cassa iniziale destinata al Buy-the-Dip (1× cap. iniziale per le strategie mensili, 2× per le settimanali) "
        "al netto dei BTD Standard e BTD Boost già eseguiti."
    )

# ------------------------ App ------------------------
if st.session_state.get("logged_in"):
    st.sidebar.title(f"Benvenuto, *{name}*")
    authenticator.logout("Logout", "sidebar")
    st.sidebar.markdown("---")

    st.title("📈 Diario di Bordo Quantitativo")

    if worksheet is None or ws_tickers is None:
        st.error("🚨 Connessione ai worksheet non riuscita. Verifica le credenziali GCP in secrets.")
        st.stop()

    all_data_df = dm.get_all_data(worksheet)
    all_tickers_df = dm.get_all_tickers(ws_tickers)

    user_data_df = (
        all_data_df.loc[all_data_df["username"] == username]
        .copy()
        .sort_values(by="date", ascending=False, ignore_index=True)
    )
    user_tickers_df = all_tickers_df.loc[all_tickers_df["username"] == username].copy()

    tab_port, tab_journal, tab_metrics = st.tabs(["💼 Portafoglio", "📒 Journal", "📊 Metriche"])

    # ------------------ TAB Portafoglio ------------------
    with tab_port:
        st.header("Impostazioni Portafoglio — Tickers & Capitale Iniziale")

        with st.expander("➕ Aggiungi o aggiorna ticker", expanded=True):
            c1, c2 = st.columns([1, 1])
            with c1:
                new_ticker = st.text_input("Ticker", placeholder="es. SPY").upper().strip()
                new_descr = st.text_input("Descrizione (opzionale)")
            with c2:
                new_cap = st.number_input("Capitale iniziale", min_value=0.0, step=100.0, format="%.2f")
                new_active = st.checkbox("Attivo", value=True)
                new_freq = st.selectbox(
                    "Frequenza strategia",
                    options=FREQUENZE,
                    index=0,
                    help="Mensile: cassa BTD = 1× cap.iniziale · Settimanale: cassa BTD = 2× cap.iniziale",
                )

            if st.button("Salva ticker"):
                if not new_ticker:
                    st.error("Inserisci un ticker.")
                else:
                    now = pd.Timestamp.now()
                    mask = (all_tickers_df["username"] == username) & (all_tickers_df["ticker"] == new_ticker)
                    if mask.any():
                        all_tickers_df.loc[mask, ["capitaleIniziale", "descrizione", "attivo", "frequenza"]] = [
                            float(new_cap), new_descr, bool(new_active), str(new_freq)
                        ]
                    else:
                        new_row = pd.DataFrame([{
                            "username": username, "ticker": new_ticker,
                            "capitaleIniziale": float(new_cap), "descrizione": new_descr,
                            "attivo": bool(new_active), "frequenza": str(new_freq),
                            "created_at": now, "notes": ""
                        }])
                        all_tickers_df = pd.concat([all_tickers_df, new_row], ignore_index=True)

                    dm.save_all_tickers(ws_tickers, all_tickers_df)
                    st.success("Ticker salvato.")
                    st.rerun()

        st.subheader("Tickers configurati")
        if not user_tickers_df.empty:
            view_tk = user_tickers_df.copy()
            view_tk.insert(0, "delete", False)
            edited_tk = st.data_editor(
                view_tk, hide_index=True, use_container_width=True,
                column_config={
                    "delete": st.column_config.CheckboxColumn("Cancella", default=False),
                    "capitaleIniziale": st.column_config.NumberColumn("Capitale Iniziale", step=100.0, format="%.2f"),
                    "attivo": st.column_config.CheckboxColumn("Attivo", default=True),
                    "frequenza": st.column_config.SelectboxColumn(
                        "Frequenza", options=FREQUENZE, required=True,
                        help="Mensile = cassa BTD 1×cap · Settimanale = cassa BTD 2×cap",
                    ),
                    "created_at": None, "notes": None, "username": None,
                },
                disabled=[c for c in view_tk.columns if c not in ["delete", "capitaleIniziale", "descrizione", "attivo", "frequenza", "notes"]],
            )
            cdel, csave = st.columns([1, 1])
            with cdel:
                if st.button("🗑️ Cancella selezionati"):
                    to_del = edited_tk[edited_tk["delete"]].drop(columns=["delete"], errors="ignore")
                    if to_del.empty:
                        st.warning("Nessun ticker selezionato.")
                    else:
                        mask = pd.Series(False, index=all_tickers_df.index)
                        for _, r in to_del.iterrows():
                            mask |= ((all_tickers_df["username"] == r["username"]) & (all_tickers_df["ticker"] == r["ticker"]))
                        kept = all_tickers_df[~mask]
                        dm.save_all_tickers(ws_tickers, kept)
                        st.success(f"Cancellati {mask.sum()} ticker.")
                        st.rerun()
            with csave:
                if st.button("💾 Salva modifiche"):
                    upd = edited_tk.drop(columns=["delete"], errors="ignore")
                    base = all_tickers_df.copy()
                    base = base[~((base["username"] == username) & (base["ticker"].isin(upd["ticker"])))]
                    merged = pd.concat([base, upd], ignore_index=True)
                    dm.save_all_tickers(ws_tickers, merged)
                    st.success("Modifiche salvate.")
                    st.rerun()
        else:
            st.info("Nessun ticker configurato. Aggiungi i tuoi ticker per iniziare.")

        st.subheader("Panoramica Portafoglio (configurato)")
        agg = compute_aggregates(user_data_df)
        k_cfg = user_tickers_df.copy().rename(columns={"capitaleIniziale": "Capitale Iniziale"})
        kpi = k_cfg.merge(agg, how="left", on="ticker")
        for c in ["inc", "reinv", "std", "bst"]:
            kpi[c] = pd.to_numeric(kpi[c], errors="coerce").fillna(0.0)
        kpi["Investito Totale"] = kpi["reinv"] + kpi["std"] + kpi["bst"]
        kpi["Cash Residuo"] = kpi["Capitale Iniziale"] + kpi["inc"] - kpi["Investito Totale"]

        # Cassa BTD: 1× cap. iniziale (mensile) o 2× cap. iniziale (settimanale)
        # Cassa Residua BTD = Cassa Iniziale − (BTD Standard + BTD Boost), floor 0
        kpi["Cassa Multiplier"] = kpi["frequenza"].map(get_cassa_multiplier)
        kpi["Cassa Iniziale BTD"] = kpi["Capitale Iniziale"] * kpi["Cassa Multiplier"]
        kpi["Cassa Residua BTD"] = (kpi["Cassa Iniziale BTD"] - kpi["std"] - kpi["bst"]).clip(lower=0.0)

        kpi_display = (
            kpi.loc[kpi["attivo"], [
                "ticker","frequenza","Capitale Iniziale","Cassa Iniziale BTD",
                "inc","reinv","std","bst","Investito Totale","Cassa Residua BTD","Cash Residuo"
            ]]
               .rename(columns={
                   "ticker": "Asset",
                   "frequenza": "Frequenza",
                   "inc": "Premi Incassati",
                   "reinv": "Premi Reinvestiti",
                   "std": "BTD Standard",
                   "bst": "BTD Boost"
               })
        )
        if kpi_display.empty:
            st.info("Nessun dato da mostrare.")
        else:
            money_cols = [c for c in kpi_display.columns if c not in ("Asset", "Frequenza")]
            styled_kpi = (
                kpi_display.style
                .format({c: format_money_or_dash for c in money_cols})
                .set_properties(**{"text-align":"right"}, subset=money_cols)
                .set_properties(**{"font-weight":"bold"}, subset=["Asset"])
                .hide(axis="index")
            )
            st.dataframe(styled_kpi, use_container_width=True, height=len(kpi_display)*row_height_px+48)
            st.caption("💧 *Cassa Iniziale BTD* = cap.iniziale × moltiplicatore (1× mensile, 2× settimanale). *Cassa Residua BTD* si erode al netto di BTD Standard + Boost.")

    # ------------------ TAB Journal ------------------
    with tab_journal:
        # === SEZIONE GRAFICI A TORTA (in testa) ===
        st.header("📊 Composizione per Ticker")
        st.caption(
            "Distribuzione visiva di **Capitale Iniziale**, **BTD Standard**, **BTD Boost**, "
            "**Premi Incassati**, **Premi Reinvestiti** e **Cassa Residua BTD** per ogni ticker configurato e attivo. "
            "La cassa BTD si erode man mano che vengono effettuati i Buy-the-Dip."
        )
        render_ticker_pies(user_data_df, user_tickers_df)
        st.markdown("---")

        st.header("Dashboard Riepilogo")
        if user_data_df.empty:
            st.info("Nessuna operazione registrata. Aggiungi la prima operazione dal form qui sotto.")
        else:
            summary = (
                user_data_df.groupby("ticker")
                .agg(incassati=("premioIncassato","sum"),
                     reinvestiti=("premioReinvestito","sum"),
                     standard=("btdStandard","sum"),
                     boost=("btdBoost","sum")).reset_index()
            )
            summary["liquidi"] = summary["incassati"] - summary["reinvestiti"]
            summary["totale_investito"] = summary["reinvestiti"] + summary["standard"] + summary["boost"]
            summary_display = summary.rename(columns={
                "ticker": "Asset", "incassati": "Premi Incassati", "reinvestiti": "Premi Reinvestiti",
                "liquidi": "Premi Liquidi", "standard": "BTD Standard", "boost": "BTD Boost",
                "totale_investito": "Inv. Totale"
            })
            styled_summary = (
                summary_display.style
                .format({c: format_money_or_dash for c in summary_display.columns if c != "Asset"})
                .set_properties(**{"text-align":"right"}, subset=[c for c in summary_display.columns if c != "Asset"])
                    .set_properties(**{"font-weight":"bold"}, subset=["Asset"])
                .hide(axis="index")
            )
            st.dataframe(styled_summary, use_container_width=True, height=len(summary_display)*row_height_px+48)

        st.header("Aggiungi Nuova Operazione")

        # Tickers disponibili: attivi & capitale iniziale > 0
        valid_tickers = []
        if not user_tickers_df.empty:
            tmp = user_tickers_df.copy()
            tmp["capitaleIniziale"] = pd.to_numeric(tmp["capitaleIniziale"], errors="coerce").fillna(0.0)
            tmp["ticker"] = tmp["ticker"].astype(str).str.upper().str.strip()
            valid_tickers = sorted(tmp.loc[(tmp["attivo"] == True) & (tmp["capitaleIniziale"] > 0.0), "ticker"].dropna().unique().tolist())

        if not valid_tickers:
            st.warning("Nessun ticker disponibile: configura almeno un ticker **attivo** con **capitale iniziale > 0** nella tab **Portafoglio**.")

        op_type_selection = st.radio("Tipo Operazione", ["Incasso Premio", "Reinvestimento Premio", "Investimento BTD"],
                                     key="op_type_selector", horizontal=True)

        form_key = f"new_op_form_{ {'Incasso Premio':'inc','Reinvestimento Premio':'rei','Investimento BTD':'btd'}[op_type_selection] }"
        ticker_options = ["— Seleziona —"] + valid_tickers

        with st.form(form_key):
            c1, c2, c3 = st.columns(3)
            with c1:
                op_date = st.date_input("Data", value=datetime.now(), format="DD/MM/YYYY")
            with c2:
                op_ticker = st.selectbox("Ticker", options=ticker_options, index=0)
            with c3:
                op_notes = st.text_input("Note")

            if op_type_selection == "Incasso Premio":
                st.number_input("Premio Incassato", min_value=0.0, step=0.01, format="%.2f", key="premio_incassato_input")
            elif op_type_selection == "Reinvestimento Premio":
                st.number_input("Premio Reinvestito", min_value=0.0, step=0.01, format="%.2f", key="premio_reinvestito_input")
            else:
                b1, b2 = st.columns(2)
                with b1:
                    st.number_input("BTD Standard", min_value=0.0, step=0.01, format="%.2f", key="btd_standard_input")
                with b2:
                    st.number_input("BTD Boost", min_value=0.0, step=0.01, format="%.2f", key="btd_boost_input")

            submitted = st.form_submit_button("✓ Registra Operazione", disabled=(len(valid_tickers) == 0))
            if submitted:
                if op_ticker == "— Seleziona —":
                    st.error("Seleziona un ticker dal menu.")
                else:
                    sel = st.session_state.op_type_selector
                    new_row = {
                        "username": username,
                        "date": pd.to_datetime(op_date),
                        "ticker": str(op_ticker).upper().strip(),
                        "type": sel,
                        "premioIncassato": float(st.session_state.get("premio_incassato_input", 0.0)) if sel == "Incasso Premio" else 0.0,
                        "premioReinvestito": float(st.session_state.get("premio_reinvestito_input", 0.0)) if sel == "Reinvestimento Premio" else 0.0,
                        "btdStandard": float(st.session_state.get("btd_standard_input", 0.0)) if sel == "Investimento BTD" else 0.0,
                        "btdBoost": float(st.session_state.get("btd_boost_input", 0.0)) if sel == "Investimento BTD" else 0.0,
                        "notes": op_notes,
                    }
                    updated_df = pd.concat([all_data_df, pd.DataFrame([new_row])], ignore_index=True)
                    dm.save_all_data(worksheet, updated_df)
                    st.success("Operazione registrata con successo!")
                    st.rerun()

        st.header("Registro Operazioni")
        if not user_data_df.empty:
            view_df = user_data_df.copy()
            view_df.insert(0, "delete", False)
            edited_df = st.data_editor(
                view_df, hide_index=True, use_container_width=True,
                column_config={"delete": st.column_config.CheckboxColumn("Cancella", default=False),
                               "date": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                               "username": None},
                disabled=[c for c in view_df.columns if c != "delete"],
            )
            if st.button("🗑️ Conferma Cancellazione Selezionate", type="primary"):
                rows_to_delete = edited_df[edited_df["delete"]].drop(columns=["delete"], errors="ignore")
                if rows_to_delete.empty:
                    st.warning("Nessuna operazione selezionata.")
                else:
                    def _norm(df: pd.DataFrame) -> pd.DataFrame:
                        d = df.copy()
                        d["date"] = pd.to_datetime(d["date"], errors="coerce")
                        for c in ["premioIncassato","premioReinvestito","btdStandard","btdBoost"]:
                            d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)
                        for c in ["ticker","type","notes","username"]:
                            d[c] = d[c].astype(str).str.strip().str.upper() if c=="ticker" else d[c].astype(str).str.strip()
                        return d
                    base = _norm(all_data_df); dele = _norm(rows_to_delete)
                    def _key(df: pd.DataFrame) -> pd.Series:
                        return (df["username"]+"|"+df["date"].dt.strftime("%Y-%m-%d")+"|"+df["ticker"]+"|"+df["type"]+"|"+
                                df["premioIncassato"].astype(str)+"|"+df["premioReinvestito"].astype(str)+"|"+
                                df["btdStandard"].astype(str)+"|"+df["btdBoost"].astype(str)+"|"+df["notes"])
                    base["_rk"] = _key(base); dele["_rk"] = _key(dele)
                    final_df = all_data_df.drop(index=base.index[base["_rk"].isin(set(dele["_rk"]))])
                    dm.save_all_data(worksheet, final_df)
                    st.success(f"{len(base.index[base['_rk'].isin(set(dele['_rk']))])} operazione/i cancellata/e.")
                    st.rerun()

    # ------------------ TAB Metriche ------------------
    with tab_metrics:
        st.header("Metriche di Portafoglio e per Ticker")
        kpi_ticker, kpi_port = compute_kpi_tables(user_data_df, user_tickers_df)

        st.subheader("KPI di Portafoglio")
        if not kpi_port.empty:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Tickers Attivi", int(kpi_port.iloc[0]["Tickers Attivi"]))
            c2.metric("Operazioni Totali", int(kpi_port.iloc[0]["Operazioni Totali"]))
            c3.metric("Capitale Iniziale Totale", format_money_or_dash(kpi_port.iloc[0]["Capitale Iniziale Totale"]))
            c4.metric("Cash Residuo Totale", format_money_or_dash(kpi_port.iloc[0]["Cash Residuo Totale"]))

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Entrate Totali", format_money_or_dash(kpi_port.iloc[0]["Entrate Totali"]))
            c6.metric("Investito Totale", format_money_or_dash(kpi_port.iloc[0]["Investito Totale"]))
            c6.caption("Reinvestimenti + BTD Standard + BTD Boost")
            c7.metric("Cassa Iniziale BTD", format_money_or_dash(kpi_port.iloc[0]["Cassa Iniziale BTD Totale"]))
            c8.metric("Cassa Residua BTD", format_money_or_dash(kpi_port.iloc[0]["Cassa Residua BTD Totale"]))
            c8.caption("Liquidita ancora disponibile per Buy-the-Dip")

            c9, c10 = st.columns(2)
            c9.metric("Utilization Portafoglio", format_pct_or_dash(kpi_port.iloc[0]["Utilization Portafoglio"]))
            c10.metric("Tasso Reinvestimento", format_pct_or_dash(kpi_port.iloc[0]['Tasso Reinvestimento Portafoglio']))

        st.subheader("KPI per Ticker (attivi)")
        if kpi_ticker.empty:
            st.info("Nessun ticker attivo o nessuna operazione registrata.")
        else:
            kpi_show = kpi_ticker.copy()
            money_cols = [
                "Capitale Iniziale","Cassa Iniziale BTD","Entrate Totali",
                "Premi Reinvestiti","BTD Standard","BTD Boost",
                "Investito Totale","Cassa Residua BTD","Cash Residuo"
            ]
            pct_cols   = ["Cassa BTD Consumata %","Tasso Reinvestimento","Utilization"]
            if "Primo Movimento" in kpi_show.columns:
                kpi_show["Primo Movimento"] = pd.to_datetime(kpi_show["Primo Movimento"], errors="coerce").dt.strftime("%Y-%m-%d")
            if "Ultimo Movimento" in kpi_show.columns:
                kpi_show["Ultimo Movimento"] = pd.to_datetime(kpi_show["Ultimo Movimento"], errors="coerce").dt.strftime("%Y-%m-%d")
            styled = (
                kpi_show.style
                .format({c: format_money_or_dash for c in money_cols})
                .format({c: format_pct_or_dash for c in pct_cols})
                .set_properties(**{"text-align":"right"}, subset=[c for c in kpi_show.columns if c not in ["Asset","Frequenza","Primo Movimento","Ultimo Movimento"]])
                .set_properties(**{"font-weight":"bold"}, subset=["Asset"])
                .hide(axis="index")
            )
            st.dataframe(styled, use_container_width=True, height=min(640, len(kpi_show)*row_height_px+60))

        st.subheader("Trend Mensile (ultimi 12 mesi)")
        monthly = compute_monthly_trend(user_data_df)
        if monthly.empty:
            st.info("Nessun dato mensile disponibile.")
        else:
            st.dataframe(monthly.rename(columns={"month":"Mese"}), use_container_width=True,
                         height=min(600, len(monthly)*row_height_px+60))
            st.line_chart(data=monthly.set_index("month")[["Investito Totale"]], use_container_width=True)

elif authentication_status is False:
    st.error("Username/password non corretti")
else:
    st.warning("Per favore, inserisci username e password")
