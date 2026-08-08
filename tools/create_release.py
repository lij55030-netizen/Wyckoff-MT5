"""创建 GitHub Release v3.1 并上传资产（Setup 安装包 + 绿色版 zip）。

安全：TOKEN 从环境变量 GITHUB_TOKEN 读取，不再硬编码进源码。
用法：set GITHUB_TOKEN=ghp_xxx && python tools/create_release.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")  # 控制台 UTF-8，避免中文输出 GBK 报错

TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = "lij55030-netizen"
REPO = "Wyckoff-MT5"  # 2026-08 仓库已迁移（原 Wyckoff-MT5-Workbuddy 重定向到本地址）
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
UPLOAD_BASE = f"https://uploads.github.com/repos/{OWNER}/{REPO}"  # 资产上传专用域名
HDR = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

if not TOKEN:
    print("❌ 未设置 GITHUB_TOKEN 环境变量（python tools/create_release.py 前先 set）")
    raise SystemExit(1)

BODY = """## 🎉 WKF 威科夫交易智能体 V3.1 一键安装版发布

### 📦 下载指引（点击文件名下载）
- **WKF_V3.1_Setup.exe** — 一键安装版（推荐）：自定义安装路径 / 桌面快捷方式 / 卸载程序
- **WKF_V3.1_Portable.zip** — 绿色免安装版：解压后双击 `WKF.exe` 即用
- **WKF_V3.0_Readme.txt** — 使用说明（MT5 连接 / 数据源切换 / 功能简介）

### ✨ 功能更新
- **分析进度条**：标签栏下方分段驱动（数据加载 0-25% / 快照生成 25-50% /
  AI 诊断推理 50-80% / 决策组装 80-100%），分析完成自动归零
- **AI 流式输出**：DeepSeek 边运算边实时输出思考过程到【诊断】页，全程可视化
- **铃铛提示开关**：分析结束、决策生成完成时播放提示音；开启=青绿高亮 / 关闭=灰色
- **内容分区**：AI 完整思考/盘面拆解 →【诊断】页；精简结论/点位/风控/概率 →【决策】页
- **收线确认**：持续跟踪等 K 线收盘定型后再分析，只用已收盘数据
- **K 线时长 7 个工作日**（168h）；**品种精简 5 个**（黄金/纳指/标普500/白银/比特币）
- **纯 K 线模式**：一键隐藏全部技术指标
- **AI 模型设置**：API Key 显示/隐藏 + 模型可编辑下拉

### 🛠 UI 修复
- 修复 Qt 日志框黑底黑字 → 深色背景 + 浅灰白文字 + 彩色分级日志
- 图表画布统一纯色 #082C32 深墨青绿
- 十字光标价格 + K 线 OHLC 显示、鼠标追踪修复
- 菜单栏 / 顶部文字深色主题适配

### 📐 布局优化
- 移除 RSI 副图，K 线主图自动填满
- 分割防卡死：最小高度/宽度保护，拖拽把手常驻
- 垂直拖拽优化：纯色简约分割条，降低重绘开销
- 侧边栏可拖拽调整宽度，按钮间距自然
- 分析日志面板：带圈序号 / 10 条上限 / 保存按钮 / 多空红绿加粗

> 仅对接 MT5 实盘 + YFinance 公开数据；配置保存在安装目录 _internal/config/。
> 以上仅作分析参考，不构成投资建议。"""


def api(method, url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=HDR, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


# 1. 创建 Release（若已存在则复用）
try:
    rel = api("POST", f"{BASE}/releases", {
        "tag_name": "v3.1",
        "name": "WKF 威科夫交易智能体 V3.1 一键安装版",
        "body": BODY,
        "draft": False,
        "prerelease": False,
    })
    print("✅ Release 创建成功:", rel["html_url"])
except Exception as e:
    rels = api("GET", f"{BASE}/releases?per_page=10")
    rel = next((r for r in rels if r.get("tag_name") == "v3.1"), None)
    if not rel:
        print("❌ 创建失败:", str(e)[:200])
        raise SystemExit(1)
    print("ℹ️ Release 已存在，复用:", rel["html_url"])
    try:
        rel = api("PATCH", f"{BASE}/releases/{rel['id']}", {
            "name": "WKF 威科夫交易智能体 V3.1 一键安装版",
            "body": BODY,
        })
        print("✅ Release 标题与说明已更新")
    except Exception as e:
        print(f"⚠️ 更新标题失败: {str(e)[:120]}")

# 2. 上传资产（本地路径, 上传显示名, 内容类型）
# 说明：当前网络通道对非 ASCII 文件名会归一化为 default.txt，
# 资产名保持 ASCII 语义（Setup/Portable/Readme），中文说明在 Release 正文。
assets = [
    ("installer/WKF_V3.1_Setup.exe", "WKF_V3.1_Setup.exe", "application/octet-stream"),
    ("installer/WKF_V3.1_绿色免安装版.zip", "WKF_V3.1_Portable.zip", "application/zip"),
    ("绿色免安装版说明.txt", "WKF_V3.0_Readme.txt", "text/plain; charset=utf-8"),
]
rel_id = rel["id"]

# 2.1 清理同 Release 下所有旧资产（含 default.txt / 截断名等垃圾）
for asset in rel.get("assets", []):
    old = asset["name"]
    del_url = f"{BASE}/releases/assets/{asset['id']}"
    del_req = urllib.request.Request(del_url, headers=HDR, method="DELETE")
    try:
        with urllib.request.urlopen(del_req, timeout=60):
            print(f"🗑️ 已删除旧资产: {old}")
    except Exception as e:
        print(f"⚠️ 删除旧资产失败 {old}: {str(e)[:120]}")

# 2.2 上传资产
for path, name, ctype in assets:
    if not os.path.exists(path):
        print(f"⚠️ 资产缺失，跳过: {path}")
        continue
    url = f"{UPLOAD_BASE}/releases/{rel_id}/assets?name={urllib.parse.quote(name, safe='')}"
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(url, data=data, headers={**HDR, "Content-Type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            json.loads(r.read().decode())
        print(f"✅ 上传 {name} ({len(data)/1024/1024:.1f}MB)")
    except Exception as e:
        print(f"❌ 上传 {name} 失败: {str(e)[:150]}")

print("\n🎉 Release 发布完成:", rel["html_url"])
