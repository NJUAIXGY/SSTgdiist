import sst

# --- 最基本可运行的测试：1x2网格 ---
print("Creating simplest working test: 1x2 mesh...")

# 基本参数
routers = []

# 创建2个路由器
for i in range(2):
    router = sst.Component(f"router_{i}", "merlin.hr_router")
    router.addParams({
        "id": i,
        "num_ports": "5",           # 网格拓扑需要5个端口
        "link_bw": "1GiB/s",
        "flit_size": "8B",
        "xbar_bw": "1GiB/s",
        "input_latency": "10ns",
        "output_latency": "10ns",
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
    })

    # 配置1x2网格拓扑
    topo = router.setSubComponent("topology", "merlin.mesh")
    topo.addParams({
        "shape": "1x2",             # 1行2列
        "width": "1x1",
        "local_ports": "1",
    })

    # 添加测试NIC
    nic = router.setSubComponent("endpoint", "merlin.test_nic")
    nic.addParams({
        "id": i,
        "num_peers": 2,             # 2个节点
        "num_messages": "3",        # 只发送3条消息
        "message_size": "8B",       # 8字节消息
        "send_untimed_bcast": "0"   # 点对点通信
    })

    routers.append(router)

# 连接两个路由器：[0] -- [1]
print("Connecting 2 routers...")
link = sst.Link("link_0_1")
link.connect(
    (routers[0], "port0", "10ns"),  # router 0 东端口
    (routers[1], "port1", "10ns")   # router 1 西端口
)

print("Simplest working configuration complete.")

# 最简统计
sst.setStatisticLoadLevel(0)
