#!/bin/bash

# Miranda CPU Mesh System - 快速启动脚本
# 创建日期: 2024-07-25

echo "========================================"
echo "  Miranda CPU Mesh System 快速启动"
echo "========================================"
echo ""

# 检查当前目录
if [ ! -d "02_Core_Systems" ]; then
    echo "❌ 错误：请在 Miranda_CPU_Mesh_Project 目录中运行此脚本"
    exit 1
fi

echo "🚀 可用的系统："
echo "  [1] cpu_mesh_simplified.py  - 主要系统（推荐）"
echo "  [2] cpu_mesh_miranda.py     - 完整系统"
echo "  [3] 查看技术文档"
echo "  [4] 分析历史结果"
echo "  [5] 查看项目结构"
echo ""

read -p "请选择要运行的选项 [1-5]: " choice

case $choice in
    1)
        echo "🎯 启动简化Miranda CPU网格系统..."
        echo "   - 4x4网格，16个CPU核心"
        echo "   - 多种工作负载基准测试"
        echo "   - 分布式内存系统"
        echo ""
        cd 02_Core_Systems/
        sst cpu_mesh_simplified.py
        ;;
    2)
        echo "🎯 启动完整Miranda CPU网格系统..."
        echo "   - 完整memHierarchy实现"
        echo "   - 复杂内存层次结构"
        echo ""
        cd 02_Core_Systems/
        sst cpu_mesh_miranda.py
        ;;
    3)
        echo "📚 打开技术文档目录..."
        cd 01_Documentation/
        ls -la
        echo ""
        echo "文档列表："
        echo "  - 技术报告_Miranda_CPU_Mesh系统.pdf (中文)"
        echo "  - Miranda_CPU_Mesh_Technical_Report_EN.pdf (英文)"
        ;;
    4)
        echo "📊 查看历史仿真结果..."
        cd 06_Results_Data/
        ls -la *.csv
        echo ""
        echo "可用的分析工具："
        cd ../04_Analysis_Tools/
        ls -la analyze_*.py
        ;;
    5)
        echo "📁 项目目录结构："
        tree . -L 2 2>/dev/null || ls -la
        ;;
    *)
        echo "❌ 无效选择"
        exit 1
        ;;
esac

echo ""
echo "✅ 操作完成！"
echo "💡 提示：查看 README.md 获取更多信息"
