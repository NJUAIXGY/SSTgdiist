# 贡献指南 - Miranda CPU Mesh System (精简版)

欢迎为Miranda CPU Mesh System项目做出贡献！本项目已经过精简，专注于核心功能。

## 🎯 项目精简状态

本项目已于2025年7月26日进行了大幅精简：
- **代码减少**: 从34个Python文件减少到11个 (68%减少)
- **结构清晰**: 保留核心系统和重要工具
- **文档完善**: 新增精简版使用指南

## 📋 贡献类型

### 欢迎的贡献
1. **Bug修复** - 核心系统和分析工具的问题修复
2. **文档改进** - 使用指南、技术文档的完善
3. **性能优化** - 仿真性能和分析效率提升
4. **新功能** - 基于现有核心系统的扩展

### 不建议的贡献
1. **实验性代码** - 已删除实验性系统，请勿重新添加
2. **重复功能** - 避免创建功能重叠的文件
3. **复杂变体** - 保持系统简洁性

## 🛠️ 开发流程

### 1. 项目设置
```bash
# 克隆项目
git clone https://github.com/NJUAIXGY/SSTgdiist.git
cd SSTgdiist

# 检查当前结构
./quick_start.sh
```

### 2. 开发规范

#### 代码风格
- Python代码遵循PEP 8规范
- 使用有意义的变量和函数名
- 添加必要的注释和文档字符串

#### 文件组织
```
SSTgdiist/
├── 02_Core_Systems/      # 仅限核心系统
├── 04_Analysis_Tools/    # 通用分析工具
├── 05_Test_Systems/      # 基础测试
└── 01_Documentation/     # 完整文档
```

### 3. 提交规范

#### 分支命名
- `feature/功能名称` - 新功能开发
- `bugfix/问题描述` - 问题修复
- `docs/文档更新` - 文档改进

#### 提交信息
```
类型(范围): 简短描述

详细描述 (可选)

关联issue: #123
```

类型示例：
- `feat`: 新功能
- `fix`: 问题修复
- `docs`: 文档更新
- `perf`: 性能优化
- `refactor`: 代码重构

### 4. Pull Request流程

1. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **开发和测试**
   ```bash
   # 确保核心系统正常工作
   sst 02_Core_Systems/cpu_mesh_simplified.py
   
   # 运行基础测试
   sst 05_Test_Systems/minimal_test.py
   ```

3. **提交更改**
   ```bash
   git add .
   git commit -m "feat(core): 添加新功能描述"
   git push origin feature/your-feature-name
   ```

4. **创建Pull Request**
   - 使用清晰的标题和描述
   - 关联相关的issue
   - 包含测试结果截图

## 📝 代码审查标准

### 核心系统修改
- 必须保证向后兼容性
- 需要详细的测试验证
- 更新相关文档

### 分析工具修改
- 确保输出格式一致
- 添加错误处理
- 提供使用示例

### 测试系统修改
- 保持简单性
- 确保快速执行
- 添加注释说明

## 🧪 测试要求

### 基础测试
在提交前运行以下测试：

```bash
# 1. 最小化测试
cd 05_Test_Systems/
sst minimal_test.py

# 2. 简单CPU系统测试
sst simple_cpu_system.py

# 3. 核心系统测试
cd ../02_Core_Systems/
sst cpu_mesh_simplified.py
```

### 分析工具测试
```bash
cd 04_Analysis_Tools/
python analyze_results.py
python project_summary.py
```

## 📚 文档要求

### 代码文档
- 在文件头部添加功能描述
- 为复杂函数添加docstring
- 更新相关的README文件

### 技术文档
- 新功能需更新技术报告
- 重大修改需更新架构图
- 保持中英文文档同步

## 🚀 发布流程

### 版本号规范
- 主版本号：重大架构变更
- 次版本号：新功能添加
- 修订版本号：问题修复

### 发布检查清单
- [ ] 所有测试通过
- [ ] 文档已更新
- [ ] 性能无显著下降
- [ ] 向后兼容性检查

## 💬 沟通渠道

### 问题报告
- 使用GitHub Issues
- 提供详细的复现步骤
- 包含系统环境信息

### 功能讨论
- 在issue中讨论设计
- 参考现有架构
- 考虑精简原则

## 📄 许可证

本项目采用MIT许可证，贡献的代码将采用相同许可证。

## 🙏 致谢

感谢所有贡献者对项目精简和改进的支持！

---

💡 **提示**: 在开始贡献前，建议先阅读 `README_SIMPLIFIED.md` 了解精简后的项目结构。
