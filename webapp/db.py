"""
SQLite 数据层 —— 站点配置 (sites) + 关键词队列 (keywords)。

设计要点：
- 每个「站」是一份完整可编辑的配置，等价于原来 config.py + main.py 里的常量。
- 关键词从网页上传 Excel 写入 keywords 表，逐条带状态。
- 用「每次操作开一个连接」的方式，天然线程安全（Web 线程读、后台线程写互不打架）。

数据目录由环境变量 DATA_DIR 决定（默认 ./data）。上 Render 时把 Render 磁盘挂到
这个目录即可持久化（DB + 生成的 Word/图片都在里面）。
"""
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

# ---- 路径 ----
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# 站点配置的字段（除 id / name / created_at 外全部可在网页编辑）
# key -> 默认值。新建站点时用这些默认值预填表单。
SITE_FIELDS: Dict[str, object] = {
    # WordPress 连接
    "wp_url": "",
    "wp_username": "",
    "wp_app_password": "",
    # API Keys
    "tavily_api_key": "",
    "openrouter_api_key": "",
    # 语言
    "language": "Vietnamese",
    # 模型
    "model_outline": "openai/gpt-5-mini",
    "model_seo": "google/gemini-3.1-flash-lite",
    "model_image_prompt": "google/gemini-3.1-flash-lite",
    "model_image_gen": "google/gemini-3.1-flash-image",
    # 字数
    "word_count_min": 2000,
    "word_count_max": 3000,
    "min_words": 1000,          # 正文最低字数（不达标会重试）
    "max_word_retries": 2,
    # 图片
    "image_enabled": 0,         # 0/1
    "image_retry": 1,
    # 发布
    "publish_status": "publish",  # publish / draft
    "daily_limit": 10,            # 每次运行处理多少条
    "pause_every_n_rows": 3,      # 每 N 条暂停 15 秒防限流
    # 分类 / 标签（逗号分隔）
    "fixed_categories": "",     # 非空则忽略每行 category，固定用这些分类；空则用每行 Excel 的 category
    "default_tags": "",         # 追加到每行的标签
    # 每篇统一追加的特殊要求（品牌 / CTA / 导流 URL 等）
    "brand_cta": "",
    # 自定义 prompt（空 = 用 prompts.py 里的默认模板）
    "prompt_outline": "",
    "prompt_article": "",
    "prompt_seo": "",
    "prompt_image": "",
}

# prompt 字段单独管理（配置表单不碰它们，避免互相覆盖）
PROMPT_FIELDS = ["prompt_outline", "prompt_article", "prompt_seo", "prompt_image"]

# 数值型字段（表单提交时转成 int）
_INT_FIELDS = {
    "word_count_min", "word_count_max", "min_words", "max_word_retries",
    "image_enabled", "image_retry", "daily_limit", "pause_every_n_rows",
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with _conn() as c:
        cols = ",\n".join(
            f"{k} {'INTEGER' if k in _INT_FIELDS else 'TEXT'}"
            for k in SITE_FIELDS
        )
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                {cols}
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS prompt_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ptype TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        # 已有库补列（老库升级用）：prompt_* 若缺则加上
        existing_cols = {r["name"] for r in c.execute("PRAGMA table_info(sites)").fetchall()}
        for pf in PROMPT_FIELDS:
            if pf not in existing_cols:
                c.execute(f"ALTER TABLE sites ADD COLUMN {pf} TEXT DEFAULT ''")
        c.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                total INTEGER DEFAULT 0,
                ok INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                cost REAL DEFAULT 0,
                status TEXT DEFAULT '',
                mode TEXT DEFAULT '',
                log TEXT DEFAULT ''
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER NOT NULL,
                main_keyword TEXT,
                secondary_keyword TEXT,
                topic TEXT,
                wordcounts INTEGER,
                specific TEXT,
                categories TEXT,
                tags TEXT,
                status TEXT DEFAULT 'pending',
                word_count INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                wp_post_id TEXT DEFAULT '',
                wp_link TEXT DEFAULT '',
                error TEXT DEFAULT '',
                updated_at TEXT,
                FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
            )
        """)


# ---------------- 站点 CRUD ----------------
def create_site(name: str, values: Dict) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = {k: values.get(k, v) for k, v in SITE_FIELDS.items()}
    keys = ["name", "created_at"] + list(SITE_FIELDS.keys())
    placeholders = ",".join("?" for _ in keys)
    vals = [name, now] + [data[k] for k in SITE_FIELDS]
    with _conn() as c:
        cur = c.execute(
            f"INSERT INTO sites ({','.join(keys)}) VALUES ({placeholders})", vals
        )
        return cur.lastrowid


def update_site(site_id: int, name: str = None, values: Dict = None):
    """只更新传入的字段（values 里出现的、且是合法列的），name 可选。
    这样「保存配置」和「保存 prompt」两个表单互不覆盖。"""
    values = values or {}
    cols = [k for k in values if k in SITE_FIELDS]
    sets = [f"{k}=?" for k in cols]
    vals = [values[k] for k in cols]
    if name is not None:
        sets.append("name=?")
        vals.append(name)
    if not sets:
        return
    vals.append(site_id)
    with _conn() as c:
        c.execute(f"UPDATE sites SET {', '.join(sets)} WHERE id=?", vals)


def delete_site(site_id: int):
    with _conn() as c:
        c.execute("DELETE FROM keywords WHERE site_id=?", (site_id,))
        c.execute("DELETE FROM sites WHERE id=?", (site_id,))


def get_site(site_id: int) -> Optional[Dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
        return dict(row) if row else None


def list_sites() -> List[Dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM sites ORDER BY id").fetchall()
        return [dict(r) for r in rows]


# ---------------- 关键词 CRUD ----------------
def add_keywords(site_id: int, rows: List[Dict]) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        for r in rows:
            c.execute("""
                INSERT INTO keywords
                (site_id, main_keyword, secondary_keyword, topic, wordcounts,
                 specific, categories, tags, status, updated_at)
                VALUES (?,?,?,?,?,?,?,?,'pending',?)
            """, (
                site_id,
                r.get("main_keyword", ""),
                r.get("secondary_keyword", ""),
                r.get("topic", ""),
                r.get("wordcounts", 0),
                r.get("specific", ""),
                r.get("categories", ""),
                r.get("tags", ""),
                now,
            ))
    return len(rows)


def add_keyword(site_id: int, row: Dict) -> int:
    """插入单条关键词，返回新行 id（用于「插入并立即生成」）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        cur = c.execute("""
            INSERT INTO keywords
            (site_id, main_keyword, secondary_keyword, topic, wordcounts,
             specific, categories, tags, status, updated_at)
            VALUES (?,?,?,?,?,?,?,?,'pending',?)
        """, (
            site_id,
            row.get("main_keyword", ""),
            row.get("secondary_keyword", ""),
            row.get("topic", ""),
            row.get("wordcounts", 0),
            row.get("specific", ""),
            row.get("categories", ""),
            row.get("tags", ""),
            now,
        ))
        return cur.lastrowid


def get_keywords_by_ids(site_id: int, ids: List[int]) -> List[Dict]:
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM keywords WHERE site_id=? AND id IN ({marks}) ORDER BY id",
            [site_id] + list(ids),
        ).fetchall()
        return [dict(r) for r in rows]


def list_keywords(site_id: int, status: str = None,
                  limit: int = None, offset: int = 0) -> List[Dict]:
    """默认返回全部（导出/快照用）；传 status/limit/offset 则分页 + 过滤（页面用）。"""
    q = "SELECT * FROM keywords WHERE site_id=?"
    params = [site_id]
    if status and status != "all":
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY id"
    if limit is not None:
        q += " LIMIT ? OFFSET ?"
        params += [limit, offset]
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def count_keywords(site_id: int, status: str = None) -> int:
    q = "SELECT COUNT(*) n FROM keywords WHERE site_id=?"
    params = [site_id]
    if status and status != "all":
        q += " AND status=?"
        params.append(status)
    with _conn() as c:
        return c.execute(q, params).fetchone()["n"]


def pending_keywords(site_id: int, limit: int) -> List[Dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM keywords WHERE site_id=? AND status='pending' ORDER BY id LIMIT ?",
            (site_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def update_keyword(kw_id: int, **fields):
    if not fields:
        return
    fields["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [kw_id]
    with _conn() as c:
        c.execute(f"UPDATE keywords SET {sets} WHERE id=?", vals)


def delete_keyword(kw_id: int):
    with _conn() as c:
        c.execute("DELETE FROM keywords WHERE id=?", (kw_id,))


def reset_keyword(kw_id: int):
    update_keyword(kw_id, status="pending", error="", wp_post_id="", wp_link="", word_count=0, cost_usd=0)


def reset_orphaned_processing() -> int:
    """服务重启时调用：把残留的 processing 退回 pending。
    重启后内存里的任务都已消失，不会有真在跑的行，所以这样做是安全的。"""
    with _conn() as c:
        cur = c.execute("UPDATE keywords SET status='pending' WHERE status='processing'")
        return cur.rowcount


# ---------------- 运行记录 ----------------
def add_run(site_id: int, started_at: str, finished_at: str, total: int,
            ok: int, failed: int, cost: float, status: str, mode: str, log: str) -> int:
    with _conn() as c:
        cur = c.execute("""
            INSERT INTO runs
            (site_id, started_at, finished_at, total, ok, failed, cost, status, mode, log)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (site_id, started_at, finished_at, total, ok, failed, cost, status, mode, log))
        return cur.lastrowid


def list_runs(site_id: int, limit: int = 20) -> List[Dict]:
    """列表不带 log（体积大），只返回摘要。"""
    with _conn() as c:
        rows = c.execute("""
            SELECT id, site_id, started_at, finished_at, total, ok, failed, cost, status, mode
            FROM runs WHERE site_id=? ORDER BY id DESC LIMIT ?
        """, (site_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_run(run_id: int) -> Optional[Dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None


# ---------------- Prompt 预设（存档）----------------
def add_preset(name: str, ptype: str, content: str) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO prompt_presets (name, ptype, content, created_at) VALUES (?,?,?,?)",
            (name.strip() or "未命名", ptype, content, now),
        )
        return cur.lastrowid


def list_presets() -> List[Dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM prompt_presets ORDER BY ptype, id").fetchall()
        return [dict(r) for r in rows]


def delete_preset(preset_id: int):
    with _conn() as c:
        c.execute("DELETE FROM prompt_presets WHERE id=?", (preset_id,))


def keyword_counts(site_id: int) -> Dict[str, int]:
    with _conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) n FROM keywords WHERE site_id=? GROUP BY status",
            (site_id,),
        ).fetchall()
    out = {"pending": 0, "done": 0, "error": 0, "skipped": 0, "total": 0}
    for r in rows:
        out[r["status"]] = r["n"]
        out["total"] += r["n"]
    return out
