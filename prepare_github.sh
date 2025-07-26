#!/bin/bash

# GitHub 仓库准备脚本
# 为项目上传到GitHub做最后准备

echo "=========================================="
echo "  准备Miranda CPU Mesh System GitHub仓库"
echo "=========================================="
echo ""

# 检查当前目录
if [ ! -f "README.md" ]; then
    echo "❌ 错误：请在项目根目录运行此脚本"
    exit 1
fi

echo "🔧 准备GitHub仓库文件..."

# 替换主README为GitHub版本
if [ -f "README_GITHUB.md" ]; then
    echo "📝 更新主README文件为GitHub版本..."
    cp README.md README_LOCAL.md
    cp README_GITHUB.md README.md
    echo "✓ README已更新为GitHub版本"
fi

# 初始化Git仓库（如果还没有）
if [ ! -d ".git" ]; then
    echo "🎯 初始化Git仓库..."
    git init
    echo "✓ Git仓库已初始化"
else
    echo "ℹ️  Git仓库已存在"
fi

# 检查Git配置
echo ""
echo "🔍 检查Git配置..."
git_user=$(git config user.name 2>/dev/null)
git_email=$(git config user.email 2>/dev/null)

if [ -z "$git_user" ] || [ -z "$git_email" ]; then
    echo "⚠️  Git用户信息未配置，请设置："
    echo "   git config --global user.name '您的姓名'"
    echo "   git config --global user.email '您的邮箱'"
    echo ""
fi

# 添加所有文件到Git
echo "📦 添加项目文件到Git..."
git add .

# 检查状态
echo ""
echo "📊 Git状态："
git status --short

# 创建初始提交
echo ""
echo "💾 创建初始提交..."
if git commit -m "Initial commit: Miranda CPU Mesh System

🚀 项目特点:
- 4×4 Miranda CPU网格系统仿真
- 完整的SST框架集成
- 多种基准测试工作负载
- 丰富的分析工具
- 中英文技术文档

📁 项目结构:
- 01_Documentation: 技术文档和报告
- 02_Core_Systems: 核心仿真系统
- 03_Experimental_Systems: 实验性版本
- 04_Analysis_Tools: 数据分析工具
- 05_Test_Systems: 测试和验证
- 06_Results_Data: 仿真结果数据
- 07_Legacy_Experiments: 早期实验

🎯 主要成果:
- cpu_mesh_simplified.py: 稳定的主系统
- 完整的技术文档 (中/英文)
- 专业的项目组织结构
- 即用的分析工具链"; then
    echo "✓ 初始提交已创建"
else
    echo "ℹ️  提交已存在或无更改"
fi

echo ""
echo "🌐 GitHub上传指南："
echo "=========================================="
echo ""
echo "1️⃣  在GitHub上创建新仓库："
echo "   • 访问: https://github.com/new"
echo "   • 仓库名: miranda-cpu-mesh-system"
echo "   • 描述: Miranda CPU Mesh System - SST Framework Based Multi-core Simulation"
echo "   • 选择: Public (推荐) 或 Private"
echo "   • 不要初始化README、.gitignore或LICENSE（我们已经有了）"
echo ""

echo "2️⃣  连接本地仓库到GitHub："
echo "   git remote add origin https://github.com/YOUR_USERNAME/miranda-cpu-mesh-system.git"
echo ""

echo "3️⃣  推送代码到GitHub："
echo "   git branch -M main"
echo "   git push -u origin main"
echo ""

echo "4️⃣  验证上传："
echo "   • 检查所有文件是否已上传"
echo "   • 验证README显示正确"
echo "   • 确认项目结构完整"
echo ""

echo "📋 项目统计："
total_files=$(find . -type f ! -path './.git/*' | wc -l)
python_files=$(find . -name "*.py" ! -path './.git/*' | wc -l)
doc_files=$(find . -name "*.md" -o -name "*.pdf" ! -path './.git/*' | wc -l)

echo "   • 总文件数: $total_files"
echo "   • Python文件: $python_files"  
echo "   • 文档文件: $doc_files"
echo ""

echo "🎉 GitHub仓库准备完成！"
echo ""
echo "💡 提示："
echo "   • 记得将README中的YOUR_USERNAME替换为您的GitHub用户名"
echo "   • 可以在GitHub仓库设置中添加主题标签: sst, simulation, cpu, mesh, hpc"
echo "   • 考虑添加GitHub Actions进行自动化测试"
echo ""

echo "🚀 准备就绪！现在可以推送到GitHub了！"
