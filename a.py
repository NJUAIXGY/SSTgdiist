import torch

# 打印 PyTorch 版本
print(f"PyTorch Version: {torch.__version__}")

# 检查 CUDA (GPU) 是否可用
is_cuda_available = torch.cuda.is_available()
print(f"Is CUDA available? {is_cuda_available}")

if is_cuda_available:
    # 打印 GPU 数量
    print(f"CUDA device count: {torch.cuda.device_count()}")
    # 打印当前 GPU 设备名称
    print(f"Current CUDA device name: {torch.cuda.get_device_name(torch.cuda.current_device())}")

# 创建一个张量 (tensor)
x = torch.rand(5, 3)
print("\nA random tensor:")
print(x)