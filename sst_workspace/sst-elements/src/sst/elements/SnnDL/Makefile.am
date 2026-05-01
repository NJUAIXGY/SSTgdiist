AM_CPPFLAGS += \
	-I$(top_srcdir)/src \
	-I$(srcdir) \
	-I$(srcdir)/api \
	-I$(srcdir)/events \
	-I$(srcdir)/components \
	-I$(srcdir)/control \
	-I$(srcdir)/compute \
	-I$(srcdir)/services \
	-I$(SST_PREFIX)/include

# 可选的MPI支持 - 不影响现有构建
# 暂时注释掉，等待configure.ac配置完成
# if SST_CONFIG_HAVE_MPI
# AM_CPPFLAGS += $(MPI_CPPFLAGS)
# endif

compdir = $(pkglibdir)
comp_LTLIBRARIES = libSnnDL.la
libSnnDL_la_SOURCES = \
	api/SnnCoreAPI.h \
	api/CoreShellAPI.h \
	api/SnnInterface.h \
	api/SnnPEParentInterface.h \
	api/ISpikeTransport.h \
	api/INocTransport.h \
	api/IManualWindowDrive.h \
	api/GasOps.h \
	api/IGasCmdSender.h \
	api/IGasStageSink.h \
	api/IGasStepGate.h \
	api/IGlobalStepHooks.h \
	api/ICoreMemoryLink.h \
	api/IMemoryAccess.h \
	api/IDmaTaggedAccess.h \
	api/IDmaSchedulerProvider.h \
	api/IPeSharedCoreFabricProvider.h \
	api/ILocalStorageProvider.h \
	api/ICoreWorkload.h \
	api/ISnnAccelRuntimeServices.h \
	api/ISpikeWorkload.h \
	api/WorkloadConfig.h \
	api/CoreWorkloadFactory.h \
	api/ISynapseRoute.h \
	api/SynapseRouteBuildConfig.h \
	api/SnnWeightReader.h \
	api/IWeightReaderAdopter.h \
	api/SnnDLLogging.h \
	events/GatingDecisionEvent.h \
	events/GasStepBarrierEvent.h \
	events/SimpleTestEvent.cc \
	events/SimpleTestEvent.h \
	events/SpikeEvent.h \
	events/SpikeEventWrapper.cc \
	events/SpikeEventWrapper.h \
	events/SpikePacket.h \
	components/gas/GlobalGasStepController.cc \
	components/gas/GlobalGasStepController.h \
	components/CachelineFragmentMemIF.cc \
	components/CachelineFragmentMemIF.h \
	components/GatherBufferIF.cc \
	components/GatherBufferIF.h \
	components/gather/GatherBufferIFConfig.cc \
	components/gather/GatherBufferIFConfig.h \
	components/gather/apply/DramAwareModel.cc \
	components/gather/apply/DramAwareModel.h \
	components/GatingPE.cc \
	components/GatingPE.h \
	components/MemKCalBench.cc \
	components/MemKCalBench.h \
	components/multicore/MultiCorePEConfig.cc \
	components/multicore/MultiCorePEConfig.h \
	components/MultiCorePE.cc \
	components/MultiCorePE.h \
	components/SnnNIC.cc \
	components/SnnNIC.h \
	components/SnnPE.cc \
	components/SnnPE.h \
	components/stimulus/SpikeSource.cc \
	components/stimulus/SpikeSource.h \
	components/WeightLoader.cc \
	components/WeightLoader.h \
	components/workload_stats/IWorkloadStatsModule.h \
	components/workload_stats/KeyedCounterStatsModule.h \
	components/workload_stats/StreamWorkloadStatsModule.h \
	components/workload_stats/TensorWorkloadStatsModule.h \
	components/workload_stats/WorkloadStatsRegistry.cc \
	components/workload_stats/WorkloadStatsRegistry.h \
	control/SnnPESubComponent.cc \
	control/SnnPESubComponent.h \
	control/SnnPESubComponent_impl.h \
	control/SnnPESubComponent_bcsr.cc \
	control/SnnPESubComponent_routing.cc \
	control/SnnPESubComponent_scheme1.cc \
	control/SnnPESubComponent_spike.cc \
	control/SnnPEApplyScatter.cc \
	control/SnnPEOrchestrators.cc \
	compute/SnnComputeCore.cc \
	compute/SnnComputeCore.h \
	compute/SnnCoreEngine.cc \
	compute/SnnCoreEngine.h \
	compute/SnnLearningCore.cc \
	compute/SnnLearningCore.h \
	compute/IWeightAwareComputeCore.h \
	compute/SnnNeuronModel.h \
	compute/SynapseManager.h \
	services/synapse/gas/AccumulatorOps.cc \
	services/synapse/gas/AccumulatorOps.h \
	services/synapse/gas/GasCustomCmd.h \
	services/synapse/gas/GasEdgeCollector.cc \
	services/synapse/gas/GasEdgeCollector.h \
	services/synapse/gas/GasPhaseController.cc \
	services/synapse/gas/GasPhaseController.h \
	services/synapse/stdmem/StdMemEndpoint.cc \
	services/synapse/stdmem/StdMemEndpoint.h \
	services/synapse/stdmem/SnnPESubComponent_mem.cc \
	services/noc/OptimizedInternalRing.cc \
	services/noc/OptimizedInternalRing.h \
	components/noc/SimpleNetworkWrapper.cc \
	components/noc/SimpleNetworkWrapper.h \
	services/synapse/weights/SnnBcsrWeightManager.cc \
	services/synapse/weights/SnnBcsrWeightManager.h \
	services/synapse/weights/SnnWeightDiagnostics.cc \
	services/synapse/weights/SnnWeightDiagnostics.h \
	components/noc/SnnNetworkAdapter.cc \
	components/noc/SnnNetworkAdapter.h \
	components/noc/MulticastRouter.cc \
	components/noc/MulticastRouter.h \
	components/noc3d/MulticastRouter3DNative.cc \
	components/noc3d/MulticastRouter3DNative.h \
	components/noc3d/MulticastRouter3DNativeConfig.h \
	components/noc3d/Noc3DSmokeSource.cc \
	components/noc3d/Noc3DSmokeSource.h \
	components/noc3d/Noc3DSmokeSink.cc \
	components/noc3d/Noc3DSmokeSink.h \
	components/noc3d/HBMStackStub.cc \
	components/noc3d/HBMStackStub.h \
	components/noc/MulticastNIC.cc \
	components/noc/MulticastNIC.h \
	services/SnnProfiler.h \
	services/synapse/route/SnnRouteProvider.cc \
	services/synapse/route/SnnRouteProvider.h \
	services/synapse/route/SpikeNocCodec.cc \
	services/synapse/route/SpikeNocCodec.h \
	services/synapse/route/BcsrRouteBuilder.cc \
	services/synapse/route/BcsrRouteBuilder.h \
	services/synapse/route/StepBcsrReachability.cc \
	services/synapse/route/StepBcsrReachability.h \
	services/synapse/route/SynapseRouteSubsystem.cc \
	services/synapse/route/SynapseRouteSubsystem.h \
	services/synapse/route3d/Route3DNodeMapper.h \
	services/synapse/route3d/SynapseRouteSubsystem3D.cc \
	services/synapse/route3d/SynapseRouteSubsystem3D.h \
	services/stimulus/StepActivationSubsystem.cc \
	services/stimulus/StepActivationSubsystem.h \
	services/stimulus/ExternalSpikeInputSubsystem.cc \
	services/stimulus/ExternalSpikeInputSubsystem.h \
	services/noc/NocSubsystem.cc \
	services/noc/NocSubsystem.h \
	services/synapse/weights/WeightAccessor.cc \
	services/synapse/weights/WeightAccessor.h \
	services/synapse/weights/WeightCacheOps.cc \
	services/synapse/weights/WeightCacheOps.h \
	services/synapse/weights/WeightMemorySubsystem.cc \
	services/synapse/weights/WeightMemorySubsystem.h \
	services/synapse/route/SpikeCommSubsystem.cc \
	services/synapse/route/SpikeCommSubsystem.h \
	services/synapse/route/SpikePacketTransport.h \
	services/synapse/route/SpikePacketBridge.cc \
	services/synapse/route/SpikePacketBridge.h \
	services/workload/CoreWorkloadFactory.cc \
	services/workload/common/SnnAccelBackend.cc \
	services/workload/common/SnnAccelBackend.h \
	services/workload/common/SnnAccelBackendContract.h \
	services/workload/layout/NormalizedNeuronLayout.cc \
	services/workload/layout/NormalizedNeuronLayout.h \
	services/workload/riscv_snn/RiscvSnnAbi.h \
	services/workload/riscv_snn/RiscvSnnAsm.h \
	services/workload/riscv_snn/RiscvSnnBootDriver.cc \
	services/workload/riscv_snn/RiscvSnnBootDriver.h \
	services/workload/riscv_snn/RiscvSnnElfWriter.h \
	services/workload/riscv_snn/RiscvSnnFirmwareLoader.cc \
	services/workload/riscv_snn/RiscvSnnFirmwareLoader.h \
	services/workload/riscv_snn/RiscvSnnHart.cc \
	services/workload/riscv_snn/RiscvSnnHart.h \
	services/workload/riscv_snn/RiscvSnnIss.cc \
	services/workload/riscv_snn/RiscvSnnIss.h \
	services/workload/riscv_snn/RiscvSnnMemoryImage.h \
	services/workload/riscv_snn/RiscvSnnQueueContract.h \
	services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.cc \
	services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.h \
	services/workload/riscv_snn/RiscvSnnSampleFirmware.h \
	services/workload/riscv_snn/RiscvSnnShadowTransportExport.cc \
	services/workload/riscv_snn/RiscvSnnShadowTransportExport.h \
	services/workload/riscv_snn/RiscvSnnShadowRuntimeServices.cc \
	services/workload/riscv_snn/RiscvSnnShadowRuntimeServices.h \
	services/workload/riscv_snn/RiscvSnnWorkload.cc \
	services/workload/riscv_snn/RiscvSnnWorkload.h \
	services/workload/snn/SnnWorkload.cc \
	services/workload/snn/SnnWorkload.h \
	services/workload/stream/StreamWorkload.cc \
	services/workload/stream/StreamWorkload.h \
	services/workload/traffic/TrafficWorkload.cc \
	services/workload/traffic/TrafficWorkload.h \
	services/workload/traffic_mem/TrafficMemWorkload.cc \
	services/workload/traffic_mem/TrafficMemWorkload.h \
	services/workload/tensor/TensorWorkload.cc \
	services/workload/tensor/TensorWorkload.h \
	services/memory/sram_sim/layout/VirtualSramLayout.h \
	services/memory/sram_sim/model/BankedSramModel.cc \
	services/memory/sram_sim/model/BankedSramModel.h \
	services/local_storage/LocalStorageTypes.h \
	services/local_storage/LocalStorageHierarchyController.cc \
	services/local_storage/LocalStorageHierarchyController.h \
	services/local_storage/PeWeightObjectPlane.cc \
	services/local_storage/PeWeightObjectPlane.h \
	services/memory/DmaMemAccessProxy.cc \
	services/memory/DmaMemAccessProxy.h \
	services/pe_fabric/PulseAgendaScorer.cc \
	services/pe_fabric/PulseAgendaScorer.h \
	services/pe_fabric/PulseDescriptor.h \
	services/pe_fabric/PeSharedCoreFabric.cc \
	services/pe_fabric/PeSharedCoreFabric.h \
	services/memory/PeDmaScheduler.cc \
	services/memory/PeDmaScheduler.h \
	services/memory/StandardMemAccess.cc \
	services/memory/StandardMemAccess.h

#
# Note: sources above already include GatherBufferIF / MemKCalBench / MPI files.
#

libSnnDL_la_LDFLAGS = -module -avoid-version
RISCV_SNN_TEST_LINK = $(CXXLD) $(DEFS) $(DEFAULT_INCLUDES) $(INCLUDES) $(AM_CPPFLAGS) $(CPPFLAGS) $(CXXFLAGS)

# 可选的MPI链接库 - 暂时注释掉
# if SST_CONFIG_HAVE_MPI
# libSnnDL_la_LDFLAGS += $(MPI_LDFLAGS)
# libSnnDL_la_LIBADD = $(MPI_LIBS)
# endif

.PHONY: test-compile test-riscv-snn-protocols test-riscv-snn-backend-timing-contract test-riscv-snn-runtime-service-provider test-riscv-snn-runtime-bridge-backend test-riscv-snn-firmware-protocol test-riscv-snn-toolchain-firmware-protocol test-riscv-snn-stimulus-gating
test-riscv-snn-protocols: test-riscv-snn-backend-timing-contract test-riscv-snn-runtime-service-provider test-riscv-snn-runtime-bridge-backend test-riscv-snn-firmware-protocol test-riscv-snn-toolchain-firmware-protocol test-riscv-snn-stimulus-gating

test-riscv-snn-stimulus-gating:
	$(RISCV_SNN_TEST_LINK) $(srcdir)/tests/test_riscv_snn_stimulus_gating.cc \
		-o $(builddir)/test_riscv_snn_stimulus_gating$(EXEEXT) && \
		$(builddir)/test_riscv_snn_stimulus_gating$(EXEEXT) && \
		rg -q "ex_rt\\.enabled = workloadAllowsSnnStimulus\\(cfg\\.workload_kind\\);" $(srcdir)/components/MultiCorePE.cc && \
		rg -q "if \\(!rt_\\.enabled\\)" $(srcdir)/services/stimulus/ExternalSpikeInputSubsystem.cc

test-riscv-snn-backend-timing-contract:
	$(RISCV_SNN_TEST_LINK) $(srcdir)/tests/test_riscv_snn_backend_timing_contract.cc \
		$(srcdir)/services/workload/common/SnnAccelBackend.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnHart.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnIss.cc \
		-o $(builddir)/test_riscv_snn_backend_timing_contract$(EXEEXT) && \
		$(builddir)/test_riscv_snn_backend_timing_contract$(EXEEXT)

test-riscv-snn-runtime-service-provider:
	$(RISCV_SNN_TEST_LINK) $(srcdir)/tests/test_riscv_snn_runtime_service_provider.cc \
		$(srcdir)/services/workload/common/SnnAccelBackend.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnShadowTransportExport.cc \
		-o $(builddir)/test_riscv_snn_runtime_service_provider$(EXEEXT) && \
		$(builddir)/test_riscv_snn_runtime_service_provider$(EXEEXT)

test-riscv-snn-runtime-bridge-backend:
	$(RISCV_SNN_TEST_LINK) $(srcdir)/tests/test_riscv_snn_runtime_bridge_backend.cc \
		$(srcdir)/services/workload/common/SnnAccelBackend.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.cc \
		-o $(builddir)/test_riscv_snn_runtime_bridge_backend$(EXEEXT) && \
		$(builddir)/test_riscv_snn_runtime_bridge_backend$(EXEEXT)

test-riscv-snn-firmware-protocol:
	$(RISCV_SNN_TEST_LINK) $(srcdir)/tests/test_riscv_snn_firmware_protocol.cc \
		$(srcdir)/services/workload/common/SnnAccelBackend.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnHart.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnIss.cc \
		-o $(builddir)/test_riscv_snn_firmware_protocol$(EXEEXT) && \
		$(builddir)/test_riscv_snn_firmware_protocol$(EXEEXT)

test-riscv-snn-toolchain-firmware-protocol:
	$(RISCV_SNN_TEST_LINK) $(srcdir)/tests/test_riscv_snn_toolchain_firmware_protocol.cc \
		$(srcdir)/services/workload/common/SnnAccelBackend.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnHart.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnIss.cc \
		$(srcdir)/services/workload/riscv_snn/RiscvSnnFirmwareLoader.cc \
		-o $(builddir)/test_riscv_snn_toolchain_firmware_protocol$(EXEEXT) && \
		$(builddir)/test_riscv_snn_toolchain_firmware_protocol$(EXEEXT)

test-compile:
	$(CXXCOMPILE) -c $(srcdir)/tests/test_includes.cc -o $(builddir)/test_includes.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_pe_internal_pod_shadow_gate.cc -o $(builddir)/test_pe_internal_pod_shadow_gate.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_pe_internal_pod_shadow_wms_seam.cc -o $(builddir)/test_pe_internal_pod_shadow_wms_seam.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_abi.cc -o $(builddir)/test_riscv_snn_abi.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_backend_timing_contract.cc -o $(builddir)/test_riscv_snn_backend_timing_contract.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_boot_driver.cc -o $(builddir)/test_riscv_snn_boot_driver.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_firmware_loader.cc -o $(builddir)/test_riscv_snn_firmware_loader.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_firmware_tools.cc -o $(builddir)/test_riscv_snn_firmware_tools.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_firmware_protocol.cc -o $(builddir)/test_riscv_snn_firmware_protocol.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_toolchain_firmware_protocol.cc -o $(builddir)/test_riscv_snn_toolchain_firmware_protocol.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_iss.cc -o $(builddir)/test_riscv_snn_iss.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_queue_contract.cc -o $(builddir)/test_riscv_snn_queue_contract.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_runtime_bridge_backend.cc -o $(builddir)/test_riscv_snn_runtime_bridge_backend.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_runtime_service_provider.cc -o $(builddir)/test_riscv_snn_runtime_service_provider.o
	$(CXXCOMPILE) -c $(srcdir)/tests/test_riscv_snn_stimulus_gating.cc -o $(builddir)/test_riscv_snn_stimulus_gating.o
