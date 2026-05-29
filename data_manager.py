import streamlit as st
import gspread
import pandas as pd
from gspread_dataframe import get_as_dataframe, set_with_dataframe

# Colonne operazioni (Foglio1)
COLS = [
    "username", "date", "ticker", "type",
    "premioIncassato", "premioReinvestito", "btdStandard", "btdBoost",
    "notes"
]

# Colonne tickers (worksheet "Tickers")
# "frequenza" è "mensile" o "settimanale": determina il moltiplicatore della cassa BTD
# (mensile=1x cap.iniziale, settimanale=2x cap.iniziale).
TICKER_COLS = [
    "username", "ticker", "capitaleIniziale", "descrizione",
    "attivo", "frequenza", "created_at", "notes"
]

# Colonne utenti (worksheet "Users") — per gli account creati da app
USER_COLS = [
    "username", "name", "email", "password", "created_at"
]

# --------------------------------------------------------------------------------------
# Connessioni
# --------------------------------------------------------------------------------------
@st.cache_resource(ttl=600)
def _get_gspread_client():
    return gspread.service_account_from_dict(st.secrets["gcp_service_account"])

def get_google_sheet(spreadsheet_name: str, worksheet_title: str = "Foglio1"):
    """Ritorna il worksheet delle operazioni."""
    try:
        gc = _get_gspread_client()
        ss = gc.open(spreadsheet_name)
        return ss.worksheet(worksheet_title)
    except Exception as e:
        st.error(f"Errore apertura worksheet '{worksheet_title}': {e}")
        return None

def get_tickers_sheet(spreadsheet_name: str, worksheet_title: str = "Tickers"):
    """Ritorna (o crea se possibile) il worksheet dei tickers."""
    try:
        gc = _get_gspread_client()
        ss = gc.open(spreadsheet_name)
        try:
            return ss.worksheet(worksheet_title)
        except gspread.WorksheetNotFound:
            # Prova a crearlo (richiede permessi di scrittura)
            try:
                ws = ss.add_worksheet(title=worksheet_title, rows=1000, cols=20)
                # intestazioni
                set_with_dataframe(ws, pd.DataFrame(columns=TICKER_COLS), include_index=False, resize=True)
                return ws
            except Exception as ce:
                st.warning(f"Worksheet '{worksheet_title}' non trovato e non creato: {ce}")
                return None
    except Exception as e:
        st.error(f"Errore apertura spreadsheet '{spreadsheet_name}': {e}")
        return None

def get_users_sheet(spreadsheet_name: str, worksheet_title: str = "Users"):
    """Ritorna (o crea se possibile) il worksheet degli utenti registrati dall'app."""
    try:
        gc = _get_gspread_client()
        ss = gc.open(spreadsheet_name)
        try:
            return ss.worksheet(worksheet_title)
        except gspread.WorksheetNotFound:
            try:
                ws = ss.add_worksheet(title=worksheet_title, rows=1000, cols=10)
                set_with_dataframe(ws, pd.DataFrame(columns=USER_COLS), include_index=False, resize=True)
                return ws
            except Exception as ce:
                st.warning(f"Worksheet '{worksheet_title}' non trovato e non creato: {ce}")
                return None
    except Exception as e:
        st.error(f"Errore apertura spreadsheet '{spreadsheet_name}': {e}")
        return None

# --------------------------------------------------------------------------------------
# Lettura/Scrittura Operazioni
# Nota: i parametri worksheet/worksheet_tickers sono _nominali (iniziano con _)
# per evitare problemi di hashing in @st.cache_data.
# --------------------------------------------------------------------------------------
@st.cache_data(ttl=60)
def get_all_data(_ws):
    """Legge tutte le operazioni."""
    if _ws is None:
        return pd.DataFrame(columns=COLS)

    df = get_as_dataframe(_ws, evaluate_formulas=True)

    # Assicura colonne
    for c in COLS:
        if c not in df.columns:
            df[c] = pd.NA

    # Tipi
    num_cols = ["premioIncassato", "premioReinvestito", "btdStandard", "btdBoost"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["type"] = df["type"].astype(str).str.strip()
    df["username"] = df["username"].astype(str)
    df["notes"] = df["notes"].astype(str)

    return df[COLS]

def save_all_data(_ws, df: pd.DataFrame):
    """Scrive l’intero DataFrame operazioni sul worksheet."""
    if _ws is None:
        return
    df_copy = df.copy()
    # serializza date
    df_copy["date"] = pd.to_datetime(df_copy["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    set_with_dataframe(_ws, df_copy[COLS], include_index=False, resize=True)
    # pulisci cache per ricarichi coerenti
    st.cache_data.clear()

# --------------------------------------------------------------------------------------
# Lettura/Scrittura Tickers
# --------------------------------------------------------------------------------------
@st.cache_data(ttl=60)
def get_all_tickers(_ws_tickers):
    """Legge la tabella Tickers."""
    if _ws_tickers is None:
        return pd.DataFrame(columns=TICKER_COLS)

    df = get_as_dataframe(_ws_tickers, evaluate_formulas=True)

    for c in TICKER_COLS:
        if c not in df.columns:
            df[c] = pd.NA

    df["capitaleIniziale"] = pd.to_numeric(df["capitaleIniziale"], errors="coerce").fillna(0.0)
    df["attivo"] = df["attivo"].map(lambda x: bool(x) if pd.notna(x) else True)
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["username"] = df["username"].astype(str)
    df["descrizione"] = df["descrizione"].astype(str)
    df["notes"] = df["notes"].astype(str)

    # frequenza: default "mensile" se mancante o non riconosciuta
    def _norm_freq(v):
        s = str(v).strip().lower() if pd.notna(v) else ""
        if s.startswith("sett") or s == "weekly" or s == "w":
            return "settimanale"
        return "mensile"
    df["frequenza"] = df["frequenza"].map(_norm_freq)

    return df[TICKER_COLS]

def save_all_tickers(_ws_tickers, df: pd.DataFrame):
    """Scrive l'intero DataFrame tickers sul worksheet."""
    if _ws_tickers is None:
        return
    df_copy = df.copy()
    df_copy["created_at"] = pd.to_datetime(df_copy["created_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    set_with_dataframe(_ws_tickers, df_copy[TICKER_COLS], include_index=False, resize=True)
    st.cache_data.clear()

# --------------------------------------------------------------------------------------
# Lettura/Scrittura Users
# --------------------------------------------------------------------------------------
@st.cache_data(ttl=30)
def get_all_users(_ws_users):
    """Legge la tabella Users (account creati via app)."""
    if _ws_users is None:
        return pd.DataFrame(columns=USER_COLS)

    df = get_as_dataframe(_ws_users, evaluate_formulas=True)
    for c in USER_COLS:
        if c not in df.columns:
            df[c] = pd.NA

    df = df.dropna(subset=["username"], how="any")
    df["username"] = df["username"].astype(str).str.strip().str.lower()
    df["name"] = df["name"].astype(str).str.strip()
    df["email"] = df["email"].astype(str).str.strip().str.lower()
    df["password"] = df["password"].astype(str)
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

    return df[USER_COLS]

def save_all_users(_ws_users, df: pd.DataFrame):
    """Sovrascrive l'intera tabella Users."""
    if _ws_users is None:
        return
    df_copy = df.copy()
    df_copy["created_at"] = pd.to_datetime(df_copy["created_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    set_with_dataframe(_ws_users, df_copy[USER_COLS], include_index=False, resize=True)
    st.cache_data.clear()

def append_user(_ws_users, username: str, name: str, email: str, password_hash: str) -> bool:
    """Aggiunge un nuovo utente al foglio Users. Ritorna False se già esistente."""
    if _ws_users is None:
        return False
    existing = get_all_users(_ws_users)
    uname = str(username).strip().lower()
    if not existing.empty and uname in set(existing["username"].astype(str).str.lower()):
        return False
    new_row = pd.DataFrame([{
        "username": uname,
        "name": name.strip(),
        "email": email.strip().lower(),
        "password": password_hash,
        "created_at": pd.Timestamp.now(),
    }])
    merged = pd.concat([existing, new_row], ignore_index=True)
    save_all_users(_ws_users, merged)
    return True
