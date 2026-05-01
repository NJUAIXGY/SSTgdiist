# services/legacy/noc/（历史 NoC 参考目录：已清空）

该目录用于标识 **历史的 NoC/网络适配参考实现曾经所在的位置**。

当前主链路已收敛为：
- `services/noc/`：NoC 传输事务子系统（实现 `api/INocTransport.h`）
- `components/noc/`：ELI 可加载的网络拓扑适配组件（如 `SnnNetworkAdapter` / `SimpleNetworkWrapper`）

主链路的默认体系结构口径中，内存侧以 **cacheline 粒度**作为对外搬运/统计单位；NoC 侧以 packet-first 的 `NocPacketEvent` 作为传输载体，二者互不耦合。

> 说明：该目录刻意保持为空，避免出现“services 下也有可加载网络组件”的认知混乱与重复实现。
