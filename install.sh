#!/bin/bash
set -e

echo "=========================================="
echo "  AgentScope Multi-Agent IM 安装脚本"
echo "=========================================="

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
USERNAME="$(whoami)"
USER_GROUP="$(id -gn)"

echo "项目目录: $PROJECT_DIR"
echo "用户: $USERNAME"

cd "$PROJECT_DIR"

if [ ! -d "venv" ] && [ ! -d "../agentscope_env" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
fi

if [ ! -f "config.json" ]; then
    echo "创建默认配置文件..."
    cat > config.json << 'EOF'
{
  "agents": [],
  "llms": [],
  "im": {
    "global_im": {},
    "platform": "multi"
  },
  "workflow": "sequential"
}
EOF
fi

mkdir -p logs media

SERVICE_FILE="multi-agent-config.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Multi-Agent Config Center
After=network.target

[Service]
Type=simple
User=$USERNAME
Group=$USER_GROUP
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/../agentscope_env/bin/streamlit run $PROJECT_DIR/streamlit_config.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=10
StandardOutput=append:$PROJECT_DIR/streamlit.log
StandardError=append:$PROJECT_DIR/streamlit.log

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "=========================================="
echo "  安装完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 配置LLM和Agent: 访问 http://localhost:8501"
echo "2. 安装服务: sudo cp $SERVICE_FILE /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable multi-agent-config && sudo systemctl start multi-agent-config"
echo ""
