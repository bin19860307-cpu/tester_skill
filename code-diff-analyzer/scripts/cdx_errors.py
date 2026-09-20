# -*- coding: utf-8 -*-
"""cdx_errors.py — Code Diff Analyzer 统一错误提示层

背景（2026-09-17，SkillHub 可靠性 4.1 反馈）：
    评审意见——「遇到文件路径错误或数据格式不匹配时，可能会给出让人摸不着头脑的
    错误提示，最好能更明确地告诉用户哪里出问题了」。

    根因：脚本此前直接用 `json.load(open(path))` / `openpyxl.load_workbook(path)`
    / `open(path).read()`，路径不存在或格式不符时抛出的是 Python 原生 traceback
    （FileNotFoundError / JSONDecodeError / KeyError / InvalidFileException），
    对非开发用户不可读；且多处 `except Exception: pass` 会静默跳过，用户看不到原因。

本模块把这类失败统一转换为**明确指出问题文件、原因、修复方法**的中文提示。

设计约束：
    - 纯标准库（不引入第三方依赖），与其余子脚本一致；
    - 不改动业务逻辑，只在 I/O 边界加「前置校验 + 友好报错」。

用法：
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from cdx_errors import guard, require_file, read_json, read_text, open_xlsx, parse_json_arg

    if __name__ == "__main__":
        guard(main)     # 顶层兜底：任何未预期异常 -> 友好提示（--debug / CDX_DEBUG=1 打印堆栈）

退出码约定：
    1 未预期错误 / 2 参数或依赖缺失 / 3 输入文件问题 / 4 数据格式问题
"""
import difflib
import json
import os
import sys
import traceback

DEBUG = ("--debug" in sys.argv) or (os.environ.get("CDX_DEBUG") == "1")


# ---------------------------------------------------------------------------
# 基础输出
# ---------------------------------------------------------------------------
def _emit(title, detail=None, hint=None):
    bar = "=" * 68
    out = [bar, "[ERROR] " + str(title)]
    if detail:
        for line in str(detail).splitlines():
            out.append("        " + line)
    if hint:
        out.append("  → 建议: " + str(hint))
    out.append(bar)
    sys.stderr.write("\n".join(out) + "\n")
    try:
        sys.stderr.flush()
    except Exception:
        pass


def die(title, detail=None, hint=None, code=2):
    """打印友好的错误块并以指定退出码结束。"""
    _emit(title, detail, hint)
    sys.exit(code)


def warn(msg):
    sys.stderr.write("[WARN] " + str(msg) + "\n")


# ---------------------------------------------------------------------------
# 文件 / 路径
# ---------------------------------------------------------------------------
def _suggest_similar(path):
    folder = os.path.dirname(path) or "."
    base = os.path.basename(path)
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    hit = difflib.get_close_matches(base, names, n=3, cutoff=0.5)
    return hit or None


def require_file(path, label="输入文件", hint=None):
    """校验文件存在，返回绝对路径；否则给出可读报错（含相近文件名提示）。"""
    if not path:
        die("%s未提供" % label, hint=hint or "请用命令行参数指定该文件路径。", code=3)
    ap = os.path.abspath(path)
    if os.path.isdir(ap):
        die("%s是一个目录，不是文件: %s" % (label, ap),
            hint=hint or "请指向具体文件，而不是目录。", code=3)
    if not os.path.isfile(ap):
        detail = ["路径: %s" % ap, "当前工作目录: %s" % os.getcwd()]
        sug = _suggest_similar(ap)
        if sug:
            detail.append("同目录下相近的文件: " + ", ".join(sug))
        die("%s不存在" % label, "\n".join(detail),
            hint=hint or "核对路径拼写；路径含空格/中文时请加英文引号。", code=3)
    return ap


def read_text(path, label="文件", hint=None):
    """读取 UTF-8 文本，失败时给出明确原因。"""
    ap = require_file(path, label, hint)
    try:
        with open(ap, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError as e:
        die("%s不是 UTF-8 文本: %s" % (label, ap),
            "解码失败于字节位置 %d" % e.start,
            hint="请用 UTF-8 编码另存后再试（勿用 GBK/ANSI）。", code=4)
    except OSError as e:
        die("%s读取失败: %s" % (label, ap), str(e),
            hint="检查文件是否被其他程序占用或权限不足。", code=4)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def _explain_json_error(raw, e):
    lines = raw.splitlines()
    ctx = ""
    if 1 <= e.lineno <= len(lines):
        ctx = "第 %d 行: %s" % (e.lineno, lines[e.lineno - 1].strip()[:120])
    return ("解析错误: %s（第 %d 行 第 %d 列）\n%s\n文件大小: %d 字节"
            % (e.msg, e.lineno, e.colno, ctx, len(raw.encode("utf-8"))))


def read_json(path, label="JSON 文件", hint=None, allow_missing=False, default=None):
    """读取 JSON；失败时指出文件、行列与常见成因。allow_missing=True 时缺失返回 default。"""
    if path:
        ap = os.path.abspath(path)
        if allow_missing and not os.path.isfile(ap):
            return default
    ap = require_file(path, label, hint)
    try:
        with open(ap, encoding="utf-8") as f:
            raw = f.read()
    except UnicodeDecodeError as e:
        die("%s不是 UTF-8 编码: %s" % (label, ap),
            "解码失败于字节位置 %d" % e.start,
            hint="另存为 UTF-8（无 BOM）后重试；可能是二进制或 GBK 文件。", code=4)
    except OSError as e:
        die("%s读取失败: %s" % (label, ap), str(e),
            hint="检查文件是否被占用或权限不足。", code=4)
    if raw.strip() == "":
        die("%s是空文件: %s" % (label, ap),
            hint="该文件应为合法 JSON（通常是本工具上一步的产出）。", code=4)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        die("%s不是合法 JSON: %s" % (label, ap), _explain_json_error(raw, e),
            hint="用 `python -m json.tool <文件>` 校验；注意 JSON 不支持注释、"
                 "结尾多余逗号、单引号、NaN。", code=4)


def try_json(path, label=None):
    """可选文件：不存在→None（静默）；存在但解析失败→打印明确 WARN 并返回 None。

    用于「缺失可容忍、但格式错误需要告知」的场景，避免静默跳过导致用户困惑。
    """
    if not path or not os.path.isfile(path):
        return None
    label = label or os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except UnicodeDecodeError:
        warn("%s 不是 UTF-8 编码，已跳过: %s" % (label, path))
        return None
    except OSError as e:
        warn("%s 读取失败(%s)，已跳过: %s" % (label, e, path))
        return None
    if raw.strip() == "":
        warn("%s 为空文件，已跳过: %s" % (label, path))
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        warn("%s 不是合法 JSON（第 %d 行 第 %d 列: %s），已跳过: %s"
             % (label, e.lineno, e.colno, e.msg, path))
        return None


def parse_json_arg(text, label="内联 JSON 参数"):
    """解析命令行内联 JSON 字符串，失败时给出明确原因。"""
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        die("%s不是合法 JSON" % label,
            "解析错误: %s（第 %d 行 第 %d 列）" % (e.msg, e.lineno, e.colno),
            hint="命令行内联 JSON 需整体加英文引号，且键/值均用双引号。", code=4)


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def open_xlsx(path, label="Excel 文件"):
    """打开 xlsx 工作簿；对扩展名/依赖/损坏/占用给出明确提示。"""
    ap = os.path.abspath(path) if path else path
    ext = os.path.splitext(ap)[1].lower() if ap else ""
    if ext and ext not in (".xlsx", ".xlsm"):
        die("%s扩展名不支持: %s" % (label, ext),
            "路径: %s" % ap,
            hint="仅支持 .xlsx/.xlsm。若为 .xls/.csv，请先用 Excel/WPS 另存为 .xlsx 再重试。",
            code=3)
    ap = require_file(ap, label)
    try:
        import openpyxl
    except ImportError:
        die("缺少依赖 openpyxl",
            hint="pip install openpyxl（或 pip install -r scripts/requirements.txt）", code=2)
    try:
        return openpyxl.load_workbook(ap, data_only=True)
    except Exception as e:  # noqa: BLE001 - 需按类型分派友好提示
        name = type(e).__name__
        if name in ("InvalidFileException", "BadZipFile"):
            die("%s无法作为 Excel 打开: %s" % (label, ap),
                "底层错误: %s: %s" % (name, e),
                hint="文件可能不是真正的 xlsx（如 .xls 改后缀、下载成了 HTML 错误页、或已损坏）。"
                     "请用 Excel/WPS 打开确认后另存为 .xlsx。", code=4)
        if isinstance(e, PermissionError):
            die("%s被占用无法读取: %s" % (label, ap), str(e),
                hint="关闭正在打开该文件的 Excel/WPS 后重试。", code=4)
        raise


def check_headers(headers, required, label="Excel", hint=None):
    """required: {标准字段: [候选列名, ...]}；有缺失则报错并列出实际表头。

    仅用于「缺了就必然失败」的必需列；可选列请保持宽容处理。
    """
    norm = [str(h).strip() for h in headers if h is not None and str(h).strip() != ""]
    missing = [(f, v) for f, v in required.items() if not any(x in norm for x in v)]
    if missing:
        det = ["缺失字段: " + "; ".join("%s（应有列名之一: %s）" % (f, "/".join(v[:3])) for f, v in missing),
               "实际表头: " + (", ".join(norm[:20]) if norm else "（空）")]
        die("%s列名不匹配" % label, "\n".join(det),
            hint=hint or "请确认导出的表格使用了预定义列名（如 编号/标题/状态/严重程度/产生版本）。",
            code=4)


# ---------------------------------------------------------------------------
# 顶层兜底
# ---------------------------------------------------------------------------
def guard(fn, *args, **kwargs):
    """运行 main 并将未预期异常转换为友好提示（--debug / CDX_DEBUG=1 打印完整堆栈）。"""
    try:
        return fn(*args, **kwargs)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.stderr.write("\n[中断] 用户取消。\n")
        sys.exit(130)
    except FileNotFoundError as e:
        die("找不到文件", str(e), hint="核对路径；相对路径基于当前工作目录。", code=3)
    except IsADirectoryError as e:
        die("期望文件但传入的是目录", str(e), hint="请指向具体文件。", code=3)
    except PermissionError as e:
        die("文件被占用或无权限", str(e),
            hint="关闭占用该文件的程序（Excel/编辑器），或改用可写目录。", code=4)
    except UnicodeDecodeError as e:
        die("文本编码错误（期望 UTF-8）", str(e), hint="将文件另存为 UTF-8 后重试。", code=4)
    except json.JSONDecodeError as e:
        die("JSON 解析失败", "%s（第 %d 行 第 %d 列）" % (e.msg, e.lineno, e.colno),
            hint="校验 JSON 语法后重试。", code=4)
    except KeyError as e:
        die("缺少必需字段/键: %s" % e,
            hint="输入数据缺少脚本预期的字段，请核对上游产物 schema。", code=4)
    except Exception as e:  # noqa: BLE001 - 顶层兜底
        if DEBUG:
            traceback.print_exc()
        die("未预期错误: %s" % type(e).__name__, str(e),
            hint="加 --debug（或设 CDX_DEBUG=1）查看完整堆栈；"
                 "若怀疑数据格式问题，请核对输入 JSON/Excel 的 schema。", code=1)
