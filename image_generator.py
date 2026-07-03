"""
OpenRouter Nano Banana (Gemini 2.5 Flash Image) 图片生成
用 chat completions 接口，modalities 带上 "image"
"""
import base64
import os
import time
from typing import Optional

import requests

from config import OPENROUTER_API_KEY, MODEL_IMAGE_GEN, IMAGE_RETRY


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _extract_image_b64(resp_json: dict) -> Optional[str]:
    """
    从 OpenRouter 返回 JSON 中抽出 base64 图片数据。
    Nano Banana 正常返回形如：
        choices[0].message.images[0].image_url.url = "data:image/png;base64,xxx"
    少数情况下会把 image 塞到 content 的数据块里，这里都兼容一下。
    """
    try:
        choices = resp_json.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}

        # 1) 标准路径: message.images[].image_url.url
        images = message.get("images") or []
        for img in images:
            url = (img or {}).get("image_url", {}).get("url", "")
            if isinstance(url, str) and url.startswith("data:image"):
                return url.split(",", 1)[1]

        # 2) 兼容: content 为结构化数组，其中含 image_url 块
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                url = (block.get("image_url") or {}).get("url", "")
                if isinstance(url, str) and url.startswith("data:image"):
                    return url.split(",", 1)[1]
    except Exception:
        pass
    return None


def generate_image(prompt: str, output_path: str, retry: int = IMAGE_RETRY,
                   api_key: str = None, model: str = None) -> Optional[str]:
    """
    生成图片并保存到 output_path。成功返回路径，失败返回 None。
    失败不抛异常，只打印日志 —— 调用方决定降级策略。

    api_key / model 可选，缺省回落到 config.py（保证命令行旧流程不受影响）。
    """
    key = api_key or OPENROUTER_API_KEY
    mdl = model or MODEL_IMAGE_GEN
    if not key:
        print("     ❌ OPENROUTER_API_KEY 未配置")
        return None

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "SEO Blog Generator - Image",
    }

    payload = {
        "model": mdl,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }

    last_error = ""
    total_attempts = retry + 1
    for attempt in range(1, total_attempts + 1):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=180)
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                print(f"     ⚠️  图片生成第 {attempt}/{total_attempts} 次失败：{last_error}")
                time.sleep(2)
                continue

            data = resp.json()
            # 峰值内存关键点：此刻 resp.text（几 MB base64 JSON）+ 解析后的 dict
            # + b64 字符串 + 解码 bytes 会同时存在。尽早释放不再需要的引用。
            resp.close()
            del resp
            b64 = _extract_image_b64(data)
            if not b64:
                # 打印 finish_reason / error 便于排查
                choices = data.get("choices") or [{}]
                finish = choices[0].get("finish_reason", "unknown")
                err = data.get("error", {}).get("message", "")
                del data
                last_error = f"响应中未找到图片 | finish_reason={finish} | err={err}"
                print(f"     ⚠️  图片生成第 {attempt}/{total_attempts} 次失败：{last_error}")
                time.sleep(2)
                continue

            del data  # 释放整个响应 dict，只留 b64 字符串
            img_bytes = base64.b64decode(b64)
            del b64
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(img_bytes)
            del img_bytes
            return output_path

        except Exception as e:
            last_error = str(e)
            print(f"     ⚠️  图片生成第 {attempt}/{total_attempts} 次异常：{last_error}")
            time.sleep(2)

    print(f"     ❌ 图片生成彻底失败：{last_error}")
    return None
