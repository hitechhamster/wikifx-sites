"""
Prompt 模板 —— 4 个环节的默认 prompt，抽成可编辑模板。

- 用 {token} 占位符，运行时由 render() 做「纯文本替换」（不走 str.format，
  因此用户在自定义 prompt 里写任意 { } 花括号都不会报错）。
- workflow.py 里：站点若提供了自定义 prompt 就用自定义的，否则用这里的默认。
- 默认模板的文字与原来 workflow.py 里的 f-string 逐字一致，只是把
  复杂表达式（如 int(wordcounts*0.9)、specific if ... else）预先算好再塞进来。
"""

# 每个环节可用的占位符（给前端提示用）
PROMPT_TOKENS = {
    "outline": ["language", "topic", "main_keyword", "secondary_keyword", "wordcounts",
                "item_count", "per_item_words", "specific_display",
                "main_search_results", "secondary_search_results"],
    "article": ["language", "main_keyword", "secondary_keyword", "wordcounts",
                "wc_low", "wc_high", "outline", "specific_display",
                "main_search_results", "secondary_search_results"],
    "seo": ["language", "content_head", "main_keyword"],
    "image": ["main_keyword", "article_excerpt"],
}

PROMPT_LABELS = {
    "outline": "大纲 prompt",
    "article": "正文 prompt",
    "seo": "SEO 元数据 prompt",
    "image": "图片 prompt",
}


def render(template: str, mapping: dict) -> str:
    """把 {key} 纯文本替换成 mapping[key]。对花括号安全，不会因用户乱写 {} 报错。"""
    out = template or ""
    for k, v in mapping.items():
        out = out.replace("{" + k + "}", "" if v is None else str(v))
    return out


# ============================================================
# 默认模板
# ============================================================

DEFAULT_OUTLINE = """# Task: Create an in-depth article outline in {language}

## Topic parameters
- Topic: {topic}
- Main keyword: {main_keyword}
- Secondary keyword: {secondary_keyword}
- Target word count: {wordcounts}
- Language: {language}
- If you choose listicle — number of main items: {item_count}, words per item: ~{per_item_words}

## Special requirement
{specific_display}
(If not empty, treat as highest priority. If the special requirement mentions a brand/URL for traffic, place 3 natural CTA hooks in the outline pointing to it.)

## Source material (for facts only — do not copy wording)
{main_search_results}

{secondary_search_results}

---

## Step 1 — Pick the right format

Judge which format the topic actually demands:

- **Listicle / comparison** — when the topic naturally contains multiple parallel items to rank, compare, or choose between (e.g. "best forex brokers", "top trading platforms", "ways to deposit on X").
- **Guide / how-to / explainer** — when the topic is a single concept, process, procedure, or definition (e.g. "how to withdraw from Exness", "what is Forex", "minimum deposit explained", "Exness fees breakdown").
- **Hybrid** — a guide that includes one embedded comparison block.

⚠️ Do NOT force a listicle if the topic does not naturally need one. Choose the format that genuinely fits the topic. Most "how to / what is / explained" topics are guides, not listicles.

## Step 2 — Build the outline using the chosen format

### H1 Title
- Must include the main keyword naturally
- Click-worthy but not clickbait
- Format must match the chosen structure:
  - Listicle: "X Best...", "X Ways...", "Top X..." with a specific number
  - Guide: "How to...", "The Complete Guide to...", "Everything You Need to Know About...", "[Topic] Explained", "[Topic]: What You Need to Know"
  - Hybrid: pick whichever reads stronger
- Use a number ONLY if listicle is the right format. Do NOT invent a number for non-listicle topics.
- ⚠️ DO NOT include any year (no 2024, 2025, 2026, etc.) anywhere in the title.

### Opening block (≈150 words)
1. One sentence: who this article is for (be specific about audience)
2. Two sentences: what problem/question it solves
3. Not a question, not an abstract intro — go straight to point. No "in today's world" filler.

### Quick Answer / TL;DR box (≈100 words)
Tight bullet list giving the answer FAST, before the deep dive.
- If listicle: "If you want [outcome A] → [Item #X]" pattern, 3-4 bullets
- If guide: 3-4 key takeaways, or a numbered quick-start
- Either way: must be concrete, no fluff

### "What We Looked For" section (≈120 words) — listicle / hybrid only
4-5 evaluation criteria as bullets, each: criterion name + one-line rationale of why it matters. SKIP this section entirely for pure guides.

### Main body — depends on chosen format

**If LISTICLE ({item_count} items, ~{per_item_words} words each):**

Each H2 follows this exact structure:
```
## [Number]. [Item Name] — [One-line positioning]

[3-4 short paragraphs describing what it is, why it stands out, and concrete usage context]

**Best for:** [specific type of user/situation]
**Skip if:** [specific disqualifier]

Key points:
- [Point with a concrete number or detail]
- [Point with a concrete number or detail]
- [Point with a concrete number or detail]
- [Point with a concrete number or detail]
```
Plan each item to include: one concrete use case, at least 2 specific numbers (price/spec/time/percentage), and one pitfall or limitation.

**If GUIDE / HOW-TO (5-8 H2 sections):**

Plan H2 sections in logical order, e.g.:
- Definition / context
- Mechanics / how it works
- Step-by-step (if procedural)
- Practical specifics (numbers, requirements, fees, timelines)
- Edge cases / variations
- Pitfalls / common mistakes

Per H2 section: 3-5 short paragraphs, ≥2 concrete numbers (price, %, time, spec, etc.), bullet/numbered lists wherever they fit, optional "Watch out for:" callout for pitfalls.

H2 headings must be noun phrases or imperatives — NEVER questions.

**If HYBRID:**

Mostly guide-style H2s, plus ONE comparison block (a numbered mini-list with 3-5 items, OR an inline comparison table) inside the body where it fits naturally.

### Comparison table section (≈120 words + table) — REQUIRED for every format
Even guide articles compare something — account types, fee tiers, plan options, deposit methods, scenarios, etc.
- One intro sentence
- A markdown table with 4-5 columns and clear headers, all relevant items / options / tiers / methods as rows
- One sentence after the table summarizing the pattern

### Closing — "How to Choose / Bottom Line" (≈120 words)
Decision tree style:
- If [condition A] → pick [option X]
- If [condition B] → pick [option Y]
- If still unsure → default recommendation with reason

## Writing style notes for the writer
- Second person "You"
- Imperative short sentences
- Explain any technical term in one short parenthetical
- Verbs over adjectives
- Every H2 must contain at least one concrete number

## What NOT to do
- Do NOT use question-form H2 headings
- Do NOT use bolded "golden answer" sentences under headings
- Do NOT write an FAQ section
- Do NOT include external links unless special requirement says so
- ⚠️ Do NOT mention or include ANY year (2024 / 2025 / 2026 etc.) anywhere — title, body, table, examples, quotes. If the source material references a year, rephrase the fact without the year (e.g. "a recent regulation", "currently", "newly introduced").
- Do NOT add meta description or meta title (handled separately)

---

Output the complete outline in {language}, structured according to the format you chose. Include estimated word count in brackets after each section header — but NEVER after the H1 title; the H1 title must stay clean with no word-count bracket or any trailing annotation. Do NOT output any "Format: ..." declaration line — just produce the outline directly. No preamble."""


DEFAULT_ARTICLE = """# Task: Write the full article in {language}

## Parameters
- Main keyword: {main_keyword}
- Secondary keyword: {secondary_keyword}
- Target word count: {wordcounts} (range: {wc_low}–{wc_high})
- Language: {language}

## Outline to follow (do not deviate from structure)
{outline}

## Source material (for facts only, do not copy wording)
{main_search_results}

{secondary_search_results}

## Special requirement
{specific_display}
(If not empty, treat as highest priority.)

---

## ⚠️ MANDATORY STYLE RULES

### Voice
- Second person: address the reader as "You"
- Conversational but efficient — no filler
- Short sentences dominate (most ≤ 18 words)
- Use imperative verbs: "Check", "Skip", "Test", "Compare"
- Explain any jargon in one short parenthetical the first time

### Bold usage (strictly limited — no inline bold highlights)
- Do NOT bold any action verbs, numbers, or phrases inside sentences.
- Do NOT use any **...** markdown inside paragraphs or bullet points.
- The ONLY permitted bold text is structural labels at the start of their own lines exactly as the outline specifies (e.g. "**Best for:**" / "**Skip if:**" for listicle items, or other bold labels the outline introduces). Nothing else may be bolded.
- Do NOT bold entire sentences.
- Do NOT use bolded "golden answer" style under headings.

### Formatting rules
- H1: exactly one, matches the outline
- H2 sections: follow the outline EXACTLY — whether numbered listicle items "## N. [Name] — [Positioning]" or descriptive guide sections "## [Section Name]"
- No H2 in question form
- Bullet/numbered lists: use them densely wherever the outline calls for them
- One markdown comparison table in the comparison section, with clear column headers (this is mandatory regardless of format)

### What to include per H2

**If the H2 is a numbered listicle item:**
- 3-4 short paragraphs of description (concrete, each with at least one number)
- "Best for:" and "Skip if:" lines
- 4-5 "Key points:" bullets, each containing a specific number, spec, price, time, or comparison
- Optional "Watch out for:" line for a common pitfall

**If the H2 is a guide / how-to section:**
- 3-5 short paragraphs covering the section's subject
- At least 2 concrete numbers, prices, percentages, timeframes, or specs per section
- Use bullet/numbered lists liberally inside the section wherever they fit
- Optional "Watch out for:" line for a common pitfall

### Global requirements
- At least 20 concrete numbers total across the whole article (prices, fees, percentages, durations, spec values, ratios, ranks, etc.)
- One markdown comparison table covering the relevant items / options / tiers / methods (mandatory, regardless of format)
- ALL sections from the outline must be present — opening, Quick Answer, body H2s, comparison table, closing
- Article must reach the target word count ({wordcounts} words minimum). If a section is thin, expand it with more concrete examples, numbers, or scenarios — never with filler or restated points.

### Forbidden
- Question-form H2 headings
- Bolded first-sentence "answer boxes" under headings
- FAQ section
- External links (unless special requirement says otherwise)
- Emojis
- AI-telltale phrases: "in today's fast-paced world", "in conclusion", "it's important to note"
- ⚠️ ANY year mention (2024 / 2025 / 2026 etc.) — not in the title, not in body text, not in the table, not in examples or quotes. If the source material mentions a year, rephrase the fact without it (e.g. "a recent change", "currently", "newly introduced rules").

---

Output the complete article in {language} in markdown format. Start directly with the H1. No preamble or postamble."""


DEFAULT_SEO = """Generate SEO title and description in {language} based on this article.

Article (first 1000 chars): {content_head}

Rules:
- Title: under 70 characters, click-worthy, must contain "{main_keyword}". Do NOT include any year (no 2024, 2025, 2026, etc.).
- Description: under 170 characters, accurately describes the article, must contain "{main_keyword}". Do NOT include any year.

Output ONLY in this exact format (no other text):
Title: [your title]
Description: [your description]"""


DEFAULT_IMAGE = """You are a prompt engineer for an image generation model (Gemini 2.5 Flash Image, aka Nano Banana).

Based on this article about "{main_keyword}", write ONE English image prompt.

The image will be used for TWO purposes at once:
- WordPress featured image (hero/cover at the top of the post)
- Inline image placed right after the first H2 of the article body

So it must:
- Be visually striking enough to function as a hero/cover
- Represent the overall theme of "{main_keyword}", not just one narrow sub-topic
- Have a wide 16:9 feel with clean composition
- Be photographic OR clean editorial illustration
- Contain NO text, NO letters, NO numbers, NO watermarks inside the image
- Include style keywords like "clean editorial photography", "soft natural lighting", "minimal composition", "shallow depth of field"

Article excerpt (first 1500 chars):
{article_excerpt}

Output ONLY the image prompt itself as a single paragraph (30-60 words). No label, no prefix, no quotes, no markdown."""


DEFAULTS = {
    "outline": DEFAULT_OUTLINE,
    "article": DEFAULT_ARTICLE,
    "seo": DEFAULT_SEO,
    "image": DEFAULT_IMAGE,
}
