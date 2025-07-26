import sst

# --- 最最基本的单节点测试 ---
print("Creating minimal single node test...")

# 创建单个路由器
router = sst.Component("router_0", "merlin.hr_router")
router.addParams({
    "id": 0,
    "num_ports": "1",           # 只有1个本地端口
    "link_bw": "1GiB/s",
    "flit_size": "8B",
    "xbar_bw": "1GiB/s",
    "input_latency": "100ns",
    "output_latency": "100ns",
    "input_buf_size": "1KiB",
    "output_buf_size": "1KiB",
})

# 配置单节点拓扑
topo = router.setSubComponent("topology", "merlin.single")

# 添加测试NIC
nic = router.setSubComponent("endpoint", "merlin.test_nic")
nic.addParams({
    "id": 0,
    "num_peers": 1,             # 只有自己
    "num_messages": "5",        # 只发送5条消息
    "message_size": "16B",      # 16字节消息
    "send_untimed_bcast": "0"   # 关闭广播
})

print("Single node configuration complete.")
print("This is the most basic SST test possible.")

# 最简统计配置
sst.setStatisticLoadLevel(0)  # 关闭大部分统计
