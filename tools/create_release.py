"""创建 GitHub Release v3.0 并上传资产（Setup 安装包 + 绿色版 zip）。

安全：TOKEN 从环境变量 GITHUB_TOKEN 读取，不再硬编码进源码。
用法：set GITHUB_TOKEN=ghp_xxx && python tools/create_release.py
"""
import json
import os
import urllib.parse
import urllib.request

TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = "lij55030-netizen"
REPO = "Wyckoff-MT5-Workbuddy"
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
HDR = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

if not TOKEN:
    print("❌ 未设置 GITHUB_TOKEN 环境变量（python tools/create_release.py 前先 set）")
    raise SystemExit(1)

BODY = """## WKF V3.0 One-Click Install Release

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
        "name": "V3.0 One-Click Install Release",
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

# 2. 上传资产
assets = [
    ("installer/WKF_V3.0_Setup.exe", "application/octet-stream"),
    ("installer/WKF_V3.0_绿色免安装版.zip", "application/zip"),
    ("绿色免安装版说明.txt", "text/plain; charset=utf-8"),
]
rel_id = rel["id"]
for path, ctype in assets:
    if not os.path.exists(path):
        print(f"⚠️ 资产缺失，跳过: {path}")
        continue
    name = os.path.basename(path)
    url = f"{BASE}/releases/{rel_id}/assets?name={urllib.parse.quote(name)}"
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
