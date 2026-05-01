import sst

# Program options (avoid MPI by forcing single partition)
sst.setProgramOption("timebase", "1ps")
sst.setProgramOption("stop-at", "3us")
sst.setProgramOption("partitioner", "sst.single")

# MultiCorePE with 1 core, 4 neurons
pe = sst.Component("pe0", "SnnDL.MultiCorePE")
pe.addParams({
    "clock": "1GHz",
    "num_cores": 1,
    "neurons_per_core": 4,
    "node_id": 0,
    "global_neuron_base": 0,
    "verbose": 1,
    # disable memory-driven weights to avoid mem dependency in this smoke test
    "enable_test_traffic": 0,
})

# Attach user SnnPESubComponent with learning enabled (no writeback)
core0 = pe.setSubComponent("core0", "SnnDL.SnnPESubComponent")
core0.addParams({
    "core_id": 0,
    "total_cores": 1,
    "num_neurons": 4,                 # local model size for this test
    "global_neuron_base": 0,
    "node_id": 0,
    "v_thresh": 1.0,
    "v_reset": 0.0,
    "v_rest": 0.0,
    "tau_mem": 20.0,
    "t_ref": 2,
    "verbose": 2,
    # routing/weights disabled for simplicity in this smoke test
    "enable_weight_fetch": 0,
    # learning params
    "learning_enabled": 1,
    "learn_window_cycles": 1000,
    "record_spike_times": 1,
    "record_membrane": 1,
    "surrogate_type": "superspike",
    "surrogate_beta": 5.0,
    # error file template; supports {node},{core},{win}
    "error_file": "/home/anarchy/SST/experimental_features/snnDL_learning_tests/errors/error_node_{node}_core_{core}_win_{win}.txt",
})

# Spike source feeding external input
src = sst.Component("src", "SnnDL.SpikeSource")
src.addParams({
    "dataset_path": "/home/anarchy/SST/experimental_features/snnDL_learning_tests/datasets/min.txt",
    "dataset_format": "TEXT",
    "time_scale": 1.0,    # timestamps interpreted as microseconds; SpikeSource clock is 1MHz
    "neuron_offset": 0,
    "max_events": 0,
    "verbose": 1,
})

# Connect source to PE external input
link = sst.Link("src_to_pe")
link.connect( (src, "spike_output", "1ns"), (pe, "external_spike_input", "1ns") )
