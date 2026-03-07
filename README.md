# AgentScope Multi-Agent IM 配置中心

基于 AgentScope 框架的多智能体 IM 配置中心，支持飞书等即时通讯平台。

## 特性

- 🖥️ **Streamlit Web配置界面** - 开箱即用的可视化配置
- 🤖 **多Agent支持** - 支持创建多个不同角色的Agent
- 💬 **IM集成** - 支持飞书等即时通讯平台
- 🔄 **多种工作流** - Sequential、Fanout、MsgHub协作模式
- 🧠 **长期记忆** - 支持Agent长期记忆功能
- 📚 **知识库** - RAG知识检索集成

## 快速开始

### 1. 安装依赖

```bash
# 克隆项目
git clone <repository>
cd multi_agent_im

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 启动配置中心

```bash
streamlit run streamlit_config.py
```

访问 http://localhost:8501 进行配置。

### 3. 配置步骤

1. **LLM配置** - 添加LLM模型（如智普AI、OpenAI等）
2. **Agent配置** - 创建Agent，选择模型、角色、能力
3. **IM配置** - 配置飞书等IM平台
4. **工作流配置** - 选择工作流模式

## 工作流模式

| 模式 | 说明 |
|------|------|
| Sequential | 顺序管道，前一个Agent输出作为后一个输入 |
| Fanout Parallel | 扇出并行，相同输入分发给多个Agent并行执行 |
| Fanout Sequential | 扇出顺序，相同输入分发给多个Agent顺序执行 |
| MsgHub | 群聊模式，多Agent之间消息广播讨论 |

## 项目结构

```
multi_agent_im/
├── streamlit_config.py      # Streamlit配置界面
├── feishu_channel_service.py # 飞书消息服务
├── path_config.py           # 路径配置（可移植性）
├── config.json              # 配置文件
├── requirements.txt         # 依赖列表
├── install.sh              # 安装脚本
└── README.md               # 说明文档
```

## 环境变量

| 变量 | 说明 |
|------|------|
| MULTI_AGENT_PROJECT_DIR | 项目目录路径 |
| MULTI_AGENT_MEDIA_DIR | 媒体文件目录 |
| MULTI_AGENT_VENV | 虚拟环境路径 |

## 许可证

MIT License
