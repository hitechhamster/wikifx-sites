"""
SEO 文章核心工作流 (auto-format 版)

相对原 Colab 版有两处行为调整：
  1) 让 LLM 先判断主题适合 Listicle / Guide / Hybrid 中的哪种结构,
     不再强制清单体 —— 不再强制标题里出现数字, 不再强制 X 项 numbered H2。
  2) 全面去除年份提示, 标题与正文都不再硬塞 2025/2026 等。

数据密度、对比表格、决策树收尾、写作风格规则全部保留。

接口 (函数签名 + 返回结构) 与原版完全一致, main.py / config.py 不需要改动。

注：屏幕输出全部为英文，避免 cmd 中文乱码。
"""
from typing import Dict

import requests
import tavily

from config import (
    TAVILY_API_KEY,
    OPENROUTER_API_KEY,
    MODEL_OUTLINE_AND_ARTICLE,
    MODEL_SEO_META,
    MODEL_IMAGE_PROMPT,
)
import prompts as _prompts


class ListicleWorkflow:
    def __init__(
        self,
        tavily_api_key: str = None,
        openrouter_api_key: str = None,
        model_outline: str = None,
        model_seo: str = None,
        model_image_prompt: str = None,
        prompt_outline: str = None,
        prompt_article: str = None,
        prompt_seo: str = None,
        prompt_image: str = None,
    ):
        # 参数优先，缺省回落到 config.py（保证命令行旧流程不受影响）
        self.tavily_api_key = tavily_api_key or TAVILY_API_KEY
        self.openrouter_api_key = openrouter_api_key or OPENROUTER_API_KEY
        self.model_outline = model_outline or MODEL_OUTLINE_AND_ARTICLE
        self.model_seo = model_seo or MODEL_SEO_META
        self.model_image_prompt = model_image_prompt or MODEL_IMAGE_PROMPT
        # 自定义 prompt 模板（非空则覆盖默认，否则用 prompts.py 里的默认）
        self.prompt_outline = (prompt_outline or "").strip() or _prompts.DEFAULT_OUTLINE
        self.prompt_article = (prompt_article or "").strip() or _prompts.DEFAULT_ARTICLE
        self.prompt_seo = (prompt_seo or "").strip() or _prompts.DEFAULT_SEO
        self.prompt_image = (prompt_image or "").strip() or _prompts.DEFAULT_IMAGE
        self.openrouter_base_url = "https://openrouter.ai/api/v1"
        # OpenRouter 花费累计（USD）
        self.row_cost = 0.0      # 当前这篇文章累计花费，每篇开头由 main.py 重置
        self.total_cost = 0.0    # 整个 run 的累计花费

    # ----------- Tavily 搜索 -----------
    def tavily_search(self, query: str, max_results: int = 5) -> str:
        try:
            client = tavily.TavilyClient(api_key=self.tavily_api_key)
            response = client.search(
                query=query,
                search_depth="basic",
                topic="general",
                max_results=max_results,
                include_raw_content=False
            )
            formatted_results = []
            for result in response.get('results', []):
                formatted_results.append(
                    f"Title: {result.get('title', '')}\n"
                    f"URL: {result.get('url', '')}\n"
                    f"Content: {result.get('content', '')}\n---"
                )
            return "\n".join(formatted_results)
        except Exception as e:
            return f"Tavily search error: {e}"

    # ----------- LLM 调用 -----------
    def call_llm(self, model: str, messages: list, temperature: float = 0.7,
                 max_tokens: int = 4000) -> str:
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "SEO Blog Generator - Version A"
        }
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 限制 reasoning 预算,防止 thinking model（gemini-3.1-pro-preview / 2.5-pro
            # 等都是 thinking model）陷入 CoT 死循环导致上游 idle timeout 502。
            # 2000 tokens 足够规划一篇 listicle 大纲 / 长文,撞到上限会被强制吐 output。
            # SEO 元数据 / 图片 prompt 这类短任务也透明兼容（用不到这么多）。
            "reasoning": {"max_tokens": 2000},
        }
        try:
            response = requests.post(f"{self.openrouter_base_url}/chat/completions",
                                     headers=headers, json=data, timeout=300)
            response.raise_for_status()
            result = response.json()

            # OpenRouter 在 usage.cost 里返回这次调用的实际花费（USD，已自动包含，无需额外参数）。
            # 即使后面 content 为空也照样计费，所以在这里就先累加。
            try:
                _cost = (result.get("usage") or {}).get("cost")
                if _cost is not None:
                    self.row_cost += float(_cost)
                    self.total_cost += float(_cost)
            except Exception:
                pass

            if 'choices' not in result or not result['choices']:
                err_msg = result.get('error', {}).get('message', str(result)[:200])
                return f"LLM call error: no choices returned | {err_msg}"

            message = result['choices'][0].get('message', {})
            content = message.get('content')

            if content is None or content == "":
                finish_reason = result['choices'][0].get('finish_reason', 'unknown')
                refusal = message.get('refusal', '')
                try:
                    import json as _json
                    print(f"\n     [DEBUG] empty content | model={model} | max_tokens={max_tokens}")
                    prompt_preview = ""
                    try:
                        prompt_preview = (messages[-1].get("content") or "")[:300]
                    except Exception:
                        pass
                    usage = result.get("usage", {})
                    print(f"     [DEBUG] usage: {usage}")
                    print(f"     [DEBUG] last 300 chars of prompt: {prompt_preview}...")
                    print(f"     [DEBUG] full OpenRouter response:")
                    print(_json.dumps(result, indent=2, ensure_ascii=False))
                    print()
                except Exception as _e:
                    print(f"     [DEBUG] dump failed: {_e}; raw={str(result)[:800]}")
                return f"LLM call error: empty content | finish_reason={finish_reason} | refusal={refusal}"

            return content
        except Exception as e:
            return f"LLM call error: {e}"

    # ----------- Step 1: 大纲生成 (auto-format) -----------
    def generate_outline(self, main_keyword: str, secondary_keyword: str,
                         topic: str, wordcounts: int, specific: str,
                         main_search_results: str, secondary_search_results: str,
                         language: str) -> str:

        if wordcounts < 3000:
            item_count = "6-7"
            per_item_words = 280
        elif wordcounts < 4000:
            item_count = "7-9"
            per_item_words = 320
        else:
            item_count = "9-11"
            per_item_words = 360

        outline_prompt = _prompts.render(self.prompt_outline, {
            "language": language,
            "topic": topic,
            "main_keyword": main_keyword,
            "secondary_keyword": secondary_keyword,
            "wordcounts": wordcounts,
            "item_count": item_count,
            "per_item_words": per_item_words,
            "specific_display": specific if specific else "(none)",
            "main_search_results": main_search_results,
            "secondary_search_results": secondary_search_results,
        })

        messages = [{"role": "user", "content": outline_prompt}]
        return self.call_llm(
            model=self.model_outline,
            messages=messages,
            temperature=0.6,
            max_tokens=4000
        )

    # ----------- Step 2: 正文生成 -----------
    def write_article(self, main_keyword: str, secondary_keyword: str,
                      topic: str, wordcounts: int, specific: str,
                      outline: str, main_search_results: str,
                      secondary_search_results: str, language: str) -> str:

        writing_prompt = _prompts.render(self.prompt_article, {
            "language": language,
            "main_keyword": main_keyword,
            "secondary_keyword": secondary_keyword,
            "wordcounts": wordcounts,
            "wc_low": int(wordcounts * 0.9),
            "wc_high": int(wordcounts * 1.3),
            "outline": outline,
            "main_search_results": main_search_results,
            "secondary_search_results": secondary_search_results,
            "specific_display": specific if specific else "(none)",
        })

        messages = [{"role": "user", "content": writing_prompt}]
        return self.call_llm(
            model=self.model_outline,
            messages=messages,
            temperature=0.75,
            max_tokens=20000
        )

    # ----------- Step 3: SEO 元数据 -----------
    def generate_seo_meta(self, content: str, main_keyword: str, language: str) -> Dict[str, str]:
        if not content or not isinstance(content, str):
            return {
                'seo_title': f"{main_keyword} - {language} Guide",
                'seo_description': f"Comprehensive guide about {main_keyword}"
            }

        seo_prompt = _prompts.render(self.prompt_seo, {
            "language": language,
            "content_head": content[:1000],
            "main_keyword": main_keyword,
        })

        messages = [{"role": "user", "content": seo_prompt}]
        response = self.call_llm(
            model=self.model_seo,
            messages=messages,
            temperature=0.6,
            max_tokens=300
        )

        seo_data = {}
        try:
            for line in (response or "").strip().split('\n'):
                if line.startswith('Title:'):
                    seo_data['seo_title'] = line.replace('Title:', '').strip().strip('"')
                elif line.startswith('Description:'):
                    seo_data['seo_description'] = line.replace('Description:', '').strip().strip('"')

            if 'seo_title' not in seo_data:
                seo_data['seo_title'] = f"{main_keyword} - {language} Guide"
            if 'seo_description' not in seo_data:
                seo_data['seo_description'] = f"Comprehensive guide about {main_keyword}"
        except Exception as e:
            print(f"     [WARN] SEO parsing failed: {e}")
            seo_data = {
                'seo_title': f"{main_keyword} - {language} Guide",
                'seo_description': f"Comprehensive guide about {main_keyword}"
            }
        return seo_data

    # ----------- Step 4: 图片 prompt -----------
    def generate_image_prompt(self, article_content: str, main_keyword: str) -> str:
        prompt = _prompts.render(self.prompt_image, {
            "main_keyword": main_keyword,
            "article_excerpt": article_content[:1500],
        })
        resp = self.call_llm(
            model=self.model_image_prompt,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500
        )

        fallback = (
            f"A clean editorial photograph representing the concept of {main_keyword}, "
            f"soft natural lighting, minimal composition, shallow depth of field, "
            f"no text in the image, professional blog header style, 16:9 composition."
        )

        if not resp or resp.startswith("LLM call error"):
            return fallback

        cleaned = resp.strip().strip('"').strip("'").strip()

        first_line = cleaned.split("\n", 1)[0]
        if ":" in first_line and len(first_line.split(":", 1)[0]) < 20:
            cleaned = cleaned.split(":", 1)[1].strip()

        return cleaned or fallback