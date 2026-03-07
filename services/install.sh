#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
LOGS_DIR="$BASE_DIR/logs"

mkdir -p "$LOGS_DIR"

echo "创建日志目录: $LOGS_DIR"

SERVICES=("web_chat" "config_center" "feishu_channel")

for service in "${SERVICES[@]}"; do
    SERVICE_FILE="$SCRIPT_DIR/${service}.service"
    if [ -f "$SERVICE_FILE" ]; then
        echo "安装服务: $service"
        sudo cp "$SERVICE_FILE" /etc/systemd/system/
        sudo chown root:root /etc/systemd/system/${service}.service
        sudo chmod 644 /etc/systemd/system/${service}.service
    else
        echo "警告: 服务文件不存在 - $SERVICE_FILE"
    fi
done

echo "重新加载 systemd 守护进程..."
sudo systemctl daemon-reload

echo ""
echo "服务安装完成!"
echo ""
echo "可用命令:"
echo "  启动服务:   sudo systemctl start <服务名>"
echo "  停止服务:   sudo systemctl stop <服务名>"
echo "  重启服务:   sudo systemctl restart <服务名>"
echo "  查看状态:   sudo systemctl status <服务名>"
echo "  查看日志:   sudo journalctl -u <服务名> -f"
echo "  开机自启:   sudo systemctl enable <服务名>"
echo "  禁用自启:   sudo systemctl disable <服务名>"
echo ""
echo "服务名称: web_chat, config_center, feishu_channel"
echo ""
echo "日志文件位置: $LOGS_DIR"
