"""
一次性种子脚本：把「Hawk站群1 教育文章」(blog.wikibit.com) 内置进 Web 后台。

- 站点专属信息（WP 账号 / 语言 / API Key）来自该站原 config.py
- 模型配置 + 生产流程：从越南站(id=1)复制，保持一致
- 关键词从 input_hawk1.xlsx 导入；done 保留(不重发)，其余置 pending
- 分类不固定，用 Excel 每行 category 列

可重复运行：同 WP 地址已存在则跳过建站、已导入的关键词不重复导。
用法：  .venv/Scripts/python.exe seed_hawk1.py
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
from webapp import db

db.init_db()

# ---- 站点专属（来自 Hawk站群1 教育文章 的 config.py）----
# WP 应用密码在网页站点配置里填；tavily/openrouter 留空走环境变量。
SITE_NAME = "教育站1 (blog.wikibit.com)"
WP_URL = "https://blog.wikibit.com/"
WP_USERNAME = "kbing0830"
WP_APP_PASSWORD = ""     # 在网页站点配置里填
TAVILY_API_KEY = ""      # 留空 → 运行时回落到环境变量 TAVILY_API_KEY
OPENROUTER_API_KEY = ""  # 留空 → 运行时回落到环境变量 OPENROUTER_API_KEY
LANGUAGE = "English"
INPUT_XLSX = "input_hawk1.xlsx"

# ---- 模型 + 生产流程：从越南站(id=1)复制 ----
vn = db.get_site(1)
if not vn:
    raise SystemExit("[ERR] 越南站(id=1)不存在，请先跑 seed_vietnam.py")

COPY_FROM_VN = [
    "model_outline", "model_seo", "model_image_prompt", "model_image_gen",
    "word_count_min", "word_count_max", "min_words", "max_word_retries",
    "image_enabled", "image_retry", "publish_status", "daily_limit", "pause_every_n_rows",
    "prompt_outline", "prompt_article", "prompt_seo", "prompt_image", "brand_cta",
]
values = {k: vn[k] for k in COPY_FROM_VN}
values.update({
    "wp_url": WP_URL,
    "wp_username": WP_USERNAME,
    "wp_app_password": WP_APP_PASSWORD,
    "tavily_api_key": TAVILY_API_KEY,
    "openrouter_api_key": OPENROUTER_API_KEY,
    "language": LANGUAGE,
    "fixed_categories": "",   # 该站不固定分类，用 Excel 每行 category
})

# ---- 幂等建站 ----
existing = next((s for s in db.list_sites() if (s["wp_url"] or "").rstrip("/") == WP_URL.rstrip("/")), None)
if existing:
    site_id = existing["id"]
    print(f"[i] 站点已存在(id={site_id}): {existing['name']}, 跳过创建。")
else:
    site_id = db.create_site(SITE_NAME, values)
    print(f"[OK] 已创建站点 id={site_id}: {SITE_NAME}")
    print(f"     模型/流程已对齐越南站: outline={values['model_outline']}, "
          f"image_enabled={values['image_enabled']}, publish={values['publish_status']}")


# ---- 导入关键词 ----
def map_status(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "pending"
    s = str(v).strip().lower()
    if s.startswith("done"):
        return "done"
    if s.startswith("skipped"):
        return "skipped"
    return "pending"


existing_kw = {(k["main_keyword"] or "").strip().lower() for k in db.list_keywords(site_id)}
df = pd.read_excel(INPUT_XLSX)
now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
added = skipped_dup = 0
counts = {"pending": 0, "done": 0, "skipped": 0}

with db._conn() as c:
    for _, r in df.iterrows():
        main_kw = str(r.get("main_keyword") or "").strip()
        if not main_kw:
            continue
        if main_kw.lower() in existing_kw:
            skipped_dup += 1
            continue
        st = map_status(r.get("status"))
        counts[st] += 1
        try:
            wc = int(float(r.get("wordcounts") or 0))
        except (TypeError, ValueError):
            wc = 0
        c.execute("""
            INSERT INTO keywords
            (site_id, main_keyword, secondary_keyword, topic, wordcounts,
             specific, categories, tags, status, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            site_id, main_kw,
            str(r.get("secondary_keyword") or "").strip(),
            str(r.get("topic") or "").strip(),
            wc,
            str(r.get("specific") or "").strip() if pd.notna(r.get("specific")) else "",
            str(r.get("category") or "").strip() if pd.notna(r.get("category")) else "",
            "", st, now,
        ))
        added += 1

print(f"[OK] 导入完成: 新增 {added} 条 | 跳过重复 {skipped_dup} 条")
print(f"    其中 pending={counts['pending']} done={counts['done']} skipped={counts['skipped']}")
print(f"[i] 打开 http://127.0.0.1:8000/sites/{site_id} 查看")
