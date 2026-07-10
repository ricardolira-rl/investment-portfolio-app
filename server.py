from __future__ import annotations

import json
import mimetypes
import os
import re
import sqlite3
import threading
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "portfolio.db"
HOST = os.environ.get("PORTFOLIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORTFOLIO_PORT", "8080"))

CATEGORIES = {
    "stocks_internacionais": {
        "label": "Stocks internacionais",
        "path": "stocks",
        "currency": "USD",
    },
    "reits_internacionais": {
        "label": "REITs internacionais",
        "path": "reits",
        "currency": "USD",
    },
    "etfs_internacionais": {
        "label": "ETFs internacionais",
        "path": "etfs-global",
        "currency": "USD",
    },
    "acoes_brasileiras": {
        "label": "Ações brasileiras",
        "path": "acoes",
        "currency": "BRL",
    },
    "fiis_brasileiros": {
        "label": "Fundos imobiliários brasileiros",
        "path": "fiis",
        "currency": "BRL",
    },
}

SEED_ASSETS = [
    ("AAPL", "stocks_internacionais"),
    ("O", "reits_internacionais"),
    ("VOO", "etfs_internacionais"),
    ("PETR4", "acoes_brasileiras"),
    ("HGLG11", "fiis_brasileiros"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                category TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                segment TEXT,
                name TEXT,
                currency TEXT NOT NULL,
                price REAL,
                pvp REAL,
                liquidity REAL,
                source_url TEXT,
                last_updated TEXT,
                error TEXT,
                UNIQUE(ticker, category)
            );

            CREATE TABLE IF NOT EXISTS dividends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                ex_date TEXT,
                payment_date TEXT,
                amount REAL NOT NULL,
                UNIQUE(asset_id, kind, ex_date, payment_date, amount)
            );

            CREATE TABLE IF NOT EXISTS fii_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                sector TEXT NOT NULL,
                allocation_pct REAL NOT NULL DEFAULT 0,
                max_price REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fii_sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                sector TEXT NOT NULL,
                allocation_pct REAL NOT NULL DEFAULT 0,
                max_price REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS international_stock_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                sector TEXT NOT NULL,
                allocation_pct REAL NOT NULL DEFAULT 0,
                max_price REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS international_stock_sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reit_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                sector TEXT NOT NULL,
                allocation_pct REAL NOT NULL DEFAULT 0,
                max_price REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reit_sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS etf_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                sector TEXT NOT NULL,
                allocation_pct REAL NOT NULL DEFAULT 0,
                max_price REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS etf_sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS contribution_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                national_balance REAL NOT NULL DEFAULT 0,
                national_contribution REAL NOT NULL DEFAULT 0,
                national_fii_budget REAL NOT NULL DEFAULT 0,
                national_stocks_budget REAL NOT NULL DEFAULT 0,
                international_balance REAL NOT NULL DEFAULT 0,
                international_contribution REAL NOT NULL DEFAULT 0,
                international_stocks_budget REAL NOT NULL DEFAULT 0,
                international_reits_budget REAL NOT NULL DEFAULT 0,
                international_etfs_budget REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )
        db.execute(
            """
            INSERT OR IGNORE INTO contribution_settings
                (id, national_balance, national_contribution, international_balance, international_contribution, updated_at)
            VALUES (1, 0, 0, 0, 0, ?)
            """,
            (utc_now(),),
        )
        columns = {row[1] for row in db.execute("PRAGMA table_info(assets)")}
        if "quantity" not in columns:
            db.execute("ALTER TABLE assets ADD COLUMN quantity REAL NOT NULL DEFAULT 0")
        if "segment" not in columns:
            db.execute("ALTER TABLE assets ADD COLUMN segment TEXT")
        if "pvp" not in columns:
            db.execute("ALTER TABLE assets ADD COLUMN pvp REAL")
        if "liquidity" not in columns:
            db.execute("ALTER TABLE assets ADD COLUMN liquidity REAL")
        contribution_columns = {row[1] for row in db.execute("PRAGMA table_info(contribution_settings)")}
        if "national_fii_budget" not in contribution_columns:
            db.execute("ALTER TABLE contribution_settings ADD COLUMN national_fii_budget REAL NOT NULL DEFAULT 0")
        if "national_stocks_budget" not in contribution_columns:
            db.execute("ALTER TABLE contribution_settings ADD COLUMN national_stocks_budget REAL NOT NULL DEFAULT 0")
        if "international_stocks_budget" not in contribution_columns:
            db.execute("ALTER TABLE contribution_settings ADD COLUMN international_stocks_budget REAL NOT NULL DEFAULT 0")
        if "international_reits_budget" not in contribution_columns:
            db.execute("ALTER TABLE contribution_settings ADD COLUMN international_reits_budget REAL NOT NULL DEFAULT 0")
        if "international_etfs_budget" not in contribution_columns:
            db.execute("ALTER TABLE contribution_settings ADD COLUMN international_etfs_budget REAL NOT NULL DEFAULT 0")
        db.execute(
            """
            INSERT OR IGNORE INTO fii_sectors (name, updated_at)
            SELECT DISTINCT sector, ? FROM fii_management
            WHERE TRIM(sector) <> ''
            """,
            (utc_now(),),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO stock_sectors (name, updated_at)
            SELECT DISTINCT sector, ? FROM stock_management
            WHERE TRIM(sector) <> ''
            """,
            (utc_now(),),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO international_stock_sectors (name, updated_at)
            SELECT DISTINCT sector, ? FROM international_stock_management
            WHERE TRIM(sector) <> ''
            """,
            (utc_now(),),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO reit_sectors (name, updated_at)
            SELECT DISTINCT sector, ? FROM reit_management
            WHERE TRIM(sector) <> ''
            """,
            (utc_now(),),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO etf_sectors (name, updated_at)
            SELECT DISTINCT sector, ? FROM etf_management
            WHERE TRIM(sector) <> ''
            """,
            (utc_now(),),
        )
        count = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        if count == 0:
            for ticker, category in SEED_ASSETS:
                config = CATEGORIES[category]
                db.execute(
                    "INSERT INTO assets (ticker, category, currency) VALUES (?, ?, ?)",
                    (ticker, category, config["currency"]),
                )


class InvestidorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.texts: list[str] = []
        self.headings: list[tuple[str, str]] = []
        self.tables: list[list[list[str]]] = []
        self._ignored = 0
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored += 1
        if self._ignored:
            return
        if tag in {"h1", "h2", "h3"}:
            self._heading_tag = tag
            self._heading_parts = []
        elif tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored = max(0, self._ignored - 1)
            return
        if self._ignored:
            return
        if tag == self._heading_tag:
            value = clean_text(" ".join(self._heading_parts))
            if value:
                self.headings.append((tag, value))
            self._heading_tag = None
        elif tag in {"td", "th"} and self._cell_parts is not None:
            self._row.append(clean_text(" ".join(self._cell_parts)))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        value = clean_text(data)
        if not value:
            return
        self.texts.append(value)
        if self._heading_tag:
            self._heading_parts.append(value)
        if self._cell_parts is not None:
            self._cell_parts.append(value)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_number(value: str) -> float:
    value = value.replace("R$", "").replace("US$", "").replace("$", "").strip()
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", re.sub(r"[^0-9.\-]", "", value)):
        value = value.replace(".", "")
    return float(re.sub(r"[^0-9.\-]", "", value))


def parse_compact_number(value: str) -> float:
    text = value.casefold().replace("r$", "").replace("us$", "").replace("$", "").strip()
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    if re.search(r"\b(bilhao|bilhoes|bi|b)\b", normalized):
        return parse_number(text) * 1_000_000_000.0
    if re.search(r"\b(milhao|milhoes|mi|m)\b", normalized):
        return parse_number(text) * 1_000_000.0
    if re.search(r"\b(mil|k)\b", normalized):
        return parse_number(text) * 1_000.0
    multiplier = 1.0
    if re.search(r"\b(bilh[oõ]es|bi|b)\b", text):
        multiplier = 1_000_000_000.0
    elif re.search(r"\b(milh[oõ]es|mi|m)\b", text):
        multiplier = 1_000_000.0
    elif re.search(r"\b(mil|k)\b", text):
        multiplier = 1_000.0
    return parse_number(text) * multiplier


def parse_date(value: str) -> str | None:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def extract_asset(html: str, fallback_ticker: str) -> dict:
    parser = InvestidorParser()
    parser.feed(html)

    price = None
    for index, text in enumerate(parser.texts[:-1]):
        if text.casefold() == "cotação":
            for candidate in parser.texts[index + 1:index + 8]:
                if re.fullmatch(r"(?:R\$|US\$|\$)?\s*[0-9.]+,[0-9]+", candidate):
                    price = parse_number(candidate)
                    break
        if price is not None:
            break
    if price is None:
        faq_match = re.search(r"hoje está em\s*(?:R\$|US\$|\$)?\s*([0-9.]+,[0-9]+)", html, re.I)
        if faq_match:
            price = parse_number(faq_match.group(1))
    if price is None:
        raise ValueError("Cotação não encontrada na página")

    name = fallback_ticker
    ticker_heading = next(
        (index for index, item in enumerate(parser.headings) if item[0] == "h1" and item[1].upper() == fallback_ticker.upper()),
        None,
    )
    if ticker_heading is not None:
        for tag, heading in parser.headings[ticker_heading + 1:ticker_heading + 5]:
            if tag == "h2" and fallback_ticker.upper() not in heading.upper():
                name = heading
                break

    pvp = None
    for index, text in enumerate(parser.texts[:-1]):
        normalized = text.casefold().replace(" ", "")
        if normalized in {"p/vp", "pvp"}:
            for candidate in parser.texts[index + 1:index + 6]:
                try:
                    pvp = parse_number(candidate)
                    break
                except ValueError:
                    continue
        if pvp is not None:
            break

    liquidity = None
    liquidity_labels = ("liquidez diária", "liquidez media diaria", "liquidez média diária")
    liquidity_labels = liquidity_labels + (
        "volume médio de negociações diária",
        "volume medio de negociacoes diaria",
    )
    for preferred in (True, False):
        for index, text in enumerate(parser.texts[:-1]):
            normalized = text.casefold()
            if "liquidez corrente" in normalized or "maiores liquidez" in normalized:
                continue
            if preferred and not any(label in normalized for label in liquidity_labels):
                continue
            if not preferred and "liquidez" not in normalized:
                continue
            for candidate in parser.texts[index + 1:index + 8]:
                if re.search(r"(?:R\$|US\$|\$)\s*[0-9.]+,[0-9]+", candidate):
                    try:
                        liquidity = parse_compact_number(candidate)
                        break
                    except ValueError:
                        continue
            if liquidity is not None:
                break
        if liquidity is not None:
            break

    dividends = []
    for table in parser.tables:
        if not table:
            continue
        header = " ".join(table[0]).casefold()
        if "pagamento" not in header or "valor" not in header or "tipo" not in header:
            continue
        for row in table[1:]:
            if len(row) < 4:
                continue
            try:
                dividends.append(
                    {
                        "kind": row[0],
                        "ex_date": parse_date(row[1]),
                        "payment_date": parse_date(row[2]),
                        "amount": parse_number(row[3]),
                    }
                )
            except ValueError:
                continue
        if dividends:
            break

    return {"name": name, "price": price, "pvp": pvp, "liquidity": liquidity, "dividends": dividends}


def source_url(ticker: str, category: str) -> str:
    path = CATEGORIES[category]["path"]
    return f"https://investidor10.com.br/{path}/{ticker.lower()}/"


def scrape(ticker: str, category: str) -> dict:
    url = source_url(ticker, category)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Investidor10 respondeu HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError("Não foi possível acessar o Investidor10") from exc
    result = extract_asset(html, ticker)
    result["source_url"] = url
    return result


def serialize_asset(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    dividends = [
        dict(item)
        for item in db.execute(
            """
            SELECT kind, ex_date, payment_date, amount
            FROM dividends WHERE asset_id = ?
            ORDER BY COALESCE(payment_date, ex_date) DESC, id DESC
            """,
            (row["id"],),
        )
    ]
    paid_12m = db.execute(
        """
        SELECT COALESCE(SUM(amount), 0) FROM dividends
        WHERE asset_id = ? AND payment_date >= date('now', '-12 months')
        """,
        (row["id"],),
    ).fetchone()[0]
    data = dict(row)
    data["category_label"] = CATEGORIES[row["category"]]["label"]
    data["source_url"] = row["source_url"] or source_url(row["ticker"], row["category"])
    data["dividends"] = dividends
    data["dividends_12m"] = paid_12m
    data["market_value"] = (row["quantity"] or 0) * row["price"] if row["price"] is not None else None
    return data


def list_assets() -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM assets ORDER BY category, ticker").fetchall()
        return [serialize_asset(db, row) for row in rows]


def refresh_asset(asset_id: int) -> dict:
    with connect() as db:
        asset = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if not asset:
            raise KeyError("Ativo não encontrado")
        try:
            result = scrape(asset["ticker"], asset["category"])
            db.execute(
                """
                UPDATE assets SET name = ?, price = ?, pvp = ?, liquidity = ?, source_url = ?,
                    last_updated = ?, error = NULL WHERE id = ?
                """,
                (result["name"], result["price"], result.get("pvp"), result.get("liquidity"), result["source_url"], utc_now(), asset_id),
            )
            db.execute("DELETE FROM dividends WHERE asset_id = ?", (asset_id,))
            db.executemany(
                """
                INSERT OR IGNORE INTO dividends
                    (asset_id, kind, ex_date, payment_date, amount)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (asset_id, item["kind"], item["ex_date"], item["payment_date"], item["amount"])
                    for item in result["dividends"]
                ],
            )
        except Exception as exc:
            db.execute(
                "UPDATE assets SET error = ?, last_updated = ? WHERE id = ?",
                (str(exc), utc_now(), asset_id),
            )
        row = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return serialize_asset(db, row)


class Handler(BaseHTTPRequestHandler):
    server_version = "CarteiraLocal/1.0"

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/assets":
            self.send_json({"assets": list_assets(), "categories": CATEGORIES})
            return
        if path == "/api/fii-management":
            with connect() as db:
                rows = db.execute(
                    "SELECT * FROM fii_management ORDER BY ticker"
                ).fetchall()
                sectors = db.execute(
                    "SELECT * FROM fii_sectors ORDER BY name COLLATE NOCASE"
                ).fetchall()
                assets = db.execute(
                    """
                    SELECT ticker, quantity, price, segment,
                        quantity * COALESCE(price, 0) AS market_value
                    FROM assets
                    WHERE category = 'fiis_brasileiros'
                    ORDER BY ticker
                    """
                ).fetchall()
            self.send_json({
                "funds": [dict(row) for row in rows],
                "portfolio": [dict(row) for row in assets],
                "sectors": [dict(row) for row in sectors],
            })
            return
        if path == "/api/stocks-management":
            with connect() as db:
                rows = db.execute(
                    "SELECT * FROM stock_management ORDER BY ticker"
                ).fetchall()
                sectors = db.execute(
                    "SELECT * FROM stock_sectors ORDER BY name COLLATE NOCASE"
                ).fetchall()
                assets = db.execute(
                    """
                    SELECT ticker, quantity, price, segment,
                        quantity * COALESCE(price, 0) AS market_value
                    FROM assets
                    WHERE category = 'acoes_brasileiras'
                    ORDER BY ticker
                    """
                ).fetchall()
            self.send_json({
                "stocks": [dict(row) for row in rows],
                "portfolio": [dict(row) for row in assets],
                "sectors": [dict(row) for row in sectors],
            })
            return
        if path == "/api/international-stocks-management":
            with connect() as db:
                rows = db.execute(
                    "SELECT * FROM international_stock_management ORDER BY ticker"
                ).fetchall()
                sectors = db.execute(
                    "SELECT * FROM international_stock_sectors ORDER BY name COLLATE NOCASE"
                ).fetchall()
                assets = db.execute(
                    """
                    SELECT ticker, quantity, price, segment,
                        quantity * COALESCE(price, 0) AS market_value
                    FROM assets
                    WHERE category = 'stocks_internacionais'
                    ORDER BY ticker
                    """
                ).fetchall()
            self.send_json({
                "stocks": [dict(row) for row in rows],
                "portfolio": [dict(row) for row in assets],
                "sectors": [dict(row) for row in sectors],
            })
            return
        if path == "/api/reits-management":
            with connect() as db:
                rows = db.execute("SELECT * FROM reit_management ORDER BY ticker").fetchall()
                sectors = db.execute("SELECT * FROM reit_sectors ORDER BY name COLLATE NOCASE").fetchall()
                assets = db.execute(
                    """
                    SELECT ticker, quantity, price, segment,
                        quantity * COALESCE(price, 0) AS market_value
                    FROM assets
                    WHERE category = 'reits_internacionais'
                    ORDER BY ticker
                    """
                ).fetchall()
            self.send_json({
                "items": [dict(row) for row in rows],
                "portfolio": [dict(row) for row in assets],
                "sectors": [dict(row) for row in sectors],
            })
            return
        if path == "/api/etfs-management":
            with connect() as db:
                rows = db.execute("SELECT * FROM etf_management ORDER BY ticker").fetchall()
                sectors = db.execute("SELECT * FROM etf_sectors ORDER BY name COLLATE NOCASE").fetchall()
                assets = db.execute(
                    """
                    SELECT ticker, quantity, price, segment,
                        quantity * COALESCE(price, 0) AS market_value
                    FROM assets
                    WHERE category = 'etfs_internacionais'
                    ORDER BY ticker
                    """
                ).fetchall()
            self.send_json({
                "items": [dict(row) for row in rows],
                "portfolio": [dict(row) for row in assets],
                "sectors": [dict(row) for row in sectors],
            })
            return
        if path == "/api/contribution-plan":
            with connect() as db:
                settings = db.execute("SELECT * FROM contribution_settings WHERE id = 1").fetchone()
                funds = db.execute("SELECT * FROM fii_management ORDER BY ticker").fetchall()
                stocks = db.execute("SELECT * FROM stock_management ORDER BY ticker").fetchall()
                international_stocks = db.execute("SELECT * FROM international_stock_management ORDER BY ticker").fetchall()
                reits = db.execute("SELECT * FROM reit_management ORDER BY ticker").fetchall()
                etfs = db.execute("SELECT * FROM etf_management ORDER BY ticker").fetchall()
            self.send_json({
                "settings": dict(settings),
                "assets": list_assets(),
                "categories": CATEGORIES,
                "fii_targets": [dict(row) for row in funds],
                "stock_targets": [dict(row) for row in stocks],
                "international_stock_targets": [dict(row) for row in international_stocks],
                "reit_targets": [dict(row) for row in reits],
                "etf_targets": [dict(row) for row in etfs],
            })
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        management_config = {
            "/api/reit-sectors": ("reit_sectors",),
            "/api/etf-sectors": ("etf_sectors",),
        }
        if path in management_config:
            table = management_config[path][0]
            name = clean_text(str(self.read_json().get("name", "")))[:80]
            if not name:
                self.send_json({"error": "Informe o nome do setor"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        f"INSERT INTO {table} (name, updated_at) VALUES (?, ?)",
                        (name, utc_now()),
                    )
                    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (cursor.lastrowid,)).fetchone()
                self.send_json(dict(row), 201)
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este setor jÃ¡ estÃ¡ cadastrado"}, 409)
            return
        asset_management_config = {
            "/api/reits-management": ("reit_management", "reits_internacionais", "Este REIT internacional jÃ¡ estÃ¡ cadastrado"),
            "/api/etfs-management": ("etf_management", "etfs_internacionais", "Este ETF internacional jÃ¡ estÃ¡ cadastrado"),
        }
        if path in asset_management_config:
            table, category, duplicate_message = asset_management_config[path]
            payload = self.read_json()
            ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
            sector = clean_text(str(payload.get("sector", "")))[:80]
            try:
                allocation_pct = float(payload.get("allocation_pct", 0) or 0)
                max_price = float(payload.get("max_price", 0) or 0)
            except (TypeError, ValueError):
                self.send_json({"error": "AlocaÃ§Ã£o ou preÃ§o mÃ¡ximo invÃ¡lido"}, 400)
                return
            if not ticker or not sector or allocation_pct < 0 or max_price < 0:
                self.send_json({"error": "Preencha todos os campos com valores vÃ¡lidos"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        f"""
                        INSERT INTO {table}
                            (ticker, sector, allocation_pct, max_price, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (ticker, sector, allocation_pct, max_price, utc_now()),
                    )
                    db.execute(
                        "UPDATE assets SET segment = ? WHERE ticker = ? AND category = ?",
                        (sector, ticker, category),
                    )
                    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (cursor.lastrowid,)).fetchone()
                self.send_json(dict(row), 201)
            except sqlite3.IntegrityError:
                self.send_json({"error": duplicate_message}, 409)
            return
        if path == "/api/international-stock-sectors":
            name = clean_text(str(self.read_json().get("name", "")))[:80]
            if not name:
                self.send_json({"error": "Informe o nome do setor"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        "INSERT INTO international_stock_sectors (name, updated_at) VALUES (?, ?)",
                        (name, utc_now()),
                    )
                    row = db.execute("SELECT * FROM international_stock_sectors WHERE id = ?", (cursor.lastrowid,)).fetchone()
                self.send_json(dict(row), 201)
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este setor jÃ¡ estÃ¡ cadastrado"}, 409)
            return
        if path == "/api/fii-sectors":
            name = clean_text(str(self.read_json().get("name", "")))[:80]
            if not name:
                self.send_json({"error": "Informe o nome do setor"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        "INSERT INTO fii_sectors (name, updated_at) VALUES (?, ?)",
                        (name, utc_now()),
                    )
                    row = db.execute("SELECT * FROM fii_sectors WHERE id = ?", (cursor.lastrowid,)).fetchone()
                self.send_json(dict(row), 201)
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este setor já está cadastrado"}, 409)
            return
        if path == "/api/stock-sectors":
            name = clean_text(str(self.read_json().get("name", "")))[:80]
            if not name:
                self.send_json({"error": "Informe o nome do setor"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        "INSERT INTO stock_sectors (name, updated_at) VALUES (?, ?)",
                        (name, utc_now()),
                    )
                    row = db.execute("SELECT * FROM stock_sectors WHERE id = ?", (cursor.lastrowid,)).fetchone()
                self.send_json(dict(row), 201)
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este setor já está cadastrado"}, 409)
            return
        if path == "/api/fii-management":
            payload = self.read_json()
            ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
            sector = clean_text(str(payload.get("sector", "")))[:80]
            try:
                allocation_pct = float(payload.get("allocation_pct", 0) or 0)
                max_price = float(payload.get("max_price", 0) or 0)
            except (TypeError, ValueError):
                self.send_json({"error": "Alocação ou preço máximo inválido"}, 400)
                return
            if not ticker or not sector or allocation_pct < 0 or max_price < 0:
                self.send_json({"error": "Preencha todos os campos com valores válidos"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        """
                        INSERT INTO fii_management
                            (ticker, sector, allocation_pct, max_price, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (ticker, sector, allocation_pct, max_price, utc_now()),
                    )
                    db.execute(
                        "UPDATE assets SET segment = ? WHERE ticker = ? AND category = 'fiis_brasileiros'",
                        (sector, ticker),
                    )
                    row = db.execute("SELECT * FROM fii_management WHERE id = ?", (cursor.lastrowid,)).fetchone()
                self.send_json(dict(row), 201)
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este fundo imobiliário já está cadastrado"}, 409)
            return
        if path == "/api/stocks-management":
            payload = self.read_json()
            ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
            sector = clean_text(str(payload.get("sector", "")))[:80]
            try:
                allocation_pct = float(payload.get("allocation_pct", 0) or 0)
                max_price = float(payload.get("max_price", 0) or 0)
            except (TypeError, ValueError):
                self.send_json({"error": "Alocação ou preço máximo inválido"}, 400)
                return
            if not ticker or not sector or allocation_pct < 0 or max_price < 0:
                self.send_json({"error": "Preencha todos os campos com valores válidos"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        """
                        INSERT INTO stock_management
                            (ticker, sector, allocation_pct, max_price, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (ticker, sector, allocation_pct, max_price, utc_now()),
                    )
                    db.execute(
                        "UPDATE assets SET segment = ? WHERE ticker = ? AND category = 'acoes_brasileiras'",
                        (sector, ticker),
                    )
                    row = db.execute("SELECT * FROM stock_management WHERE id = ?", (cursor.lastrowid,)).fetchone()
                self.send_json(dict(row), 201)
            except sqlite3.IntegrityError:
                self.send_json({"error": "Esta ação brasileira já está cadastrada"}, 409)
            return
        if path == "/api/international-stocks-management":
            payload = self.read_json()
            ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
            sector = clean_text(str(payload.get("sector", "")))[:80]
            try:
                allocation_pct = float(payload.get("allocation_pct", 0) or 0)
                max_price = float(payload.get("max_price", 0) or 0)
            except (TypeError, ValueError):
                self.send_json({"error": "AlocaÃ§Ã£o ou preÃ§o mÃ¡ximo invÃ¡lido"}, 400)
                return
            if not ticker or not sector or allocation_pct < 0 or max_price < 0:
                self.send_json({"error": "Preencha todos os campos com valores vÃ¡lidos"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        """
                        INSERT INTO international_stock_management
                            (ticker, sector, allocation_pct, max_price, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (ticker, sector, allocation_pct, max_price, utc_now()),
                    )
                    db.execute(
                        "UPDATE assets SET segment = ? WHERE ticker = ? AND category = 'stocks_internacionais'",
                        (sector, ticker),
                    )
                    row = db.execute("SELECT * FROM international_stock_management WHERE id = ?", (cursor.lastrowid,)).fetchone()
                self.send_json(dict(row), 201)
            except sqlite3.IntegrityError:
                self.send_json({"error": "Esta stock internacional jÃ¡ estÃ¡ cadastrada"}, 409)
            return
        if path == "/api/assets":
            payload = self.read_json()
            ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
            category = str(payload.get("category", ""))
            try:
                quantity = max(0, float(payload.get("quantity", 0) or 0))
            except (TypeError, ValueError):
                self.send_json({"error": "Quantidade inválida"}, 400)
                return
            segment = clean_text(str(payload.get("segment", "")))[:80] or None
            if not ticker or category not in CATEGORIES:
                self.send_json({"error": "Ticker ou categoria inválidos"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        "INSERT INTO assets (ticker, category, quantity, segment, currency) VALUES (?, ?, ?, ?, ?)",
                        (ticker, category, quantity, segment, CATEGORIES[category]["currency"]),
                    )
                    asset_id = cursor.lastrowid
                self.send_json(refresh_asset(asset_id), 201)
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este ativo já está cadastrado nesta categoria"}, 409)
            return
        match = re.fullmatch(r"/api/assets/(\d+)/refresh", path)
        if match:
            try:
                self.send_json(refresh_asset(int(match.group(1))))
            except KeyError as exc:
                self.send_json({"error": str(exc)}, 404)
            return
        if path == "/api/refresh-all":
            ids = [asset["id"] for asset in list_assets()]
            results = [refresh_asset(asset_id) for asset_id in ids]
            self.send_json({"assets": results})
            return
        self.send_json({"error": "Rota não encontrada"}, 404)

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        sector_management_match = re.fullmatch(r"/api/(reit|etf)-sectors/(\d+)", path)
        if sector_management_match:
            kind = sector_management_match.group(1)
            sector_table = f"{kind}_sectors"
            management_table = f"{kind}_management"
            category = "reits_internacionais" if kind == "reit" else "etfs_internacionais"
            name = clean_text(str(self.read_json().get("name", "")))[:80]
            if not name:
                self.send_json({"error": "Informe o nome do setor"}, 400)
                return
            sector_id = int(sector_management_match.group(2))
            try:
                with connect() as db:
                    current = db.execute(f"SELECT * FROM {sector_table} WHERE id = ?", (sector_id,)).fetchone()
                    if not current:
                        self.send_json({"error": "Setor nÃ£o encontrado"}, 404)
                        return
                    db.execute(f"UPDATE {sector_table} SET name = ?, updated_at = ? WHERE id = ?", (name, utc_now(), sector_id))
                    db.execute(f"UPDATE {management_table} SET sector = ?, updated_at = ? WHERE sector = ? COLLATE NOCASE", (name, utc_now(), current["name"]))
                    db.execute("UPDATE assets SET segment = ? WHERE category = ? AND segment = ? COLLATE NOCASE", (name, category, current["name"]))
                    row = db.execute(f"SELECT * FROM {sector_table} WHERE id = ?", (sector_id,)).fetchone()
                self.send_json(dict(row))
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este setor jÃ¡ estÃ¡ cadastrado"}, 409)
            return
        asset_management_match = re.fullmatch(r"/api/(reits|etfs)-management/(\d+)", path)
        if asset_management_match:
            kind = asset_management_match.group(1)
            table = "reit_management" if kind == "reits" else "etf_management"
            category = "reits_internacionais" if kind == "reits" else "etfs_internacionais"
            not_found = "REIT internacional nÃ£o encontrado" if kind == "reits" else "ETF internacional nÃ£o encontrado"
            payload = self.read_json()
            ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
            sector = clean_text(str(payload.get("sector", "")))[:80]
            try:
                allocation_pct = float(payload.get("allocation_pct", 0) or 0)
                max_price = float(payload.get("max_price", 0) or 0)
            except (TypeError, ValueError):
                self.send_json({"error": "AlocaÃ§Ã£o ou preÃ§o mÃ¡ximo invÃ¡lido"}, 400)
                return
            if not ticker or not sector or allocation_pct < 0 or max_price < 0:
                self.send_json({"error": "Preencha todos os campos com valores vÃ¡lidos"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        f"""
                        UPDATE {table} SET ticker = ?, sector = ?, allocation_pct = ?,
                            max_price = ?, updated_at = ? WHERE id = ?
                        """,
                        (ticker, sector, allocation_pct, max_price, utc_now(), int(asset_management_match.group(2))),
                    )
                    if not cursor.rowcount:
                        self.send_json({"error": not_found}, 404)
                        return
                    db.execute(
                        "UPDATE assets SET segment = ? WHERE ticker = ? AND category = ?",
                        (sector, ticker, category),
                    )
                    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (int(asset_management_match.group(2)),)).fetchone()
                self.send_json(dict(row))
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este ticker jÃ¡ estÃ¡ cadastrado"}, 409)
            return
        if path == "/api/contribution-plan":
            payload = self.read_json()
            try:
                values = [max(0, float(payload.get(field, 0) or 0)) for field in (
                    "national_balance", "national_contribution", "national_fii_budget", "national_stocks_budget",
                    "international_balance", "international_contribution", "international_stocks_budget",
                    "international_reits_budget", "international_etfs_budget"
                )]
            except (TypeError, ValueError):
                self.send_json({"error": "Informe valores válidos para os saldos e aportes"}, 400)
                return
            if values[2] + values[3] > values[0] + values[1] + 0.001:
                self.send_json({"error": "A soma destinada a FIIs e ações ultrapassa o total nacional disponível"}, 400)
                return
            if values[6] + values[7] + values[8] > values[4] + values[5] + 0.001:
                self.send_json({"error": "A soma destinada a Stocks, REITs e ETFs ultrapassa o total internacional disponível"}, 400)
                return
            with connect() as db:
                db.execute(
                    """
                    UPDATE contribution_settings SET national_balance = ?, national_contribution = ?,
                        national_fii_budget = ?, national_stocks_budget = ?,
                        international_balance = ?, international_contribution = ?,
                        international_stocks_budget = ?, international_reits_budget = ?, international_etfs_budget = ?,
                        updated_at = ?
                    WHERE id = 1
                    """,
                    (*values, utc_now()),
                )
                row = db.execute("SELECT * FROM contribution_settings WHERE id = 1").fetchone()
            self.send_json(dict(row))
            return
        sector_match = re.fullmatch(r"/api/fii-sectors/(\d+)", path)
        if sector_match:
            name = clean_text(str(self.read_json().get("name", "")))[:80]
            if not name:
                self.send_json({"error": "Informe o nome do setor"}, 400)
                return
            sector_id = int(sector_match.group(1))
            try:
                with connect() as db:
                    current = db.execute("SELECT * FROM fii_sectors WHERE id = ?", (sector_id,)).fetchone()
                    if not current:
                        self.send_json({"error": "Setor não encontrado"}, 404)
                        return
                    db.execute("UPDATE fii_sectors SET name = ?, updated_at = ? WHERE id = ?", (name, utc_now(), sector_id))
                    db.execute("UPDATE fii_management SET sector = ?, updated_at = ? WHERE sector = ? COLLATE NOCASE", (name, utc_now(), current["name"]))
                    db.execute("UPDATE assets SET segment = ? WHERE category = 'fiis_brasileiros' AND segment = ? COLLATE NOCASE", (name, current["name"]))
                    row = db.execute("SELECT * FROM fii_sectors WHERE id = ?", (sector_id,)).fetchone()
                self.send_json(dict(row))
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este setor já está cadastrado"}, 409)
            return
        stock_sector_match = re.fullmatch(r"/api/stock-sectors/(\d+)", path)
        if stock_sector_match:
            name = clean_text(str(self.read_json().get("name", "")))[:80]
            if not name:
                self.send_json({"error": "Informe o nome do setor"}, 400)
                return
            sector_id = int(stock_sector_match.group(1))
            try:
                with connect() as db:
                    current = db.execute("SELECT * FROM stock_sectors WHERE id = ?", (sector_id,)).fetchone()
                    if not current:
                        self.send_json({"error": "Setor não encontrado"}, 404)
                        return
                    db.execute("UPDATE stock_sectors SET name = ?, updated_at = ? WHERE id = ?", (name, utc_now(), sector_id))
                    db.execute("UPDATE stock_management SET sector = ?, updated_at = ? WHERE sector = ? COLLATE NOCASE", (name, utc_now(), current["name"]))
                    db.execute("UPDATE assets SET segment = ? WHERE category = 'acoes_brasileiras' AND segment = ? COLLATE NOCASE", (name, current["name"]))
                    row = db.execute("SELECT * FROM stock_sectors WHERE id = ?", (sector_id,)).fetchone()
                self.send_json(dict(row))
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este setor já está cadastrado"}, 409)
            return
        international_stock_sector_match = re.fullmatch(r"/api/international-stock-sectors/(\d+)", path)
        if international_stock_sector_match:
            name = clean_text(str(self.read_json().get("name", "")))[:80]
            if not name:
                self.send_json({"error": "Informe o nome do setor"}, 400)
                return
            sector_id = int(international_stock_sector_match.group(1))
            try:
                with connect() as db:
                    current = db.execute("SELECT * FROM international_stock_sectors WHERE id = ?", (sector_id,)).fetchone()
                    if not current:
                        self.send_json({"error": "Setor nÃ£o encontrado"}, 404)
                        return
                    db.execute("UPDATE international_stock_sectors SET name = ?, updated_at = ? WHERE id = ?", (name, utc_now(), sector_id))
                    db.execute("UPDATE international_stock_management SET sector = ?, updated_at = ? WHERE sector = ? COLLATE NOCASE", (name, utc_now(), current["name"]))
                    db.execute("UPDATE assets SET segment = ? WHERE category = 'stocks_internacionais' AND segment = ? COLLATE NOCASE", (name, current["name"]))
                    row = db.execute("SELECT * FROM international_stock_sectors WHERE id = ?", (sector_id,)).fetchone()
                self.send_json(dict(row))
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este setor jÃ¡ estÃ¡ cadastrado"}, 409)
            return
        international_stock_sector_match = re.fullmatch(r"/api/international-stock-sectors/(\d+)", path)
        if international_stock_sector_match:
            with connect() as db:
                sector = db.execute("SELECT * FROM international_stock_sectors WHERE id = ?", (int(international_stock_sector_match.group(1)),)).fetchone()
                if not sector:
                    self.send_json({"error": "Setor nÃ£o encontrado"}, 404)
                    return
                usage = db.execute("SELECT COUNT(*) FROM international_stock_management WHERE sector = ? COLLATE NOCASE", (sector["name"],)).fetchone()[0]
                if usage:
                    self.send_json({"error": f"O setor estÃ¡ vinculado a {usage} stock(s) e nÃ£o pode ser excluÃ­do"}, 409)
                    return
                db.execute("DELETE FROM international_stock_sectors WHERE id = ?", (sector["id"],))
            self.send_json({}, 204)
            return
        fii_match = re.fullmatch(r"/api/fii-management/(\d+)", path)
        if fii_match:
            payload = self.read_json()
            ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
            sector = clean_text(str(payload.get("sector", "")))[:80]
            try:
                allocation_pct = float(payload.get("allocation_pct", 0) or 0)
                max_price = float(payload.get("max_price", 0) or 0)
            except (TypeError, ValueError):
                self.send_json({"error": "Alocação ou preço máximo inválido"}, 400)
                return
            if not ticker or not sector or allocation_pct < 0 or max_price < 0:
                self.send_json({"error": "Preencha todos os campos com valores válidos"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        """
                        UPDATE fii_management SET ticker = ?, sector = ?, allocation_pct = ?,
                            max_price = ?, updated_at = ? WHERE id = ?
                        """,
                        (ticker, sector, allocation_pct, max_price, utc_now(), int(fii_match.group(1))),
                    )
                    if not cursor.rowcount:
                        self.send_json({"error": "Fundo imobiliário não encontrado"}, 404)
                        return
                    db.execute(
                        "UPDATE assets SET segment = ? WHERE ticker = ? AND category = 'fiis_brasileiros'",
                        (sector, ticker),
                    )
                    row = db.execute("SELECT * FROM fii_management WHERE id = ?", (int(fii_match.group(1)),)).fetchone()
                self.send_json(dict(row))
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este ticker já está cadastrado"}, 409)
            return
        stock_match = re.fullmatch(r"/api/stocks-management/(\d+)", path)
        if stock_match:
            payload = self.read_json()
            ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
            sector = clean_text(str(payload.get("sector", "")))[:80]
            try:
                allocation_pct = float(payload.get("allocation_pct", 0) or 0)
                max_price = float(payload.get("max_price", 0) or 0)
            except (TypeError, ValueError):
                self.send_json({"error": "Alocação ou preço máximo inválido"}, 400)
                return
            if not ticker or not sector or allocation_pct < 0 or max_price < 0:
                self.send_json({"error": "Preencha todos os campos com valores válidos"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        """
                        UPDATE stock_management SET ticker = ?, sector = ?, allocation_pct = ?,
                            max_price = ?, updated_at = ? WHERE id = ?
                        """,
                        (ticker, sector, allocation_pct, max_price, utc_now(), int(stock_match.group(1))),
                    )
                    if not cursor.rowcount:
                        self.send_json({"error": "Ação brasileira não encontrada"}, 404)
                        return
                    db.execute(
                        "UPDATE assets SET segment = ? WHERE ticker = ? AND category = 'acoes_brasileiras'",
                        (sector, ticker),
                    )
                    row = db.execute("SELECT * FROM stock_management WHERE id = ?", (int(stock_match.group(1)),)).fetchone()
                self.send_json(dict(row))
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este ticker já está cadastrado"}, 409)
            return
        international_stock_match = re.fullmatch(r"/api/international-stocks-management/(\d+)", path)
        if international_stock_match:
            payload = self.read_json()
            ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
            sector = clean_text(str(payload.get("sector", "")))[:80]
            try:
                allocation_pct = float(payload.get("allocation_pct", 0) or 0)
                max_price = float(payload.get("max_price", 0) or 0)
            except (TypeError, ValueError):
                self.send_json({"error": "AlocaÃ§Ã£o ou preÃ§o mÃ¡ximo invÃ¡lido"}, 400)
                return
            if not ticker or not sector or allocation_pct < 0 or max_price < 0:
                self.send_json({"error": "Preencha todos os campos com valores vÃ¡lidos"}, 400)
                return
            try:
                with connect() as db:
                    cursor = db.execute(
                        """
                        UPDATE international_stock_management SET ticker = ?, sector = ?, allocation_pct = ?,
                            max_price = ?, updated_at = ? WHERE id = ?
                        """,
                        (ticker, sector, allocation_pct, max_price, utc_now(), int(international_stock_match.group(1))),
                    )
                    if not cursor.rowcount:
                        self.send_json({"error": "Stock internacional nÃ£o encontrada"}, 404)
                        return
                    db.execute(
                        "UPDATE assets SET segment = ? WHERE ticker = ? AND category = 'stocks_internacionais'",
                        (sector, ticker),
                    )
                    row = db.execute("SELECT * FROM international_stock_management WHERE id = ?", (int(international_stock_match.group(1)),)).fetchone()
                self.send_json(dict(row))
            except sqlite3.IntegrityError:
                self.send_json({"error": "Este ticker jÃ¡ estÃ¡ cadastrado"}, 409)
            return
        international_stock_match = re.fullmatch(r"/api/international-stocks-management/(\d+)", path)
        if international_stock_match:
            with connect() as db:
                cursor = db.execute("DELETE FROM international_stock_management WHERE id = ?", (int(international_stock_match.group(1)),))
            self.send_json({}, 204 if cursor.rowcount else 404)
            return
        match = re.fullmatch(r"/api/assets/(\d+)", path)
        if not match:
            self.send_json({"error": "Rota não encontrada"}, 404)
            return
        asset_id = int(match.group(1))
        payload = self.read_json()
        ticker = re.sub(r"[^A-Z0-9.\-]", "", str(payload.get("ticker", "")).upper())
        category = str(payload.get("category", ""))
        try:
            quantity = max(0, float(payload.get("quantity", 0) or 0))
        except (TypeError, ValueError):
            self.send_json({"error": "Quantidade inválida"}, 400)
            return
        segment = clean_text(str(payload.get("segment", "")))[:80] or None
        if not ticker or category not in CATEGORIES:
            self.send_json({"error": "Ticker ou categoria inválidos"}, 400)
            return
        try:
            with connect() as db:
                current = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
                if not current:
                    self.send_json({"error": "Ativo não encontrado"}, 404)
                    return
                identity_changed = current["ticker"] != ticker or current["category"] != category
                if identity_changed:
                    db.execute(
                        """
                        UPDATE assets SET ticker = ?, category = ?, quantity = ?, segment = ?, currency = ?, name = NULL,
                            price = NULL, pvp = NULL, liquidity = NULL, source_url = NULL, last_updated = NULL, error = NULL
                        WHERE id = ?
                        """,
                        (ticker, category, quantity, segment, CATEGORIES[category]["currency"], asset_id),
                    )
                    db.execute("DELETE FROM dividends WHERE asset_id = ?", (asset_id,))
                else:
                    db.execute("UPDATE assets SET quantity = ?, segment = ? WHERE id = ?", (quantity, segment, asset_id))
            if identity_changed:
                self.send_json(refresh_asset(asset_id))
            else:
                with connect() as db:
                    row = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
                    self.send_json(serialize_asset(db, row))
        except sqlite3.IntegrityError:
            self.send_json({"error": "Este ativo já está cadastrado nesta categoria"}, 409)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        sector_management_match = re.fullmatch(r"/api/(reit|etf)-sectors/(\d+)", path)
        if sector_management_match:
            kind = sector_management_match.group(1)
            sector_table = f"{kind}_sectors"
            management_table = f"{kind}_management"
            label = "REIT" if kind == "reit" else "ETF"
            with connect() as db:
                sector = db.execute(f"SELECT * FROM {sector_table} WHERE id = ?", (int(sector_management_match.group(2)),)).fetchone()
                if not sector:
                    self.send_json({"error": "Setor nÃ£o encontrado"}, 404)
                    return
                usage = db.execute(f"SELECT COUNT(*) FROM {management_table} WHERE sector = ? COLLATE NOCASE", (sector["name"],)).fetchone()[0]
                if usage:
                    self.send_json({"error": f"O setor estÃ¡ vinculado a {usage} {label}(s) e nÃ£o pode ser excluÃ­do"}, 409)
                    return
                db.execute(f"DELETE FROM {sector_table} WHERE id = ?", (sector["id"],))
            self.send_json({}, 204)
            return
        asset_management_match = re.fullmatch(r"/api/(reits|etfs)-management/(\d+)", path)
        if asset_management_match:
            table = "reit_management" if asset_management_match.group(1) == "reits" else "etf_management"
            with connect() as db:
                cursor = db.execute(f"DELETE FROM {table} WHERE id = ?", (int(asset_management_match.group(2)),))
            self.send_json({}, 204 if cursor.rowcount else 404)
            return
        international_stock_sector_match = re.fullmatch(r"/api/international-stock-sectors/(\d+)", path)
        if international_stock_sector_match:
            with connect() as db:
                sector = db.execute("SELECT * FROM international_stock_sectors WHERE id = ?", (int(international_stock_sector_match.group(1)),)).fetchone()
                if not sector:
                    self.send_json({"error": "Setor nÃ£o encontrado"}, 404)
                    return
                usage = db.execute("SELECT COUNT(*) FROM international_stock_management WHERE sector = ? COLLATE NOCASE", (sector["name"],)).fetchone()[0]
                if usage:
                    self.send_json({"error": f"O setor estÃ¡ vinculado a {usage} stock(s) e nÃ£o pode ser excluÃ­do"}, 409)
                    return
                db.execute("DELETE FROM international_stock_sectors WHERE id = ?", (sector["id"],))
            self.send_json({}, 204)
            return
        international_stock_match = re.fullmatch(r"/api/international-stocks-management/(\d+)", path)
        if international_stock_match:
            with connect() as db:
                cursor = db.execute("DELETE FROM international_stock_management WHERE id = ?", (int(international_stock_match.group(1)),))
            self.send_json({}, 204 if cursor.rowcount else 404)
            return
        sector_match = re.fullmatch(r"/api/fii-sectors/(\d+)", path)
        if sector_match:
            with connect() as db:
                sector = db.execute("SELECT * FROM fii_sectors WHERE id = ?", (int(sector_match.group(1)),)).fetchone()
                if not sector:
                    self.send_json({"error": "Setor não encontrado"}, 404)
                    return
                usage = db.execute("SELECT COUNT(*) FROM fii_management WHERE sector = ? COLLATE NOCASE", (sector["name"],)).fetchone()[0]
                if usage:
                    self.send_json({"error": f"O setor está vinculado a {usage} fundo(s) e não pode ser excluído"}, 409)
                    return
                db.execute("DELETE FROM fii_sectors WHERE id = ?", (sector["id"],))
            self.send_json({}, 204)
            return
        stock_sector_match = re.fullmatch(r"/api/stock-sectors/(\d+)", path)
        if stock_sector_match:
            with connect() as db:
                sector = db.execute("SELECT * FROM stock_sectors WHERE id = ?", (int(stock_sector_match.group(1)),)).fetchone()
                if not sector:
                    self.send_json({"error": "Setor não encontrado"}, 404)
                    return
                usage = db.execute("SELECT COUNT(*) FROM stock_management WHERE sector = ? COLLATE NOCASE", (sector["name"],)).fetchone()[0]
                if usage:
                    self.send_json({"error": f"O setor está vinculado a {usage} ação(ões) e não pode ser excluído"}, 409)
                    return
                db.execute("DELETE FROM stock_sectors WHERE id = ?", (sector["id"],))
            self.send_json({}, 204)
            return
        fii_match = re.fullmatch(r"/api/fii-management/(\d+)", path)
        if fii_match:
            with connect() as db:
                cursor = db.execute("DELETE FROM fii_management WHERE id = ?", (int(fii_match.group(1)),))
            self.send_json({}, 204 if cursor.rowcount else 404)
            return
        stock_match = re.fullmatch(r"/api/stocks-management/(\d+)", path)
        if stock_match:
            with connect() as db:
                cursor = db.execute("DELETE FROM stock_management WHERE id = ?", (int(stock_match.group(1)),))
            self.send_json({}, 204 if cursor.rowcount else 404)
            return
        match = re.fullmatch(r"/api/assets/(\d+)", path)
        if not match:
            self.send_json({"error": "Rota não encontrada"}, 404)
            return
        with connect() as db:
            cursor = db.execute("DELETE FROM assets WHERE id = ?", (int(match.group(1)),))
        self.send_json({}, 204 if cursor.rowcount else 404)

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Carteira disponível em http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
