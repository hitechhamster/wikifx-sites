"""
WordPress REST API 客户端
- 上传图片到媒体库
- 查找或创建分类/标签
- 发布文章（默认草稿）

依赖 WP 的 Application Password 做 Basic Auth。
要求 WP 版本 ≥ 5.6。REST 路径是 /wp-json/wp/v2/...
"""
import os
from typing import Dict, List, Optional

import requests
from requests.auth import HTTPBasicAuth

from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD


def _mime_of(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/png")


class WordPressClient:
    def __init__(self, wp_url: str = None, wp_username: str = None, wp_app_password: str = None):
        # 参数优先，缺省回落到 config.py（保证命令行旧流程不受影响）
        url = wp_url or WP_URL
        user = wp_username or WP_USERNAME
        pwd = wp_app_password or WP_APP_PASSWORD
        self.base_url = url.rstrip("/") + "/wp-json/wp/v2"
        # WP 的 Application Password 原始格式带空格，去掉空格更稳妥
        self.auth = HTTPBasicAuth(user, pwd.replace(" ", ""))

    # ---------------- 媒体 ----------------
    def upload_media(self, filepath: str, alt_text: str = "") -> Optional[Dict]:
        """
        上传图片到 WP 媒体库，返回 {id, url}。失败返回 None。
        """
        if not filepath or not os.path.exists(filepath):
            print(f"     ⚠️  图片文件不存在：{filepath}")
            return None

        filename = os.path.basename(filepath)
        mime = _mime_of(filename)
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime,
        }

        try:
            with open(filepath, "rb") as f:
                body = f.read()
            resp = requests.post(
                f"{self.base_url}/media",
                headers=headers,
                data=body,
                auth=self.auth,
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()
            media_id = data.get("id")
            media_url = data.get("source_url")
            if not media_id or not media_url:
                print(f"     ⚠️  上传返回异常：{str(data)[:200]}")
                return None

            # 补 alt_text / caption（可有可无，失败不影响流程）
            if alt_text:
                try:
                    requests.post(
                        f"{self.base_url}/media/{media_id}",
                        json={"alt_text": alt_text, "caption": alt_text},
                        auth=self.auth,
                        timeout=30,
                    )
                except Exception:
                    pass

            return {"id": media_id, "url": media_url}
        except requests.HTTPError as e:
            body_txt = e.response.text[:300] if e.response is not None else ""
            print(f"     ❌ 媒体上传失败：{e} | {body_txt}")
            return None
        except Exception as e:
            print(f"     ❌ 媒体上传异常：{e}")
            return None

    # ---------------- 分类 / 标签 ----------------
    def _get_or_create_term(self, taxonomy: str, name: str) -> Optional[int]:
        name = (name or "").strip()
        if not name:
            return None
        try:
            # 精确匹配：先用 search，再在结果里找 name ==
            resp = requests.get(
                f"{self.base_url}/{taxonomy}",
                params={"search": name, "per_page": 50},
                auth=self.auth,
                timeout=30,
            )
            resp.raise_for_status()
            for item in resp.json():
                if item.get("name", "").strip().lower() == name.lower():
                    return item["id"]

            # 没找到 → 创建
            resp = requests.post(
                f"{self.base_url}/{taxonomy}",
                json={"name": name},
                auth=self.auth,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("id")
        except requests.HTTPError as e:
            body_txt = e.response.text[:200] if e.response is not None else ""
            # 有些 WP 角色无权限创建 term，此时忽略即可
            print(f"     ⚠️  {taxonomy} 处理失败（{name}）：{e} | {body_txt}")
            return None
        except Exception as e:
            print(f"     ⚠️  {taxonomy} 处理异常（{name}）：{e}")
            return None

    def resolve_categories(self, names: List[str]) -> List[int]:
        if not names:
            return []
        return [i for i in (self._get_or_create_term("categories", n) for n in names) if i]

    def resolve_tags(self, names: List[str]) -> List[int]:
        if not names:
            return []
        return [i for i in (self._get_or_create_term("tags", n) for n in names) if i]

    # ---------------- 文章 ----------------
    def create_post(
        self,
        title: str,
        content_html: str,
        excerpt: str = "",
        featured_media: Optional[int] = None,
        categories: Optional[List[int]] = None,
        tags: Optional[List[int]] = None,
        status: str = "draft",
        slug: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        创建文章。成功返回 {id, link}，失败返回 None。

        slug 用于控制最终 URL 的 path 部分。例如 slug="metatrader-5-broker"
        会生成 https://站点/metatrader-5-broker。WP 会对 slug 再做一次清洗
        （转小写、空格转 -、剥非法字符），并在重名时自动追加 -2 / -3。
        """
        payload = {
            "title": title,
            "content": content_html,
            "status": status,
            "excerpt": excerpt,
        }
        if slug:
            payload["slug"] = slug
        if featured_media:
            payload["featured_media"] = featured_media
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags

        try:
            resp = requests.post(
                f"{self.base_url}/posts",
                json=payload,
                auth=self.auth,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return {"id": data.get("id"), "link": data.get("link")}
        except requests.HTTPError as e:
            body_txt = e.response.text[:300] if e.response is not None else ""
            print(f"     ❌ 发布失败：{e} | {body_txt}")
            return None
        except Exception as e:
            print(f"     ❌ 发布异常：{e}")
            return None