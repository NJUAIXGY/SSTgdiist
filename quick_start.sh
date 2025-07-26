#!/bin/bash

# Miranda CPU Mesh System - 快速启动脚本 (极简版)
# 创建日期: 2024-07-25
# 更新日期: 2025-07-26 - 极简版更新

echo "========================================"
echo "  Miranda CPU Mesh System 快速启动"
echo "          (极简版 v1.1.0)"
echo "========================================"
echo ""

# 检查当前目录
if [ ! -d "02_Core_Systems" ]; then
    echo "❌ 错误：请在 SSTgdiist 项目目录中运行此脚本"
    exit 1
fi

# 检查SST是否安装
if ! command -v sst &> /dev/null; then
    echo "❌ 错误：未找到 SST 命令"
    echo "   请确保已正确安装 SST Core"
    exit 1
fi

echo "🚀 可用的核心系统："
echo "  [1] cpu_mesh_simplified.py  - 简化版系统（推荐）"
echo "  [2] cpu_mesh_miranda.py     - 完整版系统"
echo ""
read -p "请选择要运行的系统 [1-2]: " choice

case $choice in
    1)
        echo ""
        echo "🎯 正在运行简化版CPU网格系统..."
        echo "📍 文件: 02_Core_Systems/cpu_mesh_simplified.py"
        echo "⏱️  这可能需要几分钟，请耐心等待..."
        echo ""
        cd 02_Core_Systems/
        sst cpu_mesh_simplified.py
        ;;
    2)
        echo ""
        echo "🎯 正在运行完整版CPU网格系统..."
        echo "📍 文件: 02_Core_Systems/cpu_mesh_miranda.py"
        echo "⏱️  这可能需要几分钟，请耐心等待..."
        echo ""
        cd 02_Core_Systems/
        sst cpu_mesh_miranda.py
        ;;
    *)
        echo "❌ 无效选择，退出"
        exit 1
        ;;
esac

echo ""
echo "✅ 仿真完成！"
echo ""
echo "📊 查看结果："
echo "   - 统计文件通常以 .txt 或 .csv 结尾"
echo "   - 使用 'ls -la *.txt *.csv *.out' 查看生成的文件"
echo ""
echo "📚 更多信息："
echo "   - README.md - 项目说明"
echo "   - README_SIMPLIFIED.md - 详细使用指南"
echo "   - 01_Documentation/ - 技术文档"
echo ""
echo "🎯 项目特点："
echo "   - 4×4 Miranda CPU网格系统"
echo "   - 16个CPU核心，40GiB/s网络带宽"
echo "   - 支持STREAM、GUPS等基准测试"
echo ""
