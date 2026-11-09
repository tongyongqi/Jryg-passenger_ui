#!/bin/bash
# ===========================================
# JRYG 接口测试 - GitHub Actions 定时触发脚本
# 由 macOS crontab 每天定时调用，通过 API 触发 GitHub Actions
# ===========================================

# GitHub Token 从环境变量读取（不硬编码在脚本中）
GITHUB_TOKEN="${GITHUB_TOKEN}"
REPO="tongyongqi/Jryg-passenger_ui"
WORKFLOW="api-test.yml"
REF="main"

# 触发 workflow
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches" \
  -d "{\"ref\":\"${REF}\"}")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)

if [ "$HTTP_CODE" = "204" ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') - GitHub Actions 触发成功"
else
  echo "$(date '+%Y-%m-%d %H:%M:%S') - GitHub Actions 触发失败 (HTTP $HTTP_CODE)"
  echo "$RESPONSE"
fi
