# Code Diff Analyzer 流水线执行镜像
# 构建上下文：本目录（scripts/）
#   docker build -t diff-analyzer:v1 .
#   docker run --rm -v $PWD/data:/workspace diff-analyzer:v1 --stage all \
#       --service portal-backend --xlsx /workspace/bug.xlsx
#
# 设计原则：
#   - LLM 语义分析（Step 1-7）不在镜像内做，只消费其落盘的 service_metrics.json；
#   - git 仅用于 analyze 阶段的可选浅克隆（历史深度受限，避免大仓拖慢流水线）；
#   - 只装 openpyxl 一个第三方依赖，其余子脚本纯标准库。

FROM python:3.11-slim

WORKDIR /app

# 先装依赖（利用层缓存，脚本变更不触发重装）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝固化脚本 + 统一入口
COPY bug_correlate.py bug_trend.py gen_combined_report.py gen_p1_cases.py pipeline_wrapper.py ./

# git 用于 analyze 阶段的浅克隆
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# 默认挂载点：宿主机 diff-analytics / 报告产物
VOLUME ["/workspace"]

ENTRYPOINT ["python", "pipeline_wrapper.py"]
