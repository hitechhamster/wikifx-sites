# SEO Blog Generator - Listicle + Nano Banana + WordPress

批量生成 2000-3000 字清单风格 SEO 长文,自动配图,自动发布到 WordPress 草稿。

> **两种用法**:
> - **命令行版**(原版):`python main.py`,读 `config.py` + `input.xlsx`,单站。
> - **Web 后台版**(新增):多站可视化管理,网页上传 Excel、编辑每个站的配置、一键运行看进度。见下方「Web 后台」。

---

## Web 后台(多站群管理)

给公司同事用的可视化后台:每人负责一个站的自然流量,在网页里管理自己站群的内容生产。

### 能自定义什么(每个站一套,存数据库)
- WordPress 连接(URL / 用户名 / 应用密码)
- Tavily / OpenRouter API Key
- 语言、各环节模型(大纲/正文/SEO/图片)
- 字数上下限、正文最低字数与重试次数
- 发布状态(直接发布 / 草稿)、每次运行条数、限流间隔
- 固定分类、默认标签、是否配图
- 统一的品牌 / CTA 特殊要求(追加到每篇)

### 本地启动
```bash
pip install -r requirements.txt
run_web.bat                      # 或: python -m uvicorn webapp.app:app --reload
```
浏览器打开 http://127.0.0.1:8000 → 新建站点 → 填配置 → 上传关键词 Excel → 点「开始生成」看实时进度。

关键词 Excel 表头(与命令行版一致):`main_keyword`(必填)、`secondary_keyword`、`topic`、`wordcounts`、`specific`、`category`、`tags`。

### 部署到 Render($7 常驻)
仓库里已带 `render.yaml`(含 1GB 持久化磁盘,重新部署不丢数据)。
Render 后台 → New + → Blueprint → 选中本仓库即可。数据(SQLite + 生成文件)存在挂载盘 `/var/data`。

**环境变量(只需两个,所有站点共用):**
- `TAVILY_API_KEY`
- `OPENROUTER_API_KEY`

站点配置里的 Tavily / OpenRouter 留空时,运行时自动回落到这两个环境变量。
**各站的 WordPress 应用密码不放环境变量,直接在网页「站点配置」里逐站填。**

部署后:在网页「新建站点」建站并填 WP 密码,或跑 `seed_vietnam.py` / `seed_hawk1.py` 先建好站再去页面补 WP 密码。

> ⚠️ 源码不含明文密钥;`data/app.db`(存各站真实配置)已被 `.gitignore` 排除,不进仓库。

---


## 目录结构

```
seo_blog_generator/
├── config.py              # API Key、WP 账号、模型、字数等所有配置
├── main.py                # 主入口
├── workflow.py            # 搜索 + 大纲 + 正文 + SEO + 图片 prompt
├── image_generator.py     # Nano Banana 生图
├── wordpress_client.py    # WP REST API 封装
├── requirements.txt
└── output/                # 运行后生成
    ├── articles/*.docx    # Word 文档
    ├── images/*.png       # 生成的图片
    └── results_<时间戳>.xlsx
```

## 安装

```bash
pip install -r requirements.txt
```

## 配置

打开 `config.py`,在顶部填写:

1. **API Key**
   - `TAVILY_API_KEY` - Tavily 搜索
   - `OPENROUTER_API_KEY` - OpenRouter

2. **WordPress 账号**
   - `WP_URL` - 站点首页,末尾不带 `/`,例如 `https://example.com`
   - `WP_USERNAME` - WP 后台用户名
   - `WP_APP_PASSWORD` - Application Password(WP 后台「用户 → 个人资料 → Application Passwords」生成,**不是登录密码**)

3. 其他参数按需改,默认值可以直接用。

## 输入 Excel 列

| 列名 | 必填 | 说明 |
|---|---|---|
| `main_keyword` | ✅ | 主关键词 |
| `secondary_keyword` | ✅ | 次关键词 |
| `topic` | ✅ | 主题描述 |
| `wordcounts` | ✅ | 目标字数(会被夹到 2000-3000) |
| `specific` | 可选 | 特殊要求,例如"面向新手"、"含 xxx 品牌 CTA" |
| `category` | 可选 | WP 分类,多个逗号分隔,例如 `AI Tools, Productivity` |
| `tags` | 可选 | WP 标签,多个逗号分隔 |

分类/标签如果在 WP 里不存在会**自动创建**(要求账号有该权限)。

## 运行

```bash
# 默认读 ./input.xlsx,发到 WordPress 草稿
python main.py

# 指定输入
python main.py --input data/keywords.xlsx --language English

# 只本地生成,不发 WP
python main.py --no-wp
```

## 工作流

每条记录会按顺序跑 9 步:

1. Tavily 搜主关键词
2. Tavily 搜次关键词
3. Gemini Pro 生成清单大纲
4. Gemini Pro 撰写正文(2000-3000 字)
5. Gemini Flash Lite 生成 SEO title + description
6. Gemini Flash Lite 生成 1 个英文图像 prompt
7. Nano Banana 生成 1 张图片
8. 本地保存 Word 文档
9. 上传图片到 WP 媒体库 → Markdown 转 HTML 并在第一个 H2 后插入这张图 → 创建文章(`status=draft`,同一张图作为 `featured_media`)

## 图片失败处理

Nano Banana 偶尔会返回空图。失败时:

- 草稿不会设置 `featured_media`
- 正文里也不会插入图片
- **但文章本身会正常发布(纯文字草稿)**,不会因为图片问题中断

图片默认会试 2 次(配置项 `IMAGE_RETRY`)。

## 常见坑

- **WP Application Password 不是登录密码**。生成方式:WP 后台 → 用户 → 个人资料 → 滚动到 "Application Passwords" → 输入名称 → 生成。
- **WP 站点必须开启 REST API**。大部分 WP 默认开启,但某些安全插件会关掉。
- **图片模型有地区/额度限制**。如果 Nano Banana 一直返回空响应,检查 OpenRouter 后台该模型的可用性和余额。
- **分类/标签自动创建需要权限**。只有 Editor/Admin 角色可以创建新分类。Author/Contributor 会失败,但文章本身还会发出去(只是不带分类)。
- **模型名如果 OpenRouter 下线某个版本**,在 `config.py` 里改 `MODEL_OUTLINE_AND_ARTICLE` 即可,常用替代:`google/gemini-2.5-pro`。
