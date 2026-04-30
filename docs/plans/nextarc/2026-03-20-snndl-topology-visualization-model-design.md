# SnnDL 2D/3D 芯片拓扑可视化建模设计

## 1. 背景与目标

当前团队已经基于 `SnnDL` 搭建出两条能够代表芯片系统形态的主线：

1. `sst_dram_si/mesh_template/` 为代表的二维 mesh 芯片系统。
2. `snn3dexp/` 与 `MulticastRouter3DNative + SynapseRouteSubsystem3D + HBM-like shared stack` 为代表的三维芯片系统。

这两条主线都已经不是纸面概念，而是有真实 builder、真实组件、真实连接关系、真实运行时契约的架构模型。  
因此，如果我们要做一个“基于 SnnDL 搭建的 2D / 3D 芯片系统视觉建模”，重点不应放在优化收益、论文主张、性能数字，而应回到一个更基础但更稳定的问题：

`SnnDL 当前到底把哪些拓扑对象建进了系统里，这些对象之间的结构关系是什么，我们应该怎样把它们抽象成一套统一的可视化模型。`

本文档的目标是回答这个问题，并给出一套适合后续前端/可视化实现的统一抽象。

## 2. 分析范围与非目标

### 2.1 本文档关注的内容

本文档只关注下列“结构性”问题：

- 2D / 3D 系统中的物理节点是什么。
- 这些节点之间通过哪些端口和链路连接。
- `multicast block`、`ingress`、`core_mask` 这样的路由结构应如何被可视化理解。
- 3D memory stack 应该作为主拓扑还是 overlay 呈现。
- 如何把 2D 和 3D 都映射到同一套数据模型中。

### 2.2 本文档明确不关注的内容

本文档不讨论：

- `STORM`、`GCSS-GLIDE`、`GAS` 的收益与优化效果。
- routing policy 的优劣对比。
- thermal / physical / reliability / proxy score 的论文叙事。
- adaptive runtime、credit、band color 等运行期控制细节。
- 美术风格、颜色、动效、页面品牌语言。

换句话说，本文档只做一件事：

`为 2D/3D SnnDL 芯片系统提炼一套“拓扑可视化抽象层”。`

## 3. 现有实现中的拓扑对象

## 3.1 2D 主线中的基础对象

在 `sst_dram_si/mesh_template/build.py` 中，二维系统的 build 顺序非常清楚：

1. 先创建内存系统。
2. 再创建 `routers`。
3. 再创建 `nodes` 与 `nics`。
4. 再连接 `router-router`、`nic-router`、`spike_source-pe`。

这说明 2D 主线已经天然具备一张标准的系统图骨架：

- `PE node`
- `Router`
- `NIC`
- `Router-to-Router` 网格边
- `NIC-to-Router` 本地接入边
- 可选的 `SpikeSource`

这套骨架有两个非常重要的特点：

### 特点 A：物理拓扑与逻辑任务是分开的

`mesh_template/task_snn.py` 中的 `input_layer / hidden_layer_1 / hidden_layer_2 / output_layer`，本质上是 PE 上承载的工作负载分区，而不是芯片物理楼层或芯粒分层。  
因此，二维可视化必须把下面两层概念拆开：

- `physical topology`：谁和谁连、坐标在哪。
- `logical workload partition`：哪些 PE 被标成 input/hidden/output。

如果直接把 workload layer 画成物理层，会把现有实现误解释成“按神经网络层堆叠的硅片布局”，这并不准确。

### 特点 B：二维主线本质上是规则平面 mesh

`snndl_system/noc_multicast.py` 里 2D multicast 路由器的连边逻辑只包含：

- `east/west`
- `north/south`
- `local`

因此 2D 主视图天然适合画成：

- 平面格点图
- 或平铺的 chip tile 图

不需要在第一版里引入任何立体视图。

## 3.2 3D 主线中的基础对象

三维主线已经不只是“二维对象加一个 z 标签”，而是引入了新的拓扑实体和新的结构语义。

### 3D 基础几何

`Route3DNodeMapper.h` 已经把 3D 拓扑的几何基元定义得非常明确：

- `MeshShape3D {dim_x, dim_y, dim_z}`
- `MeshCoord3D {x, y, z}`
- `node_id <-> (x, y, z)` 双向映射
- `block_id <-> volumetric block` 编码与解码

这意味着 3D 系统的最小建模单元已经不是“线性 node_id 列表”，而是：

- 一个三维离散坐标系
- 一个规则体素网格

### 3D Router 对象

`MulticastRouter3DNative` 在组件层面新增了 3D 原生端口：

- `local`
- `north/south/east/west`
- `up/down`

同时它的路由顺序已经显式区分：

- 纵向优先的 `zxy`
- 纵向后再走 `zyx`

因此 3D router 不能再被看成 2D router 的简单皮肤替换，而应被看成一种新的拓扑节点类型：

`3D multicast-aware router`

### 3D Multicast Block 对象

3D 可视化里最容易被忽略、但其实最值得显示的，不是单条 packet path，而是 `multicast block`。

`ISynapseRoute::BlockTarget` 和 `SynapseRouteSubsystem3D` 已经把 3D blocked multicast 的结构信息组织成：

- `block_id`
- `block_z`
- `block_d`
- `ingress_node`
- `core_mask`

其含义是：

- 一个 spike 并不是对每个目标 PE 单独发一条线。
- 它先被归并到某个 3D block。
- 再为该 block 选择一个 ingress。
- 再由 router 在 block 内进行体积式传播和局部复制。

所以，3D 系统里真正适合可视化的“路由对象”，不是孤立 packet，而是：

`源节点 -> block -> ingress -> block 内传播树`

### 3D Memory Stack 对象

在 `snn3dexp/memory/hbm_stack.py` 里，3D memory 已经不是“每个 PE 一块本地内存”，而是：

- `stack`
- `channel`
- `home_xy_region`
- `node -> stack binding`
- `attach_latency_ns`

并且其 home policy 目前是 `xy_quadrant`，attach latency 与 `z` 有关。  
这说明三维系统实际上包含两张互相正交但应被关联展示的拓扑：

1. `NoC topology`
2. `Memory-home topology`

## 4. 从可视化角度看，哪些是主拓扑，哪些是 overlay

为了避免页面信息爆炸，必须先定义“主拓扑层”和“附加层”的边界。

## 4.1 应作为主拓扑展示的对象

以下对象应进入主图：

### A. PE

原因：

- 这是计算与 workload 的实际承载点。
- 2D 与 3D 都有。
- 用户理解系统时通常首先关心“芯片上有哪些 tile / node”。

建议呈现字段：

- `node_id`
- `x, y, z`
- `num_cores`
- `kind=pe`

### B. Router

原因：

- 2D / 3D 的互连形态就是通过 router 体现的。
- NoC 架构差异必须通过 router 类型显式体现。

建议呈现字段：

- `router_id`
- `router_component_type`
- `native_3d_enable`
- `vertical_route_order`

### C. Router-to-Router Links

原因：

- 这是最核心的物理拓扑边。
- 2D 与 3D 的最大差异就体现在是否存在 `up/down`。

建议边类型：

- `east`
- `west`
- `north`
- `south`
- `up`
- `down`
- `local`

### D. Mesh Shape

原因：

- `4x4x1` 和 `4x4x2` 不只是参数不同，而是视觉组织方式完全不同。
- 它决定了页面是平面图、分层图，还是立体图。

建议作为全局元数据：

- `shape.x`
- `shape.y`
- `shape.z`

## 4.2 应作为第一层 overlay 的对象

### A. Logical workload mapping

例如：

- `input_layer`
- `hidden_layer_1`
- `hidden_layer_2`
- `output_layer`

原因：

- 它很重要，但不是物理结构。
- 最适合用颜色、标签、筛选器、图层开关呈现。

### B. Multicast block

原因：

- 它是理解 `STORM + MulticastRouter` 数据面的关键。
- 但如果默认常开，会遮挡物理拓扑。

最适合的方式：

- hover 时显示 block 边界
- 选中某个 source neuron 后高亮相关 block
- 用半透明 box 或分层框显示 `w/h/d`

### C. Memory home / stack binding

原因：

- 这是 3D 系统区别于 2D per-PE memory 的关键结构。
- 但它与 NoC 是另一张关系图，不宜和主链路完全混画。

最适合的方式：

- “NoC 图 + Memory overlay”
- 选中某个 PE 时显示其 `home_stack`
- 选中某个 stack 时高亮负责区域

## 4.3 应作为第二层 overlay 或详情面板的对象

这些内容可以留到后续版本：

- `core_mask`
- `ingress_node`
- `band_color`
- `cohort_id`
- `router serialize bytes`
- `traffic_source`
- `synapse_source`
- `attach_latency`
- `vertical bandwidth proxy`

原因不是它们不重要，而是它们过于细，属于“解释某个选中对象”而不是“定义系统骨架”。

## 5. 推荐的统一拓扑抽象

浮浮酱推荐建立一套独立于具体 builder 的中间层：

`Topology IR`

它的职责不是直接模拟，也不是直接渲染，而是把 `mesh_template`、`snn3dexp`、`SnnDL route/memory` 抽成统一数据。

## 5.1 Topology IR 的分层

推荐分为 5 层：

### Layer 1: Physical Mesh

描述物理拓扑骨架：

- `shape`
- `nodes`
- `routers`
- `links`

### Layer 2: Processing Mapping

描述 PE 上承载的逻辑功能：

- `logical groups`
- `layer tags`
- `mapping policy`

### Layer 3: Multicast Topology

描述 block 与 ingress 组织方式：

- `block geometry`
- `block membership`
- `ingress selection`
- `core_mask`

### Layer 4: Memory Topology

描述 shared stack / home policy：

- `stacks`
- `channels`
- `home regions`
- `node-stack bindings`

### Layer 5: Runtime Overlay

未来再挂载：

- 热点
- 流量
- stack pressure
- vertical hop ratio

这样做的好处是：

- 2D case 只需要填前两层。
- 3D case 可以填到第四层。
- 未来做动态动画时只是在第五层加数据，不必重写前端结构。

## 5.2 建议的数据结构

下面是一版适合前后端共用的建议结构：

```json
{
  "topology_version": 1,
  "system_kind": "snndl_chip",
  "shape": { "x": 4, "y": 4, "z": 2 },
  "physical": {
    "nodes": [
      {
        "node_id": 17,
        "kind": "pe",
        "x": 1,
        "y": 0,
        "z": 1,
        "num_cores": 4
      }
    ],
    "routers": [
      {
        "router_id": 17,
        "node_id": 17,
        "component_type": "SnnDL.MulticastRouter3DNative",
        "native_3d_enable": true,
        "vertical_route_order": "zxy"
      }
    ],
    "links": [
      { "src": 0, "dst": 1, "kind": "east" },
      { "src": 0, "dst": 4, "kind": "south" },
      { "src": 0, "dst": 16, "kind": "up" },
      { "src": 0, "dst": 0, "kind": "local" }
    ]
  },
  "logical": {
    "groups": [
      { "name": "input_layer", "node_ids": [0, 1, 2, 3] }
    ]
  },
  "multicast": {
    "block_shape": { "w": 2, "h": 2, "d": 2 },
    "targets": [
      {
        "block_id": 0,
        "x0": 0,
        "y0": 0,
        "z0": 0,
        "ingress_node": 0,
        "member_node_ids": [0, 1, 4, 5, 16, 17, 20, 21]
      }
    ]
  },
  "memory": {
    "kind": "hbm_like",
    "stacks": [
      {
        "stack_id": 0,
        "home_xy_region": { "x_range": [0, 1], "y_range": [0, 1] },
        "channels_per_stack": 4
      }
    ],
    "bindings": [
      {
        "node_id": 17,
        "stack_id": 0,
        "attach_latency_ns": 4
      }
    ]
  }
}
```

## 6. 三种实现路线

## 6.1 路线 A：离线抽取 Topology IR

### 做法

- 从 `mesh_template` 与 `snn3dexp` 的 effective config / platform summary 中抽取结构数据。
- 生成标准化 `topology.json`。
- 前端只消费 `topology.json`。

### 优点

- 最稳定。
- 与 SST runtime 弱耦合。
- 最适合先做“结构视图”。
- 2D / 3D 可以走统一渲染入口。

### 缺点

- 对运行期动态事件不敏感。
- 若要画 packet 动画，后面还要补事件流。

### 结论

`这是推荐方案。`

## 6.2 路线 B：直接从 builder / SST object graph 读对象

### 做法

- 在 build 阶段拦截 `routers`、`nodes`、`links` 创建。
- 直接把对象图投给前端。

### 优点

- 与真实建图完全一致。
- 不需要再做一次抽象转换。

### 缺点

- 与具体 builder 绑定太深。
- `mesh_template` 和 `snn3dexp` 入口不同，很快会出现两套适配逻辑。
- 后续重构 builder 时可视化也会被拖着改。

### 结论

可作为内部调试工具，但不适合作为长期产品形态。

## 6.3 路线 C：运行时回放 + 动画

### 做法

- 把 packet、block、memory access、thermal overlay 都记录为事件流。
- 前端按时间轴回放。

### 优点

- 表现力最强。
- 适合做论文展示、demo、教学。

### 缺点

- 成本最高。
- 事件量巨大。
- 如果第一版直接走这条路线，极容易把“结构建模”问题拖成“时序可视化平台”。

### 结论

应作为第三阶段，而不是当前起点。

## 7. 推荐的页面视图拆分

为了既能表达结构，又不让图太乱，建议前端至少拆成 4 个视图。

## 7.1 视图一：Physical Mesh View

显示内容：

- PE
- Router
- Router-to-Router links

2D：

- 平面 tile 图或网格图

3D：

- 分层小 multiples
- 或 exploded layers

这是默认主视图。

## 7.2 视图二：Multicast Block View

显示内容：

- 选定 source 后的 `block_id`
- `ingress_node`
- block 边界
- block 内成员节点

意义：

- 这是解释 `blocked multicast` 与 `shared path` 的关键视图。

## 7.3 视图三：Memory Home View

显示内容：

- stack 区域
- node -> home stack
- attach latency 差异

意义：

- 这是解释 3D shared-stack memory 结构的关键视图。
- 也能自然支持未来的 `remote_home`、`same_xy_cross_tier` 等 overlay。

## 7.4 视图四：2D vs 3D Compare View

显示内容：

- `baseline_2d (4x4x1)` 与 `full_3d (4x4x2)` 并排
- 同一 node_id 映射方式
- 是否存在 `up/down`
- 是否存在 `stack/home overlay`

意义：

- 这是最适合第一阶段对外讲清楚“你们的 3D 到底比 2D 多了什么”的视图。

## 8. 抽取器设计建议

## 8.1 2D Extractor

输入：

- `mesh_template` 运行时配置
- `build_mesh_4x4()` 结果

输出：

- `shape = {x: mesh_size, y: mesh_size, z: 1}`
- `nodes`
- `routers`
- `links`
- `logical groups`

关键原则：

- `input_layer / hidden / output` 只写到 `logical.groups`
- 不要伪造不存在的 `up/down`
- memory 默认为 `legacy_per_pe`，可以不单独画 stack

## 8.2 3D Extractor

输入：

- `snn3dexp/platform/build_system.py::build_platform_summary()`
- `shape3d.py`
- `noc/multicast_3d.py`
- `memory/hbm_stack.py`

输出：

- `shape`
- 3D `routers`
- 3D `links`
- `memory.stacks`
- `memory.bindings`
- 可选 `logical groups`

关键原则：

- `native_3d_enable=true` 时才生成 `up/down`
- memory stack 不与 NoC 混成同一张边图
- 把 `vertical_route_order`、`multicast_block_dim_{x,y,z}` 作为元数据保留

## 8.3 Multicast Extractor

第一阶段不建议做完整 runtime 提取，而建议先做静态几何抽取：

- 根据 `shape + block_w/h/d` 生成所有合法 block
- 根据 `ingress policy` 生成默认 ingress
- 根据选定 source 或 sample target 再挂接实际高亮

这样能先把结构视图做出来，而不会被 runtime event 解析拖慢。

## 9. 里程碑建议

## 9.1 Phase 1: 静态结构可视化

交付：

- `baseline_2d` 拓扑图
- `full_3d` 拓扑图
- 统一 `topology.json`

目标：

- 把“系统结构”讲清楚

## 9.2 Phase 2: Block / Memory Overlay

交付：

- multicast block 图层
- stack/home 图层
- 2D vs 3D 对照页面

目标：

- 把“3D 不只是多一层，而是 route + memory 两张拓扑同时变化”讲清楚

## 9.3 Phase 3: Runtime Overlay

交付：

- 热点
- 流量
- stack pressure
- vertical hop

目标：

- 让静态系统图升级为研究型交互分析工具

## 10. 风险与注意事项

## 10.1 最大风险：把 workload 结构误画成物理结构

这在 2D 主线里尤其容易发生。  
`input_layer / hidden_layer / output_layer` 是逻辑映射，不是硅片层级。

## 10.2 第二风险：把 3D multicast 退化成普通最短路径图

如果前端只画 `src -> dst` 单播线，会把当前 `block + ingress + volumetric forwarding` 的真实设计信息丢掉。

## 10.3 第三风险：把 memory stack 直接混入 NoC 主图

这样会造成边过多、层次混乱。  
更合理的做法是主图显示 NoC，memory 作为可切换 overlay。

## 10.4 第四风险：第一版就想做动态回放

当前最需要的是“讲清结构”，不是“做最炫动画”。  
如果第一版直接追求 packet replay，很可能把项目节奏拖慢。

## 11. 最终建议

综合当前代码状态与文档状态，浮浮酱的建议是：

1. 先承认系统里已经存在三类拓扑：
   - `physical NoC topology`
   - `multicast block topology`
   - `memory-home topology`
2. 第一版可视化只把第一类做成主图，把后两类做成 overlay。
3. 用独立的 `Topology IR` 作为 2D / 3D 共用抽象，而不是直接绑定某个 builder。
4. 第一阶段只强制打通两个 canonical case：
   - `baseline_2d`
   - `full_3d`
5. 等静态结构表达稳定后，再逐步引入 runtime、thermal、pressure 等动态层。

如果按这个方向推进，那么最终得到的不会只是一个“把芯片画出来”的 demo，而会是一套真正能承接后续 route / memory / thermal / runtime 研究结果的结构可视化底座。

## 12. 后续落地建议

建议下一步直接进入一个小实现计划，目标不是完整前端，而是先做下面 3 个产物：

1. `topology_ir.py` 或等价抽象模块
2. `extract_2d_topology.py`
3. `extract_3d_topology.py`

只要这三件事先完成，后续不管前端选 `three.js`、`react-flow`、`d3`、还是自定义 canvas，都会容易很多。
