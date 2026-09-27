from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'output' / 'x_growth.db'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS post_queue (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 created_at TEXT NOT NULL,
 scheduled_at TEXT,
 category TEXT NOT NULL,
 source_url TEXT,
 fact TEXT NOT NULL,
 interpretation TEXT,
 hypothesis TEXT,
 post_text TEXT NOT NULL,
 content_hash TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'draft',
 x_post_id TEXT,
 posted_at TEXT,
 error TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 x_post_id TEXT NOT NULL,
 captured_at TEXT NOT NULL,
 impressions INTEGER,
 likes INTEGER,
 replies INTEGER,
 reposts INTEGER,
 quotes INTEGER,
 bookmarks INTEGER,
 raw_json TEXT
);
'''


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    return con


def _clean(v: Any) -> str:
    if pd.isna(v):
        return ''
    return str(v).strip()


def _post_text(row: pd.Series, rank: int, mode: str, source: str = '') -> tuple[str, str, str, str]:
    name, code = _clean(row.get('name')), _clean(row.get('code'))
    close = row.get('close')
    rvol = row.get('rvol')
    dev = row.get('deviation_5ma_pct')
    price_date = str(row.get('price_date', ''))[:10]
    fact = f'{name}（{code}）を{mode}で監視。{price_date}終値{close:.1f}円、RVOL {rvol:.2f}倍、5MA乖離{dev:+.2f}% 。'
    strengths = []
    if row.get('technical_score', 0) >= 70: strengths.append('テクニカルが相対的に強い')
    if source != 'PROVISIONAL' and row.get('supply_score', 0) >= 70: strengths.append('需給スコアが高い')
    if rvol >= 1.5: strengths.append('出来高が20日平均を上回る')
    interpretation = ' / '.join(strengths) or '複数指標を継続確認したい局面'
    hypothesis = '次の取引日も出来高を伴って5MA上を維持できるかを確認。崩れれば仮説を撤回。'
    heading = '【暫定・需給未確認】' if source == 'PROVISIONAL' else ('【架空データ・投稿不可】' if source == 'DEMO' else '【監視メモ】')
    disclaimer = ('※価格・出来高の一次抽出のみ。信用・貸借・回転日数は未確認。投稿前に数値と利用条件を確認。'
                  if source == 'PROVISIONAL' else '※売買推奨ではなく、確認用の監視メモです。')
    text = (
        f'{heading} #{rank} {name}（{code}）\n'
        f'FACT：{price_date}終値 {close:.1f}円 / RVOL {rvol:.2f}倍 / 5MA乖離 {dev:+.2f}%\n'
        f'見方：{interpretation}\n'
        f'次に見る点：出来高を伴って5MA上を維持できるか。\n'
        f'{disclaimer}'
    )
    return fact, interpretation, hypothesis, text


def build_queue(as_of: str | None = None, count: int = 8) -> int:
    day = as_of or datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    csv_path = ROOT / 'output' / f'candidates_{day}.csv'
    if not csv_path.exists():
        raise FileNotFoundError(f'{csv_path.name} がありません。先に run_screen.py を実行してください。')
    df = pd.read_csv(csv_path, dtype={'code': str})
    marker = (ROOT / 'output' / 'DATA_SOURCE.txt').read_text(encoding='utf-8')
    source = marker.split(':', 1)[0]
    pass_col = 'primary_pass' if source == 'PROVISIONAL' else 'filter_pass'
    eligible = df[df[pass_col].astype(str).str.lower().isin(['true', '1'])].copy()
    if eligible.empty:
        export_queue()
        return 0
    modes = [('score_normal', '通常型'), ('score_surge', '噴き上げ型'), ('score_early_flow', '初動需給型')]
    picks = []
    seen = set()
    for score_col, label in modes:
        for _, row in eligible.sort_values(score_col, ascending=False).iterrows():
            key = _clean(row['code'])
            if key in seen: continue
            picks.append((row, label))
            seen.add(key)
            if len(picks) >= count: break
        if len(picks) >= count: break
    con = connect(); added = 0
    for rank, (row, mode) in enumerate(picks, 1):
        fact, interpretation, hypothesis, text = _post_text(row, rank, mode, source)
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        try:
            con.execute('''INSERT INTO post_queue(created_at,category,fact,interpretation,hypothesis,post_text,content_hash,status)
                           VALUES(?,?,?,?,?,?,?,'draft')''',
                        (datetime.now().isoformat(timespec='seconds'), '日本株', fact, interpretation, hypothesis, text, digest))
            added += 1
        except sqlite3.IntegrityError:
            pass
    con.commit(); con.close()
    export_queue()
    return added


def export_queue() -> Path:
    con = connect()
    df = pd.read_sql_query('SELECT id,created_at,scheduled_at,category,fact,interpretation,hypothesis,post_text,status,x_post_id,posted_at,error FROM post_queue ORDER BY id DESC', con)
    con.close()
    path = ROOT / 'output' / 'x_post_queue.csv'
    df.to_csv(path, index=False, encoding='utf-8-sig')
    return path


def set_status(ids: list[int], status: str) -> None:
    if status not in {'draft','approved','rejected'}:
        raise ValueError('status は draft / approved / rejected のいずれかです')
    con = connect()
    con.executemany('UPDATE post_queue SET status=? WHERE id=? AND status IN (\'draft\',\'approved\',\'rejected\')', [(status, i) for i in ids])
    con.commit(); con.close(); export_queue()


@dataclass
class XClient:
    bearer_token: str
    user_access_token: str

    @classmethod
    def from_env(cls) -> 'XClient':
        load_dotenv(ROOT / '.env')
        return cls(os.getenv('X_BEARER_TOKEN',''), os.getenv('X_USER_ACCESS_TOKEN',''))

    def create_post(self, text: str) -> dict[str, Any]:
        if not self.user_access_token:
            raise RuntimeError('X_USER_ACCESS_TOKEN が未設定です')
        r = requests.post('https://api.x.com/2/tweets', headers={'Authorization': f'Bearer {self.user_access_token}', 'Content-Type':'application/json'}, json={'text': text}, timeout=30)
        r.raise_for_status(); return r.json()

    def get_metrics(self, post_id: str) -> dict[str, Any]:
        if not self.bearer_token:
            raise RuntimeError('X_BEARER_TOKEN が未設定です')
        params = {'tweet.fields':'public_metrics,non_public_metrics,organic_metrics'}
        r = requests.get(f'https://api.x.com/2/tweets/{post_id}', headers={'Authorization': f'Bearer {self.bearer_token}'}, params=params, timeout=30)
        r.raise_for_status(); return r.json()


def publish_approved(dry_run: bool = True, limit: int = 8) -> list[str]:
    con = connect()
    rows = con.execute("SELECT id,post_text FROM post_queue WHERE status='approved' ORDER BY id LIMIT ?", (limit,)).fetchall()
    messages = []
    client = XClient.from_env()
    for post_id, text in rows:
        if dry_run:
            messages.append(f'DRY RUN id={post_id}: {text}')
            continue
        try:
            body = client.create_post(text)
            xid = str(body['data']['id'])
            con.execute("UPDATE post_queue SET status='posted', x_post_id=?, posted_at=?, error=NULL WHERE id=?", (xid, datetime.now().isoformat(timespec='seconds'), post_id))
            con.commit(); messages.append(f'POSTED id={post_id} x_id={xid}')
        except Exception as exc:
            con.execute('UPDATE post_queue SET error=? WHERE id=?', (str(exc), post_id)); con.commit()
            messages.append(f'ERROR id={post_id}: {exc}')
    con.close(); export_queue(); return messages


def collect_metrics() -> int:
    client = XClient.from_env(); con = connect(); count = 0
    rows = con.execute("SELECT x_post_id FROM post_queue WHERE status='posted' AND x_post_id IS NOT NULL").fetchall()
    for (xid,) in rows:
        body = client.get_metrics(xid); data = body.get('data', {}); m = data.get('public_metrics', {})
        con.execute('''INSERT INTO metrics(x_post_id,captured_at,impressions,likes,replies,reposts,quotes,bookmarks,raw_json)
                       VALUES(?,?,?,?,?,?,?,?,?)''', (xid, datetime.now().isoformat(timespec='seconds'), m.get('impression_count'), m.get('like_count'), m.get('reply_count'), m.get('retweet_count'), m.get('quote_count'), m.get('bookmark_count'), json.dumps(body, ensure_ascii=False)))
        count += 1
    con.commit(); con.close(); return count


def performance_report() -> Path:
    con = connect()
    df = pd.read_sql_query('''SELECT q.id,q.post_text,q.posted_at,m.* FROM post_queue q JOIN metrics m ON q.x_post_id=m.x_post_id ORDER BY m.captured_at DESC''', con)
    con.close(); path = ROOT / 'output' / 'x_performance.csv'; df.to_csv(path,index=False,encoding='utf-8-sig'); return path
