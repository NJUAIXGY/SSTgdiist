# Auto-generated MSNN ABI include (riscv_snn_isa_lab/tools/export_riscv_snn_abi.py)
# generated 2026-03-27T02:46:24Z

.set CSR_MSNN_CFG, 0x0BC0
.set CSR_MSNN_CMDQ_BASE, 0x0BC8
.set CSR_MSNN_CMDQ_HEAD, 0x0BCA
.set CSR_MSNN_CMDQ_SIZE, 0x0BC9
.set CSR_MSNN_CMDQ_TAIL, 0x0BCB
.set CSR_MSNN_CMPQ_BASE, 0x0BCC
.set CSR_MSNN_CMPQ_HEAD, 0x0BCE
.set CSR_MSNN_CMPQ_SIZE, 0x0BCD
.set CSR_MSNN_CMPQ_TAIL, 0x0BCF
.set CSR_MSNN_EVENT_ENABLE, 0x0BD8
.set CSR_MSNN_EVENT_PENDING, 0x0BD9
.set CSR_MSNN_FAULT, 0x0BDB
.set CSR_MSNN_FEAT, 0x0BC2
.set CSR_MSNN_HART_ID, 0x0BC3
.set CSR_MSNN_RXQ_BASE, 0x0BD0
.set CSR_MSNN_RXQ_HEAD, 0x0BD2
.set CSR_MSNN_RXQ_SIZE, 0x0BD1
.set CSR_MSNN_RXQ_TAIL, 0x0BD3
.set CSR_MSNN_STATUS, 0x0BC1
.set CSR_MSNN_STEP, 0x0BDA

# event barrier_release -> bit 1
# event cmd_complete -> bit 0
# event debug -> bit 5
# event fault -> bit 2
# event prefetch_done -> bit 4
# event rx_debug -> bit 3
