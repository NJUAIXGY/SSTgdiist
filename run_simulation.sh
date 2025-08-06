#!/bin/bash

# ==============================================================================
# SST/Macro Hybrid Miranda Mesh Simulation Run Script
# ==============================================================================
#
# 功能:
#   - 运行混合Miranda网格网络系统的SST仿真
#   - 支持选择不同的网络拓扑 (mesh 或 torus)
#   - 清理旧的统计数据
#   - 自动执行SST仿真
#
# 使用方法:
#   ./run_simulation.sh [topology]
#
#   参数:
#     topology: 'mesh' 或 'torus' (可选, 默认为 'mesh')
#
# 作者: AI Assistant
# 版本: 2.0
# 日期: 2025年8月6日
#
# ==============================================================================

# --- 配置 ---
# SST核心可执行文件路径 (如果不在系统PATH中，请指定)
SST_CORE_EXEC="sst"

# 核心仿真Python脚本路径
SIMULATION_SCRIPT="02_Core_Systems/hybrid_miranda_mesh.py"

# 统计数据输出目录
STATS_DIR="02_Core_Systems/statistics_output"

# --- 脚本逻辑 ---

# 函数: 打印彩色标题
print_header() {
    echo "=============================================================================="
    echo "    SST Hybrid Miranda Mesh Simulation"
    echo "=============================================================================="
}

# 函数: 打印用法
print_usage() {
    echo "Usage: $0 [topology]"
    echo "  topology: 'mesh' or 'torus' (default: mesh)"
    echo ""
}

# 1. 参数解析
TOPOLOGY="mesh" # 默认拓扑
if [ "$1" == "torus" ]; then
    TOPOLOGY="torus"
elif [ "$1" == "mesh" ]; then
    TOPOLOGY="mesh"
elif [ -n "$1" ]; then
    echo "错误: 无效的拓扑 '$1'"
    print_usage
    exit 1
fi

# 2. 打印启动信息
print_header
echo "🚀 开始仿真..."
echo "   - 拓扑: ${TOPOLOGY}"
echo "   - 仿真脚本: ${SIMULATION_SCRIPT}"
echo ""

# 3. 检查SST核心是否存在
if ! command -v ${SST_CORE_EXEC} &> /dev/null; then
    echo "❌ 错误: SST核心 '${SST_CORE_EXEC}' 未找到。"
    echo "   请确保SST已安装并且sst命令在您的系统PATH中。"
    exit 1
fi
echo "✅ SST核心已找到: $(command -v ${SST_CORE_EXEC})"

# 4. 检查仿真脚本是否存在
if [ ! -f "${SIMULATION_SCRIPT}" ]; then
    echo "❌ 错误: 仿真脚本 '${SIMULATION_SCRIPT}' 未找到。"
    exit 1
fi
echo "✅ 仿真脚本已找到: ${SIMULATION_SCRIPT}"

# 5. 清理旧的统计数据
if [ -d "${STATS_DIR}" ]; then
    echo "🧹 清理旧的统计数据目录: ${STATS_DIR}"
    rm -rf "${STATS_DIR}"
fi
mkdir -p "${STATS_DIR}"
echo "✅ 已创建新的统计数据目录: ${STATS_DIR}"
echo ""

# 6. 执行SST仿真
echo "🔥 执行SST仿真... (这可能需要一些时间)"
echo "------------------------------------------------------------------------------"

# 构建SST命令
SST_COMMAND="${SST_CORE_EXEC} --model-options=\"--topo=${TOPOLOGY}\" ${SIMULATION_SCRIPT}"

# 打印将要执行的命令
echo "   执行命令: ${SST_COMMAND}"
echo "------------------------------------------------------------------------------"

# 运行命令
eval ${SST_COMMAND}

# 检查退出状态
if [ $? -eq 0 ]; then
    echo "------------------------------------------------------------------------------"
    echo "✅ 仿真成功完成!"
    echo "📊 统计数据已生成在: ${STATS_DIR}"
    echo "🎉 任务结束"
    echo "=============================================================================="
else
    echo "------------------------------------------------------------------------------"
    echo "❌ 错误: 仿真失败。"
    echo "   请检查上面的错误信息。"
    echo "=============================================================================="
    exit 1
fi

exit 0
