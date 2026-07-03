"""
WordPress 发文认证诊断脚本
用法: python wp_diag.py

它会用与 main.py / wordpress_client.py 完全相同的方式（读 config、
requests + HTTPBasicAuth）发一篇 draft 草稿，并把关键信息打印出来：
- requests 实际使用的代理
- 有没有发生跳转（resp.history）
- 最终请求是否真的带上了 Authorization 头
- 服务器返回的状态码和响应体
这样就能定位「curl 能发、Python 不能发」到底卡在哪。
"""
import os
import requests
from requests.auth import HTTPBasicAuth

from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD

base_url = WP_URL.rstrip("/") + "/wp-json/wp/v2"
auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD.replace(" ", ""))

print("=" * 60)
print("配置检查")
print("=" * 60)
print(f"WP_URL          : {WP_URL!r}")
print(f"目标 base_url   : {base_url}")
print(f"用户名          : {WP_USERNAME!r}")
print(f"应用密码长度    : {len(WP_APP_PASSWORD.replace(' ', ''))} 字符（去空格后）")
print()

print("=" * 60)
print("代理环境（requests 会读这些环境变量）")
print("=" * 60)
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "NO_PROXY"]:
    print(f"  {k} = {os.environ.get(k)}")
print(f"  requests 自动探测到的代理: {requests.utils.get_environ_proxies(base_url)}")
print()

payload = {
    "title": "python diag test",
    "content": "<p>diag</p>",
    "status": "draft",
}

print("=" * 60)
print("发起 POST（和 create_post 一样的调用）")
print("=" * 60)
try:
    resp = requests.post(
        f"{base_url}/posts",
        json=payload,
        auth=auth,
        timeout=60,
    )
    print(f"最终状态码      : {resp.status_code}")
    print(f"最终 URL        : {resp.url}")
    print(f"跳转历史        : {[ (h.status_code, h.headers.get('Location')) for h in resp.history ] or '无跳转'}")
    print(f"实际发出的请求头 Authorization 是否存在: "
          f"{'是' if 'Authorization' in resp.request.headers else '否 —— 认证头丢了!'}")
    # 安全起见只显示前 12 个字符
    ah = resp.request.headers.get("Authorization", "")
    print(f"  Authorization 前缀: {ah[:12]}...")
    print(f"响应 Server 头  : {resp.headers.get('Server')}")
    print(f"响应体(前 400 字): {resp.text[:400]}")
except Exception as e:
    print(f"请求异常: {e}")

print()
print("=" * 60)
print("结果怎么看：")
print(" - 状态码 201 → Python 这条路也能发文，说明上次是偶发/已恢复，直接重跑 main.py")
print(" - 跳转历史里有 Location 且认证头变'否' → 跳转剥掉了认证，把 WP_URL 改成 Location 的域名")
print(" - 认证头='否'但没跳转 → 代理/CDN 吃掉了 Authorization，需走代理或换直连源站")
print(" - 401 且认证头='是' → 认证头发出去了但 WP 不认，多半是 CDN 改写/安全插件，需放行 REST 写入")
print("=" * 60)