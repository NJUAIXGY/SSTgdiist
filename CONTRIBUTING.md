# Contributing to Miranda CPU Mesh System

感谢您对本项目的关注！我们欢迎各种形式的贡献。

## 🤝 如何贡献

### 报告Bug
如果您发现了bug，请：
1. 检查[Issues](https://github.com/YOUR_USERNAME/miranda-cpu-mesh-system/issues)确认是否已被报告
2. 创建新的Issue，包含：
   - 详细的问题描述
   - 重现步骤
   - 期望行为
   - 实际行为
   - 系统环境信息

### 功能请求
对于新功能建议：
1. 先在Issues中讨论您的想法
2. 说明功能的用途和必要性
3. 如可能，提供设计思路

### 代码贡献

#### 准备工作
```bash
# Fork并克隆仓库
git clone https://github.com/YOUR_USERNAME/miranda-cpu-mesh-system.git
cd miranda-cpu-mesh-system

# 创建开发分支
git checkout -b feature/your-feature-name
```

#### 开发规范
1. **代码风格**
   - Python代码遵循PEP 8
   - 使用有意义的变量和函数名
   - 添加适当的注释

2. **文档**
   - 更新相关的README文件
   - 为新功能添加使用示例
   - 保持中英文文档同步

3. **测试**
   - 确保现有测试通过
   - 为新功能添加测试用例
   - 在多种配置下测试

#### 提交流程
```bash
# 提交更改
git add .
git commit -m "Add: 简短描述新功能"

# 推送到您的fork
git push origin feature/your-feature-name

# 创建Pull Request
```

### Pull Request指南

#### PR标题格式
- `Add: 新增功能描述`
- `Fix: 修复问题描述`
- `Update: 更新内容描述`
- `Docs: 文档相关更改`

#### PR描述应包含
- [ ] 更改内容的详细说明
- [ ] 相关Issue编号（如有）
- [ ] 测试情况说明
- [ ] 是否需要更新文档

## 📋 开发环境设置

### 依赖安装
```bash
# SST框架（根据您的系统）
# Ubuntu/Debian
sudo apt-get install sst-core sst-elements

# 或从源码编译
# 请参考SST官方文档
```

### 代码质量检查
```bash
# Python代码检查
flake8 --max-line-length=88 *.py
black --line-length=88 *.py

# 运行测试
cd 05_Test_Systems/
python -m pytest
```

## 🎯 贡献领域

我们特别欢迎以下方面的贡献：

### 核心系统
- 新的CPU模型和配置
- 网络拓扑优化
- 内存层次结构改进

### 分析工具
- 新的性能指标
- 数据可视化功能
- 自动化报告生成

### 测试和验证
- 新的基准测试
- 回归测试用例
- 性能验证脚本

### 文档和示例
- 使用教程
- 最佳实践指南
- API文档完善

## 🚀 发布流程

### 版本号规则
- 主版本号：重大架构变更
- 次版本号：新功能添加
- 修订号：Bug修复

### 发布检查清单
- [ ] 所有测试通过
- [ ] 文档已更新
- [ ] 版本号已更新
- [ ] 变更日志已更新

## 💡 开发提示

### 代码组织
```
项目结构说明：
├── 02_Core_Systems/     # 核心仿真系统
├── 04_Analysis_Tools/   # 分析和可视化工具
├── 05_Test_Systems/     # 测试用例和验证
└── 01_Documentation/    # 文档和示例
```

### 调试技巧
1. 使用SST的调试输出：`sst --verbose cpu_mesh_simplified.py`
2. 检查统计输出文件的格式和内容
3. 使用小规模配置进行快速测试

### 性能优化
1. 避免在内循环中创建重对象
2. 合理设置仿真参数
3. 使用分析工具识别瓶颈

## 📞 联系我们

- **讨论**: 使用GitHub Discussions
- **问题**: 创建GitHub Issues  
- **紧急联系**: your.email@example.com

## 🙏 致谢

感谢所有贡献者的努力！您的贡献使这个项目变得更好。

特别感谢：
- SST开发团队提供的优秀仿真框架
- Miranda CPU组件的开发者
- 所有提供反馈和建议的用户

---

再次感谢您的贡献！🎉
