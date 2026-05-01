# SST‑SnnDL 远程服务器环境与部署指南

本指南用于将本项目迁移并在远程服务器上可重复构建、运行与分析。按本文档完成后，可运行 `sst_dram_si/mesh_template`（4×4 mesh 回归/论文口径）、DRAM-SI 与映射框架等组件。

> 约定变量（可按需修改）：
> - `SST_HOME`: 项目根目录（建议 `~/SST` 或实际克隆路径）
> - `SST_INSTALL_PREFIX`: SST 安装前缀（建议 `"$SST_HOME/sst_install"`）

---

## 1. 系统与工具链要求
- 操作系统：Ubuntu 20.04/22.04、Debian 11/12、RHEL/CentOS 8/9（x86_64）。
- 编译器：GCC ≥ 9（支持 C++17），或 Clang ≥ 12。
- 构建工具：make、autoconf、automake、libtool、m4、pkg-config、bash、tar、gzip。
- MPI（可选但推荐）：OpenMPI ≥ 4.0（或 MPICH ≥ 3.3）。
- Python：Python 3.8+，pip/venv 可用。
- 资源建议：≥ 8 GB RAM，≥ 8 CPU 线程用于并行编译；磁盘 ≥ 5 GB。

## 2. 迁移项目到远程服务器
- 方式一（推荐）：使用 rsync（保留权限，忽略 `.git` 可加速）
  ```bash
  rsync -avz --exclude .git <local_path>/SST/ <user>@<host>:~/SST/
  ```
- 方式二：远端直接 git clone（需网络可用）
  ```bash
  ssh <user>@<host>
  git clone <repo_url> ~/SST
  ```

## 3. 系统依赖安装

### 3.1 Ubuntu / Debian
```bash
sudo apt-get update
sudo apt-get install -y build-essential gcc g++ make autoconf automake libtool m4 pkg-config \
    python3 python3-venv python3-pip \
    openmpi-bin libopenmpi-dev   # 若使用 MPICH：sudo apt-get install -y mpich libmpich-dev
```

### 3.2 RHEL / CentOS / Rocky / AlmaLinux
```bash
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y gcc gcc-c++ make autoconf automake libtool m4 pkgconfig \
    python3 python3-venv python3-pip \
    openmpi openmpi-devel  # 或：mpich mpich-devel
# OpenMPI 在某些系统需：module load mpi/openmpi  或 export PATH=/usr/lib64/openmpi/bin:$PATH
```

> 无 sudo 的 HPC/集群环境：优先使用已有的 `module load gcc openmpi python`。若无模块，请联系管理员开通，或使用自建前缀安装工具链。

## 4. 目录布局与环境变量
```bash
# 进入项目根
export SST_HOME=~/SST
# 安装前缀建议设为项目内目录，便于隔离
export SST_INSTALL_PREFIX="$SST_HOME/sst_install"
# 运行期需要添加可执行与库路径
export PATH="$SST_INSTALL_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$SST_INSTALL_PREFIX/lib:$SST_INSTALL_PREFIX/lib64:${LD_LIBRARY_PATH}"
```

可将以上 export 追加到 `~/.bashrc`，便于长期使用。

## 5. 从源码构建（使用仓库随附源码）
本仓库已包含 `sst-core` 与 `sst-elements` 源码于 `sst_workspace/` 下，避免外网下载。

### 5.1 构建 sst-core
```bash
cd "$SST_HOME/sst_workspace/sst-core"
./configure --prefix="$SST_INSTALL_PREFIX"
make -j"$(nproc)"
make install
```

### 5.2 构建 sst-elements（指向刚安装的 sst-core）
```bash
cd "$SST_HOME/sst_workspace/sst-elements"
./configure --prefix="$SST_INSTALL_PREFIX" --with-sst-core="$SST_INSTALL_PREFIX"
make -j"$(nproc)"
make install
```

### 5.3 构建/安装 SnnDL 组件（可重复执行）
```bash
cd "$SST_HOME/sst_workspace/sst-elements/src/sst/elements/SnnDL"
make clean && make -j"$(nproc)" && make install
# 如系统采用动态库缓存，且拥有 root，可执行：sudo ldconfig
# 若无 sudo，请确保已正确设置 LD_LIBRARY_PATH 指向 $SST_INSTALL_PREFIX/lib*
```

### 5.4 构建（可选）实验性「神经元映射框架」
```bash
cd "$SST_HOME/experimental_features/neuron_mapping_framework"
make all           # 编译所有示例与测试
make run-demo      # 运行 demo
make run-test      # 运行工作流集成测试
make run-benchmark # 运行基准（可选：make run-benchmark-large）
make test-compile  # 仅做“能否编译”检查
```

## 6. 运行与验证

### 6.1 验证 SST 与元素安装
```bash
which sst
sst --version
sst-info | rg SnnDL   # 若无 rg，可用：sst-info | grep -i SnnDL
```
期望能看到 `SnnDL` 相关元素已注册。

### 6.2 运行 mesh_template 4×4 mesh 回归（推荐：step-limited）
```bash
cd "$SST_HOME/sst_dram_si"
./tools/run_mesh_with_time.sh
```
- 运行结束后，会在 `sst_dram_si/outputs_large/...` 下生成一次运行目录，包含：`mesh_stats.csv`、`effective_config.json`、`meta.json`、`essential_summary_mesh.json`、`validation.log`。
- 论文/回归口径默认要求 `MESH_MAX_STEPS>0`（step-limited）；避免使用引擎级 `stop-at` 作为停止条件。

### 6.3 结果汇总与验收（mesh_template）
`run_mesh_with_time.sh` 会自动生成 summary 与验收日志；如需手动查看：
```bash
cd "$SST_HOME/sst_dram_si"
# 查看权威使用手册
sed -n '1,80p' "docs/mesh_template_guide_20251122-000250.md"

# 对某次 RUN_DIR 手动汇总/验收（RUN_DIR 为 outputs_large 下的具体目录）
python3 "tools/compute_essential_summary_mesh.py" --run-dir "RUN_DIR"
python3 "tools/validate_essential_summary_mesh.py" --run-dir "RUN_DIR" --profile "paper" --strict
```

### 6.4 DRAM-SI（可选）
仓库包含 `sst_dram_si/`，用于 DRAM-SI 实验脚本与统计收集：
```bash
# 示例（根据本地脚本调整）：
# sst sst_dram_si/test_dram_si_single_pe.py
# 或根据 presets 使用工具脚本（如存在）：
# python3 sst_dram_si/tools/apply_preset.py gas_cacheline_strict --show-diff
```

## 7. 常见问题与排障
- 找不到 `sst` 或 `lib`：
  - 确认 `PATH` 与 `LD_LIBRARY_PATH` 已包含 `$SST_INSTALL_PREFIX/bin` 和 `$SST_INSTALL_PREFIX/lib*`。
  - 如具备 root，执行 `sudo ldconfig` 以刷新动态库缓存。
- `configure` 报错找不到编译器/工具：
  - 确认已安装 `gcc g++ make autoconf automake libtool m4 pkg-config`。
  - HPC 环境使用 `module load gcc openmpi`。
- MPI 相关测试无法运行或卡住：
  - 先验证本地串行可运行（不使用 `mpirun`）。
  - 若需多进程，确认已安装且加载 OpenMPI/MPICH，并在作业队列系统（如 Slurm）中使用正确的 `srun`/`mpirun`。
- 编译失败（C++17）：
  - 升级编译器至 GCC 9+ 或 Clang 12+。
- Python 模块缺失：
  - `pip install pandas numpy`，必要时添加 `-i` 指定镜像源。

## 8. 环境持久化（可选）
将以下内容追加到 `~/.bashrc`：
```bash
export SST_HOME=~/SST
export SST_INSTALL_PREFIX="$SST_HOME/sst_install"
export PATH="$SST_INSTALL_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$SST_INSTALL_PREFIX/lib:$SST_INSTALL_PREFIX/lib64:${LD_LIBRARY_PATH}"
```
然后执行 `source ~/.bashrc`。

## 9. 参考运行速查（Cheat Sheet）
```bash
# 构建 core 与 elements
cd "$SST_HOME/sst_workspace/sst-core" && ./configure --prefix="$SST_INSTALL_PREFIX" && make -j4 && make install
cd "$SST_HOME/sst_workspace/sst-elements" && ./configure --prefix="$SST_INSTALL_PREFIX" --with-sst-core="$SST_INSTALL_PREFIX" && make -j4 && make install

# 仅重建 SnnDL 组件
cd "$SST_HOME/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make clean && make -j4 && make install

# 运行（推荐：mesh_template step-limited 回归）
cd "$SST_HOME/sst_dram_si" && ./tools/run_mesh_with_time.sh

# 映射框架
cd "$SST_HOME/experimental_features/neuron_mapping_framework" && make test-compile && make run-demo
```

## 10. 版本与兼容性说明
- 本指南基于仓库内置的 `sst-core` 与 `sst-elements` 源码版本测试通过。
- 统一以 `sst_dram_si/test_mesh_4x4.py` + `sst_dram_si/mesh_template/` 作为配置入口与回归口径；新增配置建议在 mesh_template 体系内派生并保持可复现。
- 不建议在未充分验证的情况下替换外部 SST 版本或修改核心接口。

---

如需在远程服务器上进行批量实验或接入队列系统（Slurm/PBS），可在上述命令外层包裹作业脚本；如需进一步的性能统计，请在仿真脚本中启用 `sst.enableAllStatisticsForAllComponents()` 并结合仓库自带分析工具使用。
