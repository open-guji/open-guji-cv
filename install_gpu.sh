#!/usr/bin/env bash
# install_gpu.sh — 安装 GPU 版 PaddlePaddle + open-guji-cv
#
# 用法：
#   bash install_gpu.sh           # 默认 CUDA 12.x
#   bash install_gpu.sh cu118     # CUDA 11.8
#   bash install_gpu.sh cpu       # 仅 CPU（无需 GPU 驱动）
#
# 支持的 CUDA 版本：cu118 / cu120 / cu121 / cu122 / cu123 / cu124
# 查询 CUDA 版本：nvidia-smi

set -e

CUDA_TAG="${1:-cu123}"
PADDLE_INDEX="https://www.paddlepaddle.org.cn/packages/stable/${CUDA_TAG}/"

echo "========================================="
echo " open-guji-cv GPU 安装脚本"
echo " CUDA 标签: ${CUDA_TAG}"
echo "========================================="

# 1. 卸载 CPU 版（如果已安装）
echo ""
echo "[1/4] 卸载 CPU 版 paddlepaddle（如有）..."
pip uninstall paddlepaddle -y 2>/dev/null || true

# 2. 安装 GPU 版 paddlepaddle
echo ""
echo "[2/4] 安装 paddlepaddle-gpu (${CUDA_TAG})..."
if [ "${CUDA_TAG}" = "cpu" ]; then
    pip install paddlepaddle
else
    pip install paddlepaddle-gpu -i "${PADDLE_INDEX}"
fi

# 3. 安装 paddleocr
echo ""
echo "[3/4] 安装 paddleocr..."
pip install "paddleocr>=2.8.0"

# 4. 安装 open-guji-cv（GPU extras，跳过 cpu paddle）
echo ""
echo "[4/4] 安装 open-guji-cv[gpu]..."
if [ -f "pyproject.toml" ]; then
    # 本地开发安装
    pip install -e ".[gpu]"
else
    pip install "open-guji-cv[gpu]"
fi

echo ""
echo "========================================="
echo " 安装完成！验证："
echo "   python -c \"import paddle; paddle.utils.run_check()\""
echo "========================================="
