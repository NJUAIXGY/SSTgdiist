#!/usr/bin/env bash
# SnnDL 安装脚本（兼容入口）

set -euo pipefail

echo "正在安装 SnnDL（推荐走 sst-elements 的标准构建流程）..."

# 确保在正确的目录
cd "$(dirname "$0")"

echo "编译..."
make -j"${MAKE_JOBS:-4}"

echo "安装..."
make install

echo ""
echo "SnnDL 安装完成。若 install 失败（权限/前缀问题），请先在 sst-elements 顶层重新 configure 指定 prefix，或使用 sudo make install。"
