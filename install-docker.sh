#!/bin/bash
# Docker 安装脚本（WSL Ubuntu 内执行）
# 用法：先在 PowerShell 输入 wsl 回车，然后运行：
#   bash /mnt/d/uv/rag_yuyin/RAG/install-docker.sh

set -e

echo "=== 添加 Docker 阿里云镜像源 ==="
curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list

echo "=== 安装 Docker ==="
apt update && apt install -y docker-ce docker-ce-cli docker-compose-plugin

echo "=== 启动 Docker ==="
service docker start

echo "=== 验证安装 ==="
docker run hello-world

echo "=== 完成！之后每次打开 WSL，先运行 service docker start ==="
