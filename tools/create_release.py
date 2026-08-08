"""创建 GitHub Release v3.0 并上传资产（Setup 安装包 + 绿色版 zip）。

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

BODY = """## 🎉 WKF 威科夫交易智能体 V3.0 一键安装版发布

### 📦 下载指引（点击文件名即可下载，说明如下）

| 点击下载 | 这是什么 | 怎么用 |
|---|---|---|
| **WKF_V3.0_Setup.exe** | 一键安装包（推荐） | 双击运行进入安装向导，支持自定义安装路径、桌面快捷方式、开始菜单、卸载程序 |
| **WKF_V3.0_Portable.zip** | 绿色免安装版 | 解压后双击文件夹里的 `WKF.exe` 即可使用，无需安装、无需 Python 环境 |
| **WKF_V3.0_Readme.txt** | 使用说明 | 下载后请先阅读：MT5 连接、数据源切换、功能简介 |

> 提示：如浏览器下载后文件名显示异常，可右键另存为后重命名。

### 🎉 本版亮点（V1.3.2 + V1.3.3 迭代汇总）

**行情异步加载（根治切换卡顿）**
- QThread 子线程拉取 MT5/yfinance K线 + Footprint + 订单流，信号回主线程一次性渲染
- 300ms 防抖 + 全局加载锁 + 请求序号：快速连续切换只发最后一次，不堆积不串数据
- 切换前置清理（清图层/挂起Tick/重置十字光标）+ 完成后恢复附属功能
- 1 分钟周期 tick 分桶二分优化（O(n×m) → O(n log m)），2880 根 K 线秒级加载
- 修复 MT5 IPC 连接失败（显式 terminal64 路径重试）

**时间戳体系（统一 YYYY-MM-DD HH:mm:ss）**
- 决策面板头部「决策生成时间」（空值自动兜底当前时间）
- 数据快照文件名含时间 + 文档头部创建时间；历史记录前置时间标签
- 诊断报告首行生成时间；HTML/飞书输出附带时间戳

**YFinance 数据源 UI**
- 顶部新增「行情数据源」下拉（MT5 / YFinance），切换即清缓存异步重拉
- 底部状态栏实时展示数据源；诊断/快照备注行情渠道

**K 线图表交互**
- 左键拖拽平移 / 滚轮缩放 / 右键框选局部放大 / 空格键重置完整视图
- 品种或周期切换自动重置视图，覆盖元素随画布自适应

**核心信号修复**
- 订单流吸收结构三重联合判定（放量+窄幅+Delta背离），废弃恒真硬编码
- 回测真实胜率：K线向后推演（突破入场价判盈利/止损判亏），
  输出胜率/盈亏比/最大连亏/净值曲线/逐笔明细导出 CSV

### 📦 安装方式
1. **一键安装版**：WKF_V3.0_Setup.exe（支持自定义路径/桌面快捷方式/卸载程序）
2. **绿色免安装版**：WKF_V3.0_绿色免安装版.zip（解压即用，无需 Python）

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
        "tag_name": "v3.0",
        "name": "WKF 威科夫交易智能体 V3.0 一键安装版",
        "body": BODY,
        "draft": False,
        "prerelease": False,
    })
    print("✅ Release 创建成功:", rel["html_url"])
except Exception as e:
    rels = api("GET", f"{BASE}/releases?per_page=10")
    rel = next((r for r in rels if r.get("tag_name") == "v3.0"), None)
    if not rel:
        print("❌ 创建失败:", str(e)[:200])
        raise SystemExit(1)
    print("ℹ️ Release 已存在，复用:", rel["html_url"])
    # 已存在则同步更新标题与说明（汉化）
    try:
        rel = api("PATCH", f"{BASE}/releases/{rel['id']}", {
            "name": "WKF 威科夫交易智能体 V3.0 一键安装版",
            "body": BODY,
        })
        print("✅ Release 标题与说明已更新为中文")
    except Exception as e:
        print(f"⚠️ 更新标题失败: {str(e)[:120]}")

# 2. 上传资产（本地路径, 上传显示名, 内容类型）
# 说明：当前网络通道对非 ASCII 文件名会归一化为 default.txt，
# 资产名保持 ASCII 语义（Setup/Portable/Readme），中文说明在 Release 正文。
assets = [
    ("installer/WKF_V3.0_Setup.exe", "WKF_V3.0_Setup.exe", "application/octet-stream"),
    ("installer/WKF_V3.0_绿色免安装版.zip", "WKF_V3.0_Portable.zip", "application/zip"),
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

# 2.2 上传中文名资产
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
