#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_common.py — Code Diff Analyzer · 共享基础模块

两个职责，都是「全技能唯一实现」以避免口径漂移：

【一】版本键归一化（2026-09-18 修复 · 对应缺陷 P0-1）

    历史缺陷：三个数据文件对同一版本用了三种写法，导致 Bug↔变更 两侧永不交汇
    （实测 49 个 Bug 有效关联数为 0）：
        version_bugs.json   -> 裸号      5.3.0.2
        service_metrics.json-> 带前缀    business-5.3.0.2
        version_chain.json  -> 带前缀    business-5.3.0.2
    而 bug_correlate.py 用精确字符串相等匹配 → 必然 miss。

    现在统一走 norm_version() 取规范键（首个「数字.数字」连续段），
    所有跨文件比较一律先归一，再比较。

【二】变更文件路径过滤（2026-09-18 修复 · 对应缺陷 P0-4）

    分两级，语义不同、不可混用：
      · JUNK_PATTERNS      —— 硬排除。输入产物（*tagdiff*.txt）/ 临时文件 / VCS 噪声。
                              这些东西**从来不是变更代码**，绝不允许进 file_history。
                              实例：trufar-frontend/file_history.json 里混入过
                              `manage-5.1.0.5_tagdiff.txt`（那是输入文件）。
      · NON_LOGIC_PATTERNS —— 软标记。确实是本次变更的文件（应计入 files_changed），
                              但不是业务逻辑（lock / 构建配置 / 静态资源 / 文档），
                              风险评分时降权，**不剔除**。
                              注：早期若把这一级也剔除，会破坏
                              「file_history 条目数 == metrics.files_changed」自检。

用法：
    from _common import norm_version, version_key, same_version, version_series
    from _common import is_junk_path, is_logic_path, filter_change_files
"""
import json
import os
import re
import sys

# ----------------------------------------------------------------------------
# 一、版本键归一化
# ----------------------------------------------------------------------------
# 取首个「数字.数字(.数字)*」连续段；至少两段才算版本号（避免把 5 当成版本）
_VER_RUN_RE = re.compile(r"(\d+(?:\.\d+){1,})")
_SEG_RE = re.compile(r"\d+")

# 排序时统一补齐到 4 段，使 5.3 / 5.3.0 / 5.3.0.0 视为同一版本
_PAD_SEGMENTS = 4


def norm_version(v):
    """把任意版本写法归一为规范键。

    business-5.3.0.2 / v5.3.0.2 / 5.3.0.2 / release-5.3.0.2-hotfix -> '5.3.0.2'
    5.3 -> '5.3'；非法/空 -> None

    非版本类键（如纯文本）返回小写去空白后的原串，保证 != None 时仍可比较。
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("none", "nan", "-", "—", "/"):
        return None
    m = _VER_RUN_RE.search(s)
    if m:
        return m.group(1)
    # 无数字版本段：保留清洗后的字符串，便于诊断（不静默丢弃）
    cleaned = re.sub(r"\s+", "", s).lower()
    return cleaned or None


def version_segments(v):
    """规范键 -> 整数段列表（供排序/补齐用）。"""
    nv = norm_version(v)
    if not nv:
        return []
    return [int(x) for x in _SEG_RE.findall(nv)]


def version_key(v):
    """规范键 -> 可排序元组（统一补齐 4 段，保证全序且长度无关）。

    5.3 / 5.3.0 / 5.3.0.0  ->  (5, 3, 0, 0)
    5.3.0.2                ->  (5, 3, 0, 2)
    非法                   ->  (0, 0, 0, 0)
    """
    segs = version_segments(v)
    if not segs:
        return (0,) * _PAD_SEGMENTS
    if len(segs) < _PAD_SEGMENTS:
        return tuple(segs + [0] * (_PAD_SEGMENTS - len(segs)))
    return tuple(segs)


def same_version(a, b):
    """两个版本写法是否指向同一版本（含 None 处理：两者都为 None 时返回 True）。"""
    na, nb = norm_version(a), norm_version(b)
    if na is None and nb is None:
        return True
    return na is not None and na == nb


def version_series(v):
    """版本系列 = 规范键前两段。'5.3.0.2' -> '5.3'；段数不足 -> None。"""
    segs = version_segments(v)
    if len(segs) < 2:
        return None
    return "%d.%d" % (segs[0], segs[1])


def build_canon_index(values):
    """一批原始版本串 -> {规范键: [原始串, ...]}（用于诊断书写法不一致）。"""
    idx = {}
    for v in values:
        nv = norm_version(v)
        if nv is None:
            continue
        idx.setdefault(nv, [])
        if str(v) not in idx[nv]:
            idx[nv].append(str(v))
    return idx


def inconsistent_keys(values):
    """返回「同一规范键对应多种原始写法」的清单，供 doctor / 回归检查使用。"""
    return {k: vs for k, vs in build_canon_index(values).items() if len(vs) > 1}


def inconsistent_keys_by_source(sources):
    """按来源定位「同一版本多种写法」——用于定位缺陷根因落在哪个文件。

    sources: {来源名: [原始版本串, ...]}，例如
        {"service_metrics.version_to": ["business-5.3.0.2"],
         "version_bugs.found_in_version": ["5.3.0.2"]}

    返回 {规范键: {"raw_forms": [...], "sources": [...]}}
    只保留 len(raw_forms) > 1 的条目（即真实的写法不一致）。

    ⚠️ 必须把 Bug 侧版本一并传入：2026-09-18 的一次实现只扫了 metrics/chain，
    结果三个文件真不一致却报「0 处不一致」，把根因藏起来了。
    """
    per_key = {}
    for src, values in (sources or {}).items():
        for v in (values or []):
            nv = norm_version(v)
            if nv is None:
                continue
            e = per_key.setdefault(nv, {"raw_forms": [], "sources": []})
            raw = str(v).strip()
            if raw not in e["raw_forms"]:
                e["raw_forms"].append(raw)
            if src not in e["sources"]:
                e["sources"].append(src)
    out = {}
    for k, e in per_key.items():
        if len(e["raw_forms"]) > 1:
            out[k] = {"raw_forms": sorted(e["raw_forms"]), "sources": sorted(e["sources"])}
    return out


# ----------------------------------------------------------------------------
# 二、变更文件路径过滤
# ----------------------------------------------------------------------------
# 硬排除：输入产物 / 临时文件 / VCS 与构建噪声 —— 从来不是变更代码
JUNK_PATTERNS = [
    r"(^|/)[^/]*tagdiff[^/]*\.(txt|log|json|csv|md)$",   # 输入产物（本技能的上游输入）
    r"(^|/)temp_[^/]*$",                                  # report 目录临时产物
    r"(^|/)_build_[^/]*$",
    r"\.(tmp|bak|orig|old|rej|swp|pyc|pyo|class|log)$",
    r"(^|/)\.(DS_Store|gitkeep)$",
    r"(^|/)__pycache__/",
    r"(^|/)node_modules/",
    r"(^|/)\.git/",
    r"(^|/)compare_[^/]*_to_[^/]*\.(md|txt)$",            # 本技能另一类输入产物
]

# 软标记：是真实变更文件，但不是业务逻辑 —— 保留、但风险评分降权
NON_LOGIC_PATTERNS = [
    r"package(-lock)?\.json$",
    r"pnpm-lock\.yaml$",
    r"yarn\.lock$",
    r"(^|/)tsconfig[^/]*\.json$",
    r"(^|/)\.eslintrc", r"(^|/)\.prettierrc",
    r"(^|/)\.browserslistrc$", r"(^|/)\.editorconfig$",
    r"(^|/)\.gitignore$", r"(^|/)\.npmrc$",
    r"(^|/)Dockerfile$", r"(^|/)\.dockerignore$",
    r"(^|/)README[^/]*$", r"\.(md|txt|rst)$",
    r"\.(png|jpe?g|gif|svg|ico|webp|bmp|woff2?|ttf|eot)$",
    r"\.(css|scss|less|styl)$",
    r"\.(map|d\.ts)$",
    # 静态页面外壳（SPA 入口 / 纯展示页）：只放脚本标签与标题，不是业务逻辑。
    # 实测 trufar-frontend 每次发版都会动 index.html（构建产物 hash），
    # 若计入逻辑文件会稀释风险分的区分度。
    r"\.(html?|htm)$",
]

_JUNK_RE = [re.compile(p, re.I) for p in JUNK_PATTERNS]
_NON_LOGIC_RE = [re.compile(p, re.I) for p in NON_LOGIC_PATTERNS]


def normalize_path(p):
    """统一路径分隔符为 /，去掉前导 ./，便于模式匹配与跨平台键一致。"""
    if p is None:
        return ""
    s = str(p).strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def is_junk_path(p):
    """是否属于「输入产物 / 临时文件 / VCS 噪声」—— 应硬排除。"""
    s = normalize_path(p)
    if not s:
        return True
    return any(r.search(s) for r in _JUNK_RE)


def is_logic_path(p):
    """是否是业务逻辑文件（非逻辑的仍会入 file_history，只是风险降权）。"""
    s = normalize_path(p)
    if not s:
        return False
    return not any(r.search(s) for r in _NON_LOGIC_RE)


def filter_change_files(paths, keep_junk=False):
    """过滤一批变更文件路径。

    返回 (kept, dropped)：
      kept    —— 保留的路径（顺序稳定、去重）
      dropped —— 被硬排除的路径（供报告提示"已忽略 N 个输入产物/临时文件"）
    keep_junk=True 时只去重不过滤（诊断用）。
    """
    kept, dropped, seen = [], [], set()
    for p in (paths or []):
        s = normalize_path(p)
        if not s or s in seen:
            continue
        seen.add(s)
        if not keep_junk and is_junk_path(s):
            dropped.append(s)
        else:
            kept.append(s)
    return kept, dropped


# ---------------------------------------------------------------------------
# 项目级 Bug 池（2026-09-18 用户决策：Bug 按「提测版本整包」关联，不区分前后端服务）
# ---------------------------------------------------------------------------
PROJECT_POOL_DIR = "_project"
PROJECT_SERVICE = "_project"

# 端归属预判关键词（按优先级顺序；命中即停）。仅作「预判」输出，报告中必须带
# 「预判」字样，且允许在 version_bugs.json 中人工覆盖 side_pre 字段。
SIDE_PRE_RULES = [
    ("后端", r"接口|请求参数|未请求|返回数据|返回错误|返回结果|数据错误|数据异常|"
             r"查询报错|导出失败|导出文件|导出与页面|统计(值|错误|中)|分页查询|"
             r"跳转至|跳转|加载|获取|检索|未获取|去重|口径|数据未|未包含|应请求"),
    ("前端", r"展示|显示|未展示|文案|悬浮|提示语?|样式|布局|排版|icon|图标|翻译|未翻译|"
             r"下拉|按钮|间距|缩放|列宽|滚动|页面|表格|弹窗|省略号|固定字段长度|"
             r"未清空|未重置|联动|白屏|标题格式|按demo|与demo"),
]


def classify_bug_side(bug):
    """按标题关键词预判 Bug 端归属（前端/后端/通用）。

    返回 (side, matched_rule) —— matched_rule 为命中的关键词片段（可空）。
    规则只命中一次（按 SIDE_PRE_RULES 顺序），均未命中归「通用」。
    这是**预判**：仅用于报告展示分布，不参与任何评分/关联计算。
    """
    title = (bug or {}).get("title") or ""
    for side, pat in SIDE_PRE_RULES:
        m = re.search(pat, title)
        if m:
            return side, m.group(0)
    return "通用", ""


# 服务端属性识别（2026-09-19）：用于把项目级 Bug 池按「前后端」拆分展示。
# 判定优先级：① 服务名关键词 ② 变更文件扩展名（metrics 记录传入）
SERVICE_SIDE_NAME_RULES = [
    ("后端", r"backend|back-end|-back\b|server|service|api|admin"),
    ("前端", r"frontend|front-end|-front\b|web|ui\b|landing|page|h5|miniapp|app"),
]
SERVICE_SIDE_EXT_RULES = [
    ("后端", r"\.(java|kt|scala|py|go|rb|php|c|cpp|cs|sql|xml|gradle)$"),
    ("前端", r"\.(vue|tsx|jsx|ts|js|css|scss|less|html|htm)$"),
]


def service_side(service, files=None):
    """判定服务的端属性：前端 / 后端 / None（判不出就返回 None，报告端按「未知」处理）。

    ① 服务名：portal-backend→后端、manage-frontend→前端
    ② 兜底用变更文件扩展名：.java→后端、.vue/.ts→前端
    返回 (side, rule) —— rule 为判定依据（name:xxx / ext:xxx / None）。
    """
    s = (service or "").lower()
    for side, pat in SERVICE_SIDE_NAME_RULES:
        m = re.search(pat, s)
        if m:
            return side, f"name:{m.group(0)}"
    for side, pat in SERVICE_SIDE_EXT_RULES:
        hit = None
        for f in (files or []):
            p = f.get("path") if isinstance(f, dict) else f
            if p and re.search(pat, str(p).lower()):
                hit = re.search(pat, str(p).lower()).group(0)
                break
        if hit:
            return side, f"ext:{hit}"
    return None, None


def bugs_side_breakdown(bugs, key_of=lambda b: norm_version(b.get("found_in_version"))):
    """按端归属预判拆分一组 Bug：-> {版本键: {"前端":n,"后端":n,"通用":n}}。"""
    out = {}
    for b in bugs or []:
        k = key_of(b)
        if not k:
            continue
        side = b.get("side_pre") or classify_bug_side(b)[0]
        out.setdefault(k, {"前端": 0, "后端": 0, "通用": 0})
        out[k][side] = out[k].get(side, 0) + 1
    return out


def side_relevant_count(dist, side):
    """本端相关数 = 该端预判数 + 通用数（通用=关键词未命中、端归属待定，计入但需标注）。"""
    if not side:
        return None
    return (dist.get(side, 0) + dist.get("通用", 0))


def load_bugs_doc(analytics_root, service):
    """加载 version_bugs.json：优先服务级，回退项目级池 `_project/`。

    返回 (doc, scope)：
      doc   —— version_bugs.json 解析结果（无则 None）
      scope —— "service"（服务级，可归因到单服务）| "project"（项目级池，
               Bug 属于提测版本整包，不可归因到单服务）| None（两者皆无）
    """
    root = analytics_root
    if service and service != PROJECT_SERVICE:
        p = os.path.join(root, service, "version_bugs.json")
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                if d and d.get("bugs"):
                    return d, "service"
            except (OSError, ValueError):
                pass
    p = os.path.join(root, PROJECT_POOL_DIR, "version_bugs.json")
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if d and d.get("bugs"):
                return d, "project"
        except (OSError, ValueError):
            pass
    return None, None


# -------------------------------
# HTML 注释泄漏防护（2026-09-20）
# 教训：注释体内出现「<-- X_START/END -->」嵌套写法时，浏览器在嵌套的 --> 处
# 提前终止注释，剩余文本（如「）。 -->」）以裸文本泄漏到页面。
# 守则：HTML 注释内禁止出现 "-->"（含 "<--" 嵌套标记写法）与 "--!>"。
# -------------------------------

_LEAK_PATTERNS = ("<!--", "<--", "--!>")


def scan_comment_leaks(html):
    """扫描 HTML 注释体内的嵌套标记/提前终止隐患，返回泄漏片段列表（空 = 安全）。"""
    risks = []
    for m in re.finditer(r"<!--(.*?)-->", html, re.S):
        inner = m.group(1)
        if any(p in inner for p in _LEAK_PATTERNS):
            risks.append("<!--%s-->" % inner.strip()[:120])
    return risks


def safe_write_report(path, html):
    """写入报告 HTML 前强制做注释泄漏检查；发现泄漏则拒绝落盘并退出（防带病交付）。"""
    leaks = scan_comment_leaks(html)
    if leaks:
        sys.stderr.write(
            "[ERROR] 拒绝写入 %s：检测到 %d 处 HTML 注释泄漏（注释体内含 %s 嵌套写法，"
            "会在浏览器中提前终止注释并泄漏裸文本）\n" % (path, len(leaks), "/".join(_LEAK_PATTERNS))
        )
        for s in leaks[:5]:
            sys.stderr.write("  - %s\n" % s)
        sys.stderr.write("  修复：把注释内的标记写法改为「X_START/END 标记对」等不含 --> 的表述。\n")
        raise SystemExit(2)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    # 自检：归一化 + 版本序 + 路径过滤
    cases = [
        ("business-5.3.0.2", "5.3.0.2"), ("v5.3.0.2", "5.3.0.2"),
        ("5.3.0.2", "5.3.0.2"), ("release-5.3.0.2-hotfix", "5.3.0.2"),
        ("BUSINESS-5.3.0.4", "5.3.0.4"), ("5.3", "5.3"), (None, None),
    ]
    bad = [(a, b, norm_version(a)) for a, b in cases if norm_version(a) != b]
    print("归一化用例: %d/%d 通过" % (len(cases) - len(bad), len(cases)))
    for a, b, got in bad:
        print("  [FAIL] %r 期望 %r 实得 %r" % (a, b, got))

    keys = sorted(["business-5.3.0.4", "5.3.0.1", "v5.3.0.2", "5.3.0.1"], key=version_key)
    print("排序:", keys)

    p = ["apps/manage/src/views/home/myClass.vue", "manage-5.1.0.5_tagdiff.txt",
         "index.html", "tsconfig.json", "__pycache__/a.pyc", "zh.json"]
    kept, dropped = filter_change_files(p)
    print("保留:", kept)
    print("排除:", dropped)
