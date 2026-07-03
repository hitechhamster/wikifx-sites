"""
按「站点配置」跑生成流程 —— 复用 workflow / wordpress_client / image_generator，
并提供后台任务管理（一个站一个后台线程 + 内存里的进度与实时日志）。

与命令行版 main.py 的区别：
- 配置来自数据库里的 site dict，而不是 config.py。
- 逐条处理 keywords 表里的 pending 行，实时把状态写回数据库。
- 日志走 log 回调进内存缓冲，前端轮询 /progress 取回。
"""
import ctypes
import gc
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Dict, List, Optional

# Linux 下强制 glibc 把空闲内存还给 OS。Python 长跑服务 + 大字符串/JSON
# 反复分配会造成堆碎片，RSS 只涨不降，最终在 512MB 容器里 OOM。
# 每处理完一条调用一次，几乎零开销，是压 RSS 最有效的手段。
try:
    _libc = ctypes.CDLL("libc.so.6")
except OSError:  # 本地 Windows 开发环境没有 libc
    _libc = None


def _trim_memory():
    gc.collect()
    if _libc is not None:
        try:
            _libc.malloc_trim(0)
        except Exception:
            pass

# 纯函数（Markdown→Word / Markdown→HTML / slug / 字数），不依赖 pandas
from textutils import (
    create_word_document,
    markdown_to_html_for_wp,
    slugify_keyword,
    sanitize_filename,
    count_words,
)
from workflow import ListicleWorkflow
from wordpress_client import WordPressClient
from image_generator import generate_image
from webapp import db


def _split_csv(val: str) -> List[str]:
    if not val:
        return []
    return [x.strip() for x in str(val).replace("，", ",").split(",") if x.strip()]


class _StopRequested(Exception):
    """运行中途收到停止指令。"""


# ============================================================
# 单条处理
# ============================================================
def process_one(site: Dict, kw: Dict, log: Callable[[str], None],
                should_stop: Callable[[], bool] = None) -> Dict:
    """处理一条关键词，返回结果 dict（含 status / word_count / wp 信息 / cost / error）。

    should_stop: 每步之间会调用它；返回 True 则中途停止（当前这条不算 done/error）。
    """
    result = {
        "status": "error", "word_count": 0, "cost_usd": 0.0,
        "wp_post_id": "", "wp_link": "", "error": "",
    }

    def ck():
        if should_stop and should_stop():
            raise _StopRequested()

    workflow = ListicleWorkflow(
        tavily_api_key=site.get("tavily_api_key"),
        openrouter_api_key=site.get("openrouter_api_key"),
        model_outline=site.get("model_outline"),
        model_seo=site.get("model_seo"),
        model_image_prompt=site.get("model_image_prompt"),
        prompt_outline=site.get("prompt_outline"),
        prompt_article=site.get("prompt_article"),
        prompt_seo=site.get("prompt_seo"),
        prompt_image=site.get("prompt_image"),
    )
    workflow.row_cost = 0.0

    language = site.get("language") or "English"
    main_kw = (kw.get("main_keyword") or "").strip()
    sec_kw = (kw.get("secondary_keyword") or "").strip()
    topic = (kw.get("topic") or "").strip()

    # 字数夹到站点的 min/max
    wc_min = int(site.get("word_count_min") or 2000)
    wc_max = int(site.get("word_count_max") or 3000)
    try:
        wc = int(kw.get("wordcounts") or wc_min)
    except (TypeError, ValueError):
        wc = wc_min
    wc = max(wc_min, min(wc, wc_max))

    # 特殊要求：每行的 specific + 站点统一的 brand_cta
    specific = (kw.get("specific") or "").strip()
    brand_cta = (site.get("brand_cta") or "").strip()
    if brand_cta:
        specific = (specific + " " if specific else "") + brand_cta

    if not (main_kw and sec_kw and topic):
        result["error"] = "main_keyword / secondary_keyword / topic 不能为空"
        return result

    try:
        ck()
        log(f"[1] Tavily 搜索主关键词: {main_kw}")
        main_res = workflow.tavily_search(main_kw, max_results=5)
        time.sleep(1.0)

        ck()
        log(f"[2] Tavily 搜索次关键词: {sec_kw}")
        sec_res = workflow.tavily_search(sec_kw, max_results=5)
        time.sleep(1.0)

        ck()
        log("[3] 生成大纲...")
        outline = workflow.generate_outline(
            main_kw, sec_kw, topic, wc, specific, main_res, sec_res, language
        )
        if not outline or outline.startswith("LLM call error"):
            raise RuntimeError(f"大纲生成失败: {outline}")

        log("[4] 撰写正文...")
        min_words = int(site.get("min_words") or 1000)
        max_retries = int(site.get("max_word_retries") or 2)
        article = ""
        word_count = 0
        for attempt in range(1, max_retries + 2):
            ck()
            spec_call = specific
            if attempt > 1:
                spec_call = (spec_call + " " if spec_call else "") + (
                    f"IMPORTANT: The article MUST be at least {min_words} words. "
                    f"Previous draft only had {word_count} words; expand each section."
                )
            article = workflow.write_article(
                main_kw, sec_kw, topic, wc, spec_call, outline, main_res, sec_res, language
            )
            if not article or article.startswith("LLM call error"):
                if attempt <= max_retries:
                    log(f"     正文第 {attempt} 次失败，重试...")
                    time.sleep(3)
                    continue
                raise RuntimeError(f"正文生成失败: {article}")
            word_count = count_words(article, language)
            if word_count >= min_words:
                log(f"     正文 {word_count} 字 (第 {attempt} 次)")
                break
            if attempt <= max_retries:
                log(f"     仅 {word_count} 字 (最低 {min_words})，重试...")
                time.sleep(3)
            else:
                log(f"     重试 {max_retries} 次仍偏短，用当前版本 ({word_count} 字)")

        ck()
        log("[5] 生成 SEO 元数据...")
        seo = workflow.generate_seo_meta(article, main_kw, language)

        # ---- 图片 ----
        image_path = None
        if int(site.get("image_enabled") or 0):
            log("[6] 生成图片 prompt...")
            img_prompt = workflow.generate_image_prompt(article, main_kw)
            img_dir = os.path.join(db.OUTPUT_DIR, f"site_{site['id']}", "images")
            slug = sanitize_filename(main_kw).replace(" ", "_").lower() or "post"
            log("[7] 生成图片 (Nano Banana)...")
            image_path = generate_image(
                img_prompt,
                os.path.join(img_dir, f"{kw['id']}_{slug}.png"),
                retry=int(site.get("image_retry") or 1),
                api_key=site.get("openrouter_api_key"),
                model=site.get("model_image_gen"),
            )
            if image_path:
                log(f"     图片: {image_path}")

        # ---- Word 存档 ----
        log("[8] 保存 Word 文档...")
        word_dir = os.path.join(db.OUTPUT_DIR, f"site_{site['id']}", "articles")
        word_path = os.path.join(word_dir, f"{kw['id']}_{sanitize_filename(main_kw)}.docx")
        create_word_document(article, word_path)

        # ---- WordPress ----
        wp_url = (site.get("wp_url") or "").strip()
        if wp_url and site.get("wp_username") and site.get("wp_app_password"):
            status = site.get("publish_status") or "publish"
            log(f"[9] 发布到 WordPress (status={status})...")
            wp = WordPressClient(
                wp_url=wp_url,
                wp_username=site.get("wp_username"),
                wp_app_password=site.get("wp_app_password"),
            )
            media = None
            if image_path:
                media = wp.upload_media(image_path, alt_text=main_kw)

            title_text, html_body = markdown_to_html_for_wp(
                article,
                inline_image_url=media["url"] if media else None,
                inline_alt=main_kw,
            )
            post_title = title_text or seo["seo_title"]
            post_slug = slugify_keyword(main_kw)

            # 分类：站点固定分类优先，否则用该行 Excel 的 category
            fixed_cats = _split_csv(site.get("fixed_categories"))
            cat_names = fixed_cats if fixed_cats else _split_csv(kw.get("categories"))
            tag_names = _split_csv(kw.get("tags")) + _split_csv(site.get("default_tags"))

            cat_ids = wp.resolve_categories(cat_names)
            tag_ids = wp.resolve_tags(tag_names)

            post = wp.create_post(
                title=post_title,
                content_html=html_body,
                excerpt=seo["seo_description"],
                featured_media=media["id"] if media else None,
                categories=cat_ids,
                tags=tag_ids,
                status=status,
                slug=post_slug,
            )
            if post and post.get("id"):
                result["wp_post_id"] = str(post["id"])
                result["wp_link"] = post.get("link") or ""
                log(f"     已{('发布' if status == 'publish' else '存草稿')}: {post.get('link')}")
            else:
                log("     [警告] 文章创建失败")
        else:
            log("[9] 未配置 WordPress，跳过发布（仅本地存档）")

        result["status"] = "done"
        result["word_count"] = word_count
        result["cost_usd"] = round(workflow.row_cost, 6)
        log(f"[✓] 完成 | 本篇花费 ${workflow.row_cost:.4f}")

    except _StopRequested:
        result["status"] = "stopped"
        result["cost_usd"] = round(workflow.row_cost, 6)
        log("[■] 已停止（当前这条中止）")
    except Exception as e:
        import traceback
        result["error"] = str(e)[:300]
        result["cost_usd"] = round(workflow.row_cost, 6)
        log(f"[✗] 失败: {e}")
        log(traceback.format_exc())

    return result


# ============================================================
# 后台任务管理
# ============================================================
class Job:
    def __init__(self, site_id: int):
        self.site_id = site_id
        self.running = False
        self.stop_flag = False
        self.total = 0
        self.done = 0
        self.ok = 0
        self.failed = 0
        self.current = ""
        self.cost = 0.0
        self.started_at = ""
        self.finished_at = ""
        self.logs: deque = deque(maxlen=500)
        self._lock = threading.Lock()

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self.logs.append(f"[{ts}] {msg}")

    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "running": self.running,
                "total": self.total,
                "done": self.done,
                "ok": self.ok,
                "failed": self.failed,
                "current": self.current,
                "cost": round(self.cost, 4),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "logs": list(self.logs),
            }


class JobManager:
    def __init__(self):
        self._jobs: Dict[int, Job] = {}
        self._lock = threading.Lock()

    def get(self, site_id: int) -> Optional[Job]:
        return self._jobs.get(site_id)

    def is_running(self, site_id: int) -> bool:
        j = self._jobs.get(site_id)
        return bool(j and j.running)

    def stop(self, site_id: int):
        j = self._jobs.get(site_id)
        if j:
            j.stop_flag = True

    def start(self, site_id: int, limit: Optional[int] = None,
              kw_ids: Optional[list] = None) -> bool:
        with self._lock:
            if self.is_running(site_id):
                return False
            job = Job(site_id)
            job.running = True
            job.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._jobs[site_id] = job
        t = threading.Thread(target=self._run, args=(site_id, job, limit, kw_ids), daemon=True)
        t.start()
        return True

    def _run(self, site_id: int, job: Job, limit: Optional[int], kw_ids: Optional[list] = None):
        try:
            site = db.get_site(site_id)
            if not site:
                job.log("站点不存在")
                return
            pause_n = int(site.get("pause_every_n_rows") or 3)
            if kw_ids:
                # 插入任务模式：只跑指定的这几条
                pending = db.get_keywords_by_ids(site_id, kw_ids)
            else:
                lim = limit if limit is not None else int(site.get("daily_limit") or 10)
                pending = db.pending_keywords(site_id, lim)
            job.total = len(pending)
            if not pending:
                job.log("没有待处理的关键词（pending）")
                return
            job.log(f"本次处理 {len(pending)} 条")

            for n, kw in enumerate(pending):
                if job.stop_flag:
                    job.log("收到停止指令，中止本次运行")
                    break
                job.current = kw.get("main_keyword") or f"#{kw['id']}"
                job.log(f"===== [{n+1}/{len(pending)}] {job.current} =====")
                db.update_keyword(kw["id"], status="processing")

                res = process_one(site, kw, job.log, should_stop=lambda: job.stop_flag)

                # 中途停止：这条退回 pending，不计入成功/失败，结束本轮
                if res["status"] == "stopped":
                    db.update_keyword(kw["id"], status="pending")
                    job.cost += res["cost_usd"]
                    job.log("已停止，当前这条退回 pending")
                    break

                db.update_keyword(
                    kw["id"],
                    status=res["status"],
                    word_count=res["word_count"],
                    cost_usd=res["cost_usd"],
                    wp_post_id=res["wp_post_id"],
                    wp_link=res["wp_link"],
                    error=res["error"],
                )
                job.done += 1
                job.cost += res["cost_usd"]
                if res["status"] == "done":
                    job.ok += 1
                else:
                    job.failed += 1

                # 每条处理完把空闲内存还给 OS，防止 RSS 长期爬升撞 512MB
                _trim_memory()

                if pause_n and (n + 1) % pause_n == 0 and (n + 1) < len(pending):
                    job.log("暂停 15 秒防限流...")
                    for _ in range(15):
                        if job.stop_flag:
                            break
                        time.sleep(1)

            job.log(f"运行结束 | 成功 {job.ok} / 失败 {job.failed} | 总花费 ${job.cost:.4f}")
        except Exception as e:
            job.log(f"运行异常: {e}")
        finally:
            job.running = False
            job.current = ""
            job.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # 保存运行记录（含完整日志），供页面「运行记录」查看
            try:
                if job.total > 0 or job.done > 0:
                    run_status = "stopped" if job.stop_flag else "done"
                    db.add_run(
                        site_id=site_id,
                        started_at=job.started_at,
                        finished_at=job.finished_at,
                        total=job.total,
                        ok=job.ok,
                        failed=job.failed,
                        cost=round(job.cost, 6),
                        status=run_status,
                        mode=("insert" if kw_ids else "scheduled"),
                        log="\n".join(job.logs),
                    )
            except Exception as _e:
                print(f"[WARN] 保存运行记录失败: {_e}")


# 全局单例
jobs = JobManager()
