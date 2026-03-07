#!/usr/bin/env python3
from flask import Flask, render_template_string, request, jsonify
import asyncio
import os
import logging
import queue
import threading
import json
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import agentscope
from agentscope.agent import ReActAgent
from agentscope.model import OpenAIChatModel
from agentscope.memory import InMemoryMemory
from agentscope.formatter import OpenAIChatFormatter
from agentscope.pipeline import MsgHub, sequential_pipeline
from agentscope.message import Msg

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('web_chat.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

agentscope.init(
    project="multi_agent_web"
)

def load_config():
    config_file = 'config.json'
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    logger.warning(f"配置文件 {config_file} 不存在，使用默认配置")
    return {}

def get_llm_config(llm_id: str, config: dict) -> Optional[Dict[str, Any]]:
    llms = config.get('llms', [])
    for llm in llms:
        if llm.get('id') == llm_id:
            return llm
    logger.warning(f"未找到LLM配置: {llm_id}")
    return None

def create_model_from_config(llm_config: Dict[str, Any]) -> OpenAIChatModel:
    return OpenAIChatModel(
        model_name=llm_config['model_id'],
        api_key=llm_config['api_key'],
        client_kwargs={
            "base_url": llm_config['base_url']
        }
    )

def create_agents_from_config():
    config = load_config()
    agents_config = config.get('agents', [])
    agents = {}
    
    for agent_config in agents_config:
        agent_name = agent_config.get('name')
        llm_id = agent_config.get('model')
        
        if not llm_id:
            logger.warning(f"Agent {agent_name} 未配置模型，跳过")
            continue
        
        llm_config = get_llm_config(llm_id, config)
        if not llm_config:
            logger.warning(f"Agent {agent_name} 的模型配置 {llm_id} 不存在，跳过")
            continue
        
        try:
            model = create_model_from_config(llm_config)
            agent = ReActAgent(
                name=agent_name,
                sys_prompt=agent_config.get('system_prompt', f"你是{agent_name}，负责{agent_config.get('role', '执行任务')}。"),
                model=model,
                memory=InMemoryMemory(),
                formatter=OpenAIChatFormatter()
            )
            agents[agent_name] = agent
            logger.info(f"成功创建Agent: {agent_name}, 模型: {llm_config.get('display_name')}")
        except Exception as e:
            logger.error(f"创建Agent {agent_name} 失败: {str(e)}")
    
    return agents

agents_dict = create_agents_from_config()

researcher = agents_dict.get('研究员')
analyst = agents_dict.get('分析师')
writer = agents_dict.get('撰写员')

if not all([researcher, analyst, writer]):
    logger.warning("部分Agent未成功创建，系统可能无法正常工作")

class MessageQueueManager:
    def __init__(self):
        self.message_queue = queue.Queue()
        self.response_queues: Dict[str, queue.Queue] = {}
        self.lock = threading.Lock()
        logger.info("消息队列管理器初始化完成")
    
    def add_message(self, source: str, message_id: str, content: str, metadata: Optional[Dict] = None) -> str:
        with self.lock:
            message_data = {
                'source': source,
                'message_id': message_id,
                'content': content,
                'metadata': metadata or {},
                'timestamp': datetime.now().isoformat()
            }
            self.message_queue.put(message_data)
            self.response_queues[message_id] = queue.Queue()
            
            logger.info(f"消息入队 - 来源: {source}, ID: {message_id}, 内容长度: {len(content)}")
            logger.debug(f"消息详情: {json.dumps(message_data, ensure_ascii=False)}")
            
            return message_id
    
    def get_response(self, message_id: str, timeout: float = 60.0) -> Optional[Dict]:
        try:
            if message_id not in self.response_queues:
                logger.warning(f"未找到消息ID: {message_id}")
                return None
            
            response = self.response_queues[message_id].get(timeout=timeout)
            logger.info(f"获取响应 - ID: {message_id}, 状态: {response.get('status', 'unknown')}")
            return response
        except queue.Empty:
            logger.error(f"获取响应超时 - ID: {message_id}")
            return {'status': 'timeout', 'error': '响应超时'}
        finally:
            with self.lock:
                if message_id in self.response_queues:
                    del self.response_queues[message_id]
    
    def put_response(self, message_id: str, response: Dict):
        with self.lock:
            if message_id in self.response_queues:
                self.response_queues[message_id].put(response)
                logger.info(f"响应入队 - ID: {message_id}")
            else:
                logger.warning(f"未找到响应队列 - ID: {message_id}")
    
    def get_next_message(self) -> Optional[Dict]:
        try:
            message = self.message_queue.get_nowait()
            logger.debug(f"从队列获取消息 - ID: {message['message_id']}")
            return message
        except queue.Empty:
            return None

message_manager = MessageQueueManager()

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>多 Agent 协作系统</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-bottom: 10px; text-align: center; }
        .subtitle { text-align: center; color: #666; margin-bottom: 20px; }
        .chat-box { height: 500px; overflow-y: auto; border: 1px solid #ddd; padding: 15px; margin-bottom: 20px; background: #fafafa; border-radius: 5px; }
        .message { margin-bottom: 15px; padding: 10px; border-radius: 5px; }
        .user-message { background: #e3f2fd; text-align: right; }
        .agent-message { background: #f1f8e9; }
        .agent-name { font-weight: bold; color: #1976d2; margin-bottom: 5px; }
        .input-area { display: flex; gap: 10px; }
        input[type="text"] { flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-size: 14px; }
        button { padding: 10px 20px; background: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; }
        button:hover { background: #45a049; }
        .status { text-align: center; color: #666; margin-top: 10px; font-size: 12px; }
        .agents-info { display: flex; justify-content: space-around; margin-bottom: 20px; padding: 10px; background: #e8f5e9; border-radius: 5px; }
        .agent-card { text-align: center; padding: 10px; }
        .agent-card h3 { color: #1976d2; margin-bottom: 5px; }
        .agent-card p { color: #666; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 多 Agent 协作系统</h1>
        <p class="subtitle">研究员 → 分析师 → 撰写员</p>
        
        <div class="agents-info">
            <div class="agent-card">
                <h3>📚 研究员</h3>
                <p>收集和整理信息</p>
            </div>
            <div class="agent-card">
                <h3>📊 分析师</h3>
                <p>分析数据并给出见解</p>
            </div>
            <div class="agent-card">
                <h3>✍️ 撰写员</h3>
                <p>生成完整报告</p>
            </div>
        </div>
        
        <div class="chat-box" id="chatBox">
            <div class="message agent-message">
                <div class="agent-name">系统</div>
                <div>你好！我是多 Agent 协作系统。请输入你的任务，三个 Agent 会协作完成。</div>
            </div>
        </div>
        <div class="input-area">
            <input type="text" id="userInput" placeholder="输入你的任务..." onkeypress="if(event.key==='Enter')sendMessage()">
            <button onclick="sendMessage()">发送</button>
        </div>
        <div class="status" id="status"></div>
    </div>

    <script>
        async function sendMessage() {
            const input = document.getElementById('userInput');
            const message = input.value.trim();
            if (!message) return;

            const chatBox = document.getElementById('chatBox');
            const status = document.getElementById('status');

            chatBox.innerHTML += `<div class="message user-message"><strong>你：</strong> ${message}</div>`;
            input.value = '';
            status.textContent = '多 Agent 协作中...';

            chatBox.scrollTop = chatBox.scrollHeight;

            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: message })
                });

                const data = await response.json();
                
                if (data.error) {
                    chatBox.innerHTML += `<div class="message agent-message"><strong>错误：</strong> ${data.error}</div>`;
                } else {
                    data.responses.forEach(resp => {
                        chatBox.innerHTML += `<div class="message agent-message"><div class="agent-name">${resp.agent}</div><div>${resp.content}</div></div>`;
                    });
                }
            } catch (error) {
                chatBox.innerHTML += `<div class="message agent-message"><strong>错误：</strong> 网络请求失败</div>`;
            }

            status.textContent = '';
            chatBox.scrollTop = chatBox.scrollHeight;
        }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        message = data.get('message', '')
        
        logger.info(f"收到Web消息 - 内容长度: {len(message)}")
        logger.debug(f"Web消息详情: {message}")
        
        message_id = f"web_{datetime.now().timestamp()}"
        
        config = load_config()
        workflow_mode = config.get('workflow', 'sequential')
        
        async def get_response():
            responses = []
            
            logger.info(f"开始处理Web消息 - ID: {message_id}, 工作流模式: {workflow_mode}")
            
            if workflow_mode == 'parallel':
                logger.info("使用并行执行模式")
                
                async def process_agent(agent):
                    try:
                        msg = Msg(name="user", content=message, role="user")
                        response = await agent(msg)
                        
                        content = response.content
                        if isinstance(content, str):
                            return {
                                'agent': agent.name,
                                'content': content
                            }
                        elif isinstance(content, list):
                            text_parts = []
                            for item in content:
                                if isinstance(item, dict):
                                    if item.get('type') == 'text':
                                        text_parts.append(item.get('text', ''))
                                elif isinstance(item, str):
                                    text_parts.append(item)
                            
                            if text_parts:
                                return {
                                    'agent': agent.name,
                                    'content': '\n'.join(text_parts)
                                }
                        
                        logger.info(f"Agent {agent.name} 处理完成 - ID: {message_id}")
                        return None
                        
                    except Exception as e:
                        logger.error(f"Agent {agent.name} 处理错误 - ID: {message_id}, 错误: {str(e)}")
                        return {
                            'agent': agent.name,
                            'content': f'处理时出错: {str(e)}'
                        }
                
                tasks = [process_agent(agent) for agent in [researcher, analyst, writer]]
                results = await asyncio.gather(*tasks)
                
                for result in results:
                    if result:
                        responses.append(result)
                        
            else:
                logger.info("使用顺序执行模式")
                
                async with MsgHub(
                    participants=[researcher, analyst, writer],
                    announcement=Msg("系统", message, "system")
                ) as hub:
                    for agent in [researcher, analyst, writer]:
                        try:
                            msg = Msg(name="user", content=message, role="user")
                            response = await agent(msg)
                            
                            content = response.content
                            if isinstance(content, str):
                                responses.append({
                                    'agent': agent.name,
                                    'content': content
                                })
                            elif isinstance(content, list):
                                text_parts = []
                                for item in content:
                                    if isinstance(item, dict):
                                        if item.get('type') == 'text':
                                            text_parts.append(item.get('text', ''))
                                    elif isinstance(item, str):
                                        text_parts.append(item)
                                
                                if text_parts:
                                    responses.append({
                                        'agent': agent.name,
                                        'content': '\n'.join(text_parts)
                                    })
                            
                            logger.info(f"Agent {agent.name} 处理完成 - ID: {message_id}")
                            
                        except Exception as e:
                            logger.error(f"Agent {agent.name} 处理错误 - ID: {message_id}, 错误: {str(e)}")
                            responses.append({
                                'agent': agent.name,
                                'content': f'处理时出错: {str(e)}'
                            })
                            continue
            
            return responses
        
        responses = asyncio.run(get_response())
        
        logger.info(f"Web消息处理完成 - ID: {message_id}, 响应数量: {len(responses)}")
        
        return jsonify({'responses': responses})
    except Exception as e:
        logger.error(f"Web消息处理异常: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)})

@app.route('/feishu/webhook', methods=['POST'])
def feishu_webhook():
    try:
        data = request.json
        logger.info(f"收到飞书消息: {json.dumps(data, ensure_ascii=False)}")
        
        if data.get('type') == 'url_verification':
            challenge = data.get('challenge', '')
            logger.info(f"飞书URL验证请求: {challenge}")
            return jsonify({'challenge': challenge})
        
        event = data.get('event', {})
        message_type = event.get('message_type', 'text')
        
        if message_type == 'text':
            message_content = event.get('message', {}).get('content', '')
            try:
                content_json = json.loads(message_content)
                text_content = content_json.get('text', '')
            except:
                text_content = message_content
            
            message_id = event.get('message_id', f"feishu_{datetime.now().timestamp()}")
            sender_id = event.get('sender', {}).get('sender_id', {}).get('open_id', 'unknown')
            
            logger.info(f"飞书消息处理 - 发送者: {sender_id}, 内容: {text_content}")
            
            message_manager.add_message(
                source='feishu',
                message_id=message_id,
                content=text_content,
                metadata={
                    'sender_id': sender_id,
                    'message_type': message_type,
                    'event': event
                }
            )
            
            threading.Thread(
                target=process_message_async,
                args=(message_id, text_content, 'feishu'),
                daemon=True
            ).start()
            
            response = message_manager.get_response(message_id, timeout=60.0)
            
            if response and response.get('status') == 'success':
                logger.info(f"飞书消息处理成功 - ID: {message_id}")
                return jsonify({
                    'status': 'success',
                    'message_id': message_id,
                    'responses': response.get('responses', [])
                })
            else:
                logger.error(f"飞书消息处理失败 - ID: {message_id}")
                return jsonify({
                    'status': 'error',
                    'message_id': message_id,
                    'error': response.get('error', '处理失败') if response else '处理超时'
                })
        
        return jsonify({'status': 'ignored', 'message': '不支持的消息类型'})
        
    except Exception as e:
        logger.error(f"飞书webhook处理错误: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500

def process_message_async(message_id: str, content: str, source: str):
    try:
        logger.info(f"开始处理消息 - ID: {message_id}, 来源: {source}")
        
        async def get_response():
            responses = []
            
            async with MsgHub(
                participants=[researcher, analyst, writer],
                announcement=Msg("系统", content, "system")
            ) as hub:
                for agent in [researcher, analyst, writer]:
                    try:
                        msg = Msg(name="user", content=content, role="user")
                        response = await agent(msg)
                        
                        agent_content = response.content
                        if isinstance(agent_content, str):
                            responses.append({
                                'agent': agent.name,
                                'content': agent_content
                            })
                        elif isinstance(agent_content, list):
                            text_parts = []
                            for item in agent_content:
                                if isinstance(item, dict):
                                    if item.get('type') == 'text':
                                        text_parts.append(item.get('text', ''))
                                elif isinstance(item, str):
                                    text_parts.append(item)
                            
                            if text_parts:
                                responses.append({
                                    'agent': agent.name,
                                    'content': '\n'.join(text_parts)
                                })
                        
                        logger.info(f"Agent {agent.name} 处理完成 - ID: {message_id}")
                        
                    except Exception as e:
                        logger.error(f"Agent {agent.name} 处理错误 - ID: {message_id}, 错误: {str(e)}")
                        responses.append({
                            'agent': agent.name,
                            'content': f'处理时出错: {str(e)}'
                        })
                        continue
            
            return responses
        
        responses = asyncio.run(get_response())
        
        message_manager.put_response(message_id, {
            'status': 'success',
            'responses': responses
        })
        
        logger.info(f"消息处理完成 - ID: {message_id}, 响应数量: {len(responses)}")
        
    except Exception as e:
        logger.error(f"消息处理异常 - ID: {message_id}, 错误: {str(e)}", exc_info=True)
        message_manager.put_response(message_id, {
            'status': 'error',
            'error': str(e)
        })

@app.route('/feishu/status', methods=['GET'])
def feishu_status():
    return jsonify({
        'status': 'active',
        'message_queue_size': message_manager.message_queue.qsize(),
        'pending_responses': len(message_manager.response_queues)
    })

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("多 Agent Web 界面启动中...")
    print("=" * 60)
    print("\n访问地址: http://localhost:5000")
    print("飞书Webhook: http://localhost:5000/feishu/webhook")
    print("\n按 Ctrl+C 停止服务\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
