"""
一次性种子脚本：把 config.py + main.py 里原来的越南语站配置，
连同 input.xlsx 的关键词，导入 Web 后台数据库。

- 已发布的行(status 以 done 开头) -> 标记 done，不会重发
- skipped 行 -> skipped
- 其余(空 / error / 待处理) -> pending

可重复运行：若同 WP 地址的站点已存在则不重复创建。
用法：  .venv/Scripts/python.exe seed_vietnam.py
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd

import config
from webapp import db

db.init_db()

# ---- 站点配置：来自 config.py + main.py 常量 ----
SITE_NAME = "越南语站3 (dzypjy.com)"
values = {
    "wp_url": config.WP_URL,
    "wp_username": config.WP_USERNAME,
    "wp_app_password": "",   # WP 应用密码在网页站点配置里填，不进代码/环境变量
    "tavily_api_key": "",    # 留空 → 运行时回落到环境变量 TAVILY_API_KEY
    "openrouter_api_key": "",  # 留空 → 运行时回落到环境变量 OPENROUTER_API_KEY
    "language": config.DEFAULT_LANGUAGE,                 # Vietnamese
    "model_outline": config.MODEL_OUTLINE_AND_ARTICLE,
    "model_seo": config.MODEL_SEO_META,
    "model_image_prompt": config.MODEL_IMAGE_PROMPT,
    "model_image_gen": config.MODEL_IMAGE_GEN,
    "word_count_min": config.WORD_COUNT_MIN,
    "word_count_max": config.WORD_COUNT_MAX,
    "min_words": 1000,                                   # main.py: MIN_WORDS
    "max_word_retries": 2,                               # main.py: MAX_WORD_RETRIES
    "image_enabled": 1 if config.IMAGE_ENABLED else 0,
    "image_retry": config.IMAGE_RETRY,
    "publish_status": "publish",                         # main.py: WP_POST_STATUS
    "daily_limit": 10,                                   # main.py: DAILY_LIMIT
    "pause_every_n_rows": config.PAUSE_EVERY_N_ROWS,
    "fixed_categories": "Giáo dục",                      # main.py 里写死的固定分类
    "default_tags": "",
    "brand_cta": "",
}

# ---- 幂等：同 WP 地址已存在则跳过建站 ----
existing = next((s for s in db.list_sites() if s["wp_url"] == config.WP_URL), None)
if existing:
    site_id = existing["id"]
    print(f"[i] 站点已存在(id={site_id}): {existing['name']}, 跳过创建。")
else:
    site_id = db.create_site(SITE_NAME, values)
    print(f"[OK] 已创建站点 id={site_id}: {SITE_NAME}")


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

df = pd.read_excel("input.xlsx")
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
            "", "", st, now,
        ))
        added += 1

print(f"[OK] 导入完成: 新增 {added} 条 | 跳过重复 {skipped_dup} 条")
print(f"    其中 pending={counts['pending']} done={counts['done']} skipped={counts['skipped']}")
print(f"[i] 打开 http://127.0.0.1:8000/sites/{site_id} 查看")
