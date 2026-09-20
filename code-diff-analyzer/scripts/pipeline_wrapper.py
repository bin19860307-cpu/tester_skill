#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_wrapper.py — Code Diff Analyzer 流水线统一入口（Phase 1 容器化）

统一编排 4 个固化脚本，供 Jenkins Shared Library / GitLab CI / 手动三种方式调用：
    bug_correlate.py       —— Bug 关联（Flow A + Flow B，全量覆写 version_bugs / cross_reference）
    bug_trend.py           —— 版本 Bug 趋势（Flow C.2，内联 SVG，无 CDN）
    gen_combined_report.py —— 综合比对分析报告（多服务聚合）
    gen_p1_cases.py        —— P1 用例注入（幂等）

关键边界（与「LLM 前置生成」决策一致）：
    Step 1-7 的语义分析（格式识别 / 变更分类 / 模块依赖 / 风险评分）由 LLM Agent 在
    PR 前置阶段完成，其产物 service_metrics.json 落盘到 diff-analytics/{service}/。
    本流水线【只消费】这些结果：bug 关联 → 趋势统计 → 综合报告 → P1 用例注入，
    不在流水线内做 LLM 推理，避免发布链路被 AI 延迟/成本拖累。

分阶段执行（--stage）：
    analyze  —— 准备工作区 + 可选 git 浅克隆 + 写运行元数据 + 交接校验（严格把关）
    score    —— bug_correlate(需 --xlsx) + bug_trend(需 version_bugs.json 已就绪)
    report   —— gen_combined_report(多服务) + gen_p1_cases 注入(可选 --p1-data-file)
    all      —— analyze → score → report 链式执行（默认）

交接把关（analyze 阶段）：
    默认【阻断】：若 service_metrics.json 未就绪，analyze 以退出码 2 结束，
    用于 CI 门禁拦截「语义分析产物缺失却继续出报告」。
    手动 / 开发场景可加 --allow-missing-metrics 豁免（降级为警告 + 退出码 0）。

用法示例：
    # 仅准备 + 校验（CI 门禁：语义分析产物未就绪则退出码 2 拦截）
    python pipeline_wrapper.py --stage analyze --service portal-backend \
        --repo-url git@xxx/portal-backend.git --target-tag v1.1

    # 量化评分：导入 bug Excel + 生成趋势
    python pipeline_wrapper.py --stage score --service portal-backend --xlsx bug.xlsx

    # 报告聚合 + P1 用例注入
    python pipeline_wrapper.py --stage report --services a b c --p1-data-file p1.json

    # 一键全流程（analyze → score → report）
    python pipeline_wrapper.py --stage all --service portal-backend --xlsx bug.xlsx

    # 手动 / 开发：产物缺失时不阻断
    python pipeline_wrapper.py --stage all --service portal-backend --allow-missing-metrics

依赖：仅 Python 标准库（wrapper 本体）；子脚本 bug_correlate 需 openpyxl。
"""
import argparse
import cdx_errors  # 统一友好错误层
import json
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# analyze 交接失败（语义分析产物缺失）专用退出码：与 1（参数错误）/ 子脚本退出码区分，
# 便于 Jenkins / GitLab CI 用 returnCode==2 精准判定「前置语义分析未就绪」，而非笼统失败。
EXIT_HANDOFF_MISSING = 2

# 超时保护（R 运行稳定性）：子脚本与 git clone 均设超时，避免磁盘/网络卡顿挂死流水线。
# 可由命令行 --timeout / --git-timeout 覆盖。
SCRIPT_TIMEOUT = 600
GIT_TIMEOUT = 180

SCRIPTS = {
    "bug_correlate": os.path.join(HERE, "bug_correlate.py"),
    "bug_trend": os.path.join(HERE, "bug_trend.py"),
    "gen_combined_report": os.path.join(HERE, "gen_combined_report.py"),
    "gen_p1_cases": os.path.join(HERE, "gen_p1_cases.py"),
}


def _py():
    return sys.executable or "python"


def run_py(script_name, *args):
    """以当前解释器运行兄弟脚本，任一非零退出码或超时即中止整条流水线。"""
    if script_name not in SCRIPTS:
        print(f"[ERROR] 未知脚本: {script_name}")
        sys.exit(1)
    cmd = [_py(), SCRIPTS[script_name]] + list(args)
    print("\n>>> " + " ".join(cmd))
    try:
        r = subprocess.run(cmd, timeout=SCRIPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] '{script_name}' 超过 {SCRIPT_TIMEOUT}s 未完成，已中止。")
        print("          常见原因：磁盘 / 网络卡顿或输入过大；可用 --timeout 调大后重试。")
        sys.exit(1)
    if r.returncode != 0:
        print(f"[FAIL] '{script_name}' 退出码 {r.returncode}，流水线中止。")
        sys.exit(r.returncode)
    return r.returncode


def resolve_paths(args):
    """统一路径：workspace 优先取 --workspace，其次 $WORKSPACE(Jenkins)，最后 cwd。

    覆盖 4 个子脚本硬编码的 Windows 默认 workspace（d:/workbuddy/测试日常），
    使容器 / CI 环境也能正确落盘。"""
    workspace = args.workspace or os.environ.get("WORKSPACE") or os.getcwd()
    analytics_root = args.analytics_root or os.path.join(workspace, ".workbuddy", "diff-analytics")
    report_root = args.report_root or os.path.join(workspace, "report", "code-diff")
    return workspace, analytics_root, report_root


def write_run_meta(analytics_root, service, args):
    """写运行元数据（版本链可追溯），供后续回归对比 / 审计。"""
    meta = {
        "pipeline": "code-diff-analyzer",
        "service": service,
        "source_tag": args.source_tag,
        "target_tag": args.target_tag,
        "stage": args.stage,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    svc_dir = os.path.join(analytics_root, service)
    os.makedirs(svc_dir, exist_ok=True)
    path = os.path.join(svc_dir, "pipeline_run.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[OK] 运行元数据已写入 {path}")
    return path


def stage_analyze(args):
    workspace, analytics_root, report_root = resolve_paths(args)
    if not args.service:
        print("[ERROR] analyze 阶段需要 --service")
        sys.exit(1)

    os.makedirs(analytics_root, exist_ok=True)

    # 可选：git 浅克隆（仅作上下文/归档，语义 diff 由 LLM 前置完成）
    if args.repo_url:
        clone_dir = args.clone_dir or os.path.join(workspace, "src", args.service)
        branch = args.target_tag or args.source_tag
        cmd = ["git", "clone", "--depth", str(args.git_depth)]
        if branch:
            cmd += ["--branch", branch]
        cmd += [args.repo_url, clone_dir]
        print("\n>>> " + " ".join(cmd))
        try:
            r = subprocess.run(cmd, timeout=GIT_TIMEOUT)
            if r.returncode != 0:
                print(f"[WARN] git clone 非零退出码 {r.returncode}，仅记录不影响后续")
        except subprocess.TimeoutExpired:
            print(f"[WARN] git clone 超过 {GIT_TIMEOUT}s 未完成（网络卡顿？），已跳过，仅归档用途不影响后续。")
            print("       可用 --git-timeout 调大后重试。")
        except FileNotFoundError:
            print("[WARN] 未找到 git 命令，跳过浅克隆（仅归档用途不影响后续）。")
        except OSError as e:
            print(f"[WARN] git clone 无法执行（{e}），已跳过，仅归档用途不影响后续。")

    write_run_meta(analytics_root, args.service, args)

    # 交接校验：语义分析产物（service_metrics.json）是否就绪
    metrics = os.path.join(analytics_root, args.service, "service_metrics.json")
    if os.path.isfile(metrics):
        print(f"[OK] service_metrics.json 已就绪，可进入 score 阶段")
    elif args.allow_missing_metrics:
        print("[HANDOFF] service_metrics.json 尚未生成。")
        print("         语义分析（Step 1-7）由 LLM Agent 在 PR 前置阶段完成，")
        print("         流水线只消费其结果。请先完成语义分析，产物落盘到上述 analytics 目录。")
        print("[WARN] 已启用 --allow-missing-metrics 豁免，本次不阻断（退出码 0）。")
    else:
        print("[HANDOFF] service_metrics.json 尚未生成。")
        print("         语义分析（Step 1-7）由 LLM Agent 在 PR 前置阶段完成，")
        print("         流水线只消费其结果。请先完成语义分析，产物落盘到上述 analytics 目录。")
        print(f"[FAIL] 交接未就绪，analyze 以退出码 {EXIT_HANDOFF_MISSING} 结束（CI 门禁应拦截）。")
        print("       手动 / 开发场景可加 --allow-missing-metrics 豁免。")
        sys.exit(EXIT_HANDOFF_MISSING)


def stage_score(args):
    workspace, analytics_root, report_root = resolve_paths(args)
    if not args.service:
        print("[ERROR] score 阶段需要 --service")
        sys.exit(1)

    # 1) Bug 关联（需 --xlsx；全量覆写 version_bugs.json + 重建 cross_reference.json）
    if args.xlsx:
        if not os.path.isfile(args.xlsx):
            print(f"[ERROR] xlsx 不存在: {args.xlsx}")
            sys.exit(1)
        run_py("bug_correlate", "--xlsx", args.xlsx,
               "--service", args.service, "--analytics-root", analytics_root)
    else:
        print("[SKIP] 未提供 --xlsx，跳过 bug_correlate（Bug 关联）")

    # 2) Bug 趋势（需 version_bugs.json 已就绪；服务级缺失时回退项目级池）
    import _common  # noqa: E402  （同目录共享模块）
    _doc, _scope = _common.load_bugs_doc(analytics_root, args.service)
    if _doc:
        out = args.trend_out or os.path.join(
            report_root, args.service,
            f"{args.service}_bug趋势统计_{datetime.now().strftime('%Y%m%d')}.html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        run_py("bug_trend", "--service", args.service,
               "--analytics-root", analytics_root, "--out", out)
    else:
        print("[SKIP] 服务级与项目级池均无 version_bugs.json，跳过 bug_trend（趋势统计）")


def stage_report(args):
    workspace, analytics_root, report_root = resolve_paths(args)

    services = list(args.services or ([args.service] if args.service else []))

    # 1) 综合报告（仅多服务聚合时触发）
    combined_out = None
    if len(services) >= 2:
        combined_out = args.out or os.path.join(
            report_root, "_综合",
            f"综合比对分析报告_{'_'.join(services)}_{datetime.now().strftime('%Y%m%d')}.html")
        os.makedirs(os.path.dirname(combined_out), exist_ok=True)
        run_py("gen_combined_report", "--services", *services,
               "--analytics-root", analytics_root, "--report-root", report_root,
               "--out", combined_out)

    # 2) P1 用例注入（可选）
    if args.p1_data_file:
        target = args.p1_report or combined_out
        if not target:
            print("[WARN] --p1-data-file 需要注入目标：--p1-report 或 ≥2 服务的综合报告")
        elif not os.path.isfile(target):
            print(f"[ERROR] 注入目标报告不存在: {target}")
            sys.exit(1)
        else:
            run_py("gen_p1_cases", "--report", target, "--data-file", args.p1_data_file)


def main():
    global SCRIPT_TIMEOUT, GIT_TIMEOUT
    ap = argparse.ArgumentParser(
        description="Code Diff Analyzer 流水线统一入口（编排 4 个固化脚本）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # 阶段
    ap.add_argument("--stage", choices=["analyze", "score", "report", "all"],
                    default="all", help="执行阶段（默认 all=analyze→score→report）")
    # 服务
    ap.add_argument("--service", help="单服务名")
    ap.add_argument("--services", nargs="+", help="多服务名（综合报告用）")
    # 路径
    ap.add_argument("--workspace", help="工作区根目录（缺省取 $WORKSPACE 或 cwd）")
    ap.add_argument("--analytics-root", help="覆盖 diff-analytics 根目录")
    ap.add_argument("--report-root", help="覆盖 report/code-diff 根目录")
    # analyze 阶段
    ap.add_argument("--source-tag", help="起始版本标签（记录用 / git 分支）")
    ap.add_argument("--target-tag", help="目标版本标签（记录用 / git 分支）")
    ap.add_argument("--repo-url", help="git 仓库地址（提供则浅克隆）")
    ap.add_argument("--clone-dir", help="克隆目标目录（缺省 {workspace}/src/{service}）")
    ap.add_argument("--git-depth", type=int, default=100, help="浅克隆历史深度（默认 100）")
    ap.add_argument("--allow-missing-metrics", action="store_true",
                    help="analyze 交接产物(service_metrics.json)缺失时不阻断（手动 / 开发豁免通道）")
    ap.add_argument("--timeout", type=int, default=SCRIPT_TIMEOUT,
                    help="单个子脚本执行超时秒数（默认 %d）" % SCRIPT_TIMEOUT)
    ap.add_argument("--git-timeout", type=int, default=GIT_TIMEOUT,
                    help="git clone 超时秒数（默认 %d）" % GIT_TIMEOUT)
    # score 阶段
    ap.add_argument("--xlsx", help="TAPD Bug 导出 Excel（bug_correlate 输入）")
    ap.add_argument("--trend-out", help="Bug 趋势报告输出路径（缺省自动生成）")
    # report 阶段
    ap.add_argument("--out", help="综合报告输出路径（缺省自动生成）")
    ap.add_argument("--p1-data-file", help="P1 用例 JSON 文件（gen_p1_cases 输入）")
    ap.add_argument("--p1-report", help="P1 用例注入目标报告（单服务时需显式指定）")
    args = ap.parse_args()

    SCRIPT_TIMEOUT = args.timeout
    GIT_TIMEOUT = args.git_timeout

    if args.stage == "analyze":
        stage_analyze(args)
    elif args.stage == "score":
        stage_score(args)
    elif args.stage == "report":
        stage_report(args)
    else:  # all
        stage_analyze(args)
        stage_score(args)
        stage_report(args)

    print("\n[DONE] 流水线阶段 '%s' 执行完成。" % args.stage)


if __name__ == "__main__":
    cdx_errors.guard(main)
