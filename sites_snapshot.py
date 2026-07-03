"""
站点快照 —— 把本地数据库里所有站点的「设置 + prompt + 关键词队列」导出成一个
不含密钥的 JSON，提交进仓库；换台机器 / 部署到 Render 后一条命令即可还原。

  导出： .venv/Scripts/python.exe sites_snapshot.py export
  还原： python sites_snapshot.py import

导出的 JSON 里 **不含** WordPress 应用密码 / Tavily / OpenRouter Key（一律置空）：
  - WP 应用密码：还原后到网页「站点配置」里逐站填
  - Tavily / OpenRouter：留空即回落到环境变量

还原是幂等的：同 WP 地址的站点已存在则跳过（不会重复建、不重复导关键词）。
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from webapp import db

db.init_db()

SNAPSHOT = os.path.join(os.path.dirname(__file__), "seeds", "sites_snapshot.json")

# 导出时置空的敏感字段
SECRET_FIELDS = ["wp_app_password", "tavily_api_key", "openrouter_api_key"]

# 关键词要保留的列
KW_COLS = ["main_keyword", "secondary_keyword", "topic", "wordcounts", "specific",
           "categories", "tags", "status", "word_count", "cost_usd", "wp_post_id", "wp_link"]


def do_export():
    sites = db.list_sites()
    out = []
    for s in sites:
        values = {k: s.get(k) for k in db.SITE_FIELDS}
        for f in SECRET_FIELDS:
            values[f] = ""   # 抹掉密钥
        kws = [{c: k.get(c) for c in KW_COLS} for k in db.list_keywords(s["id"])]
        out.append({"name": s["name"], "values": values, "keywords": kws})

    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    total_kw = sum(len(x["keywords"]) for x in out)
    print(f"[OK] 已导出 {len(out)} 个站点、{total_kw} 条关键词 -> {SNAPSHOT}")
    for x in out:
        print(f"     - {x['name']}: {len(x['keywords'])} 条  (密钥已抹除)")


def do_import():
    if not os.path.exists(SNAPSHOT):
        raise SystemExit(f"[ERR] 找不到快照文件: {SNAPSHOT}")
    with open(SNAPSHOT, encoding="utf-8") as f:
        data = json.load(f)

    existing_urls = {(s["wp_url"] or "").rstrip("/") for s in db.list_sites()}
    created = skipped = 0
    for site in data:
        url = (site["values"].get("wp_url") or "").rstrip("/")
        if url and url in existing_urls:
            print(f"[i] 已存在，跳过: {site['name']}")
            skipped += 1
            continue
        site_id = db.create_site(site["name"], site["values"])
        rows = [{c: k.get(c) for c in KW_COLS} for k in site["keywords"]]
        # 逐条插入并保留状态
        now_rows = []
        with db._conn() as c:
            for r in rows:
                c.execute("""
                    INSERT INTO keywords
                    (site_id, main_keyword, secondary_keyword, topic, wordcounts,
                     specific, categories, tags, status, word_count, cost_usd,
                     wp_post_id, wp_link, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """, (
                    site_id, r.get("main_keyword", ""), r.get("secondary_keyword", ""),
                    r.get("topic", ""), r.get("wordcounts") or 0, r.get("specific", ""),
                    r.get("categories", ""), r.get("tags", ""), r.get("status") or "pending",
                    r.get("word_count") or 0, r.get("cost_usd") or 0,
                    r.get("wp_post_id") or "", r.get("wp_link") or "",
                ))
        created += 1
        print(f"[OK] 已还原: {site['name']} (id={site_id}, {len(rows)} 条关键词)")

    print(f"\n[DONE] 新建 {created} 个站点，跳过 {skipped} 个。")
    print("提醒：到网页「站点配置」里给每个站填 WordPress 应用密码；")
    print("      Tavily / OpenRouter 留空即用环境变量。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="站点设置快照 导出/还原")
    ap.add_argument("action", choices=["export", "import"], help="export=导出到 JSON, import=从 JSON 还原")
    args = ap.parse_args()
    (do_export if args.action == "export" else do_import)()
