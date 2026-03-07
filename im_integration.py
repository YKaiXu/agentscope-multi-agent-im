#!/usr/bin/env python3
import os
import asyncio
from typing import AsyncGenerator
from dataclasses import dataclass
from dotenv import load_dotenv
import agentscope
from agentscope.agent import ReActAgent
from agentscope.model import OpenAIChatModel
from agentscope.memory import InMemoryMemory
from agentscope.formatter import OpenAIChatFormatter
from agentscope.pipeline import MsgHub, sequential_pipeline
from agentscope.message import Msg

load_dotenv()

print("=" * 60)
print("多 Agent + IM 集成系统")
print("=" * 60)

@dataclass
class IMMessage:
    content: str
    sender: str
    channel: str

class BaseChannel:
    async def receive(self) -> AsyncGenerator[IMMessage, None]:
        raise NotImplementedError
    
    async def send(self, message: str, **kwargs):
        raise NotImplementedError

class SimpleWebChannel(BaseChannel):
    def __init__(self):
        self.messages = []
    
    async def receive(self) -> AsyncGenerator[IMMessage, None]:
        while True:
            user_input = input("\n用户: ").strip()
            if user_input.lower() in ['exit', 'quit']:
                break
            yield IMMessage(content=user_input, sender="user", channel="web")
    
    async def send(self, message: str, **kwargs):
        print(f"\n助手: {message}")
        self.messages.append(message)

agentscope.init(
    project="multi_agent_im"
)

print("\n步骤 1: 创建多个 Agent")
print("-" * 60)

model = OpenAIChatModel(
    model_name="GLM-4.7-Flash",
    api_key=os.getenv("ZHIPU_API_KEY"),
    client_kwargs={
        "base_url": "https://open.bigmodel.cn/api/paas/v4"
    }
)

researcher = ReActAgent(
    name="研究员",
    sys_prompt="你负责收集和整理信息，提供事实和数据支持。",
    model=model,
    memory=InMemoryMemory(),
    formatter=OpenAIChatFormatter()
)

analyst = ReActAgent(
    name="分析师",
    sys_prompt="你负责分析数据并给出见解和建议。",
    model=model,
    memory=InMemoryMemory(),
    formatter=OpenAIChatFormatter()
)

writer = ReActAgent(
    name="撰写员",
    sys_prompt="你负责将分析结果整理成清晰的报告。",
    model=model,
    memory=InMemoryMemory(),
    formatter=OpenAIChatFormatter()
)

print("✓ 已创建 3 个 Agent")

async def process_message(channel: BaseChannel):
    async for im_msg in channel.receive():
        print(f"\n{'='*60}")
        print(f"收到消息: {im_msg.content}")
        print(f"发送者: {im_msg.sender}")
        print(f"渠道: {im_msg.channel}")
        print(f"{'='*60}")
        
        async with MsgHub(
            participants=[researcher, analyst, writer],
            announcement=Msg("系统", im_msg.content, "system")
        ) as hub:
            await sequential_pipeline([researcher, analyst, writer])
            
            print("\n✓ 多 Agent 协作完成")

async def main():
    print("\n步骤 2: 初始化 IM 渠道")
    print("-" * 60)
    
    channel = SimpleWebChannel()
    
    print("✓ Web 渠道已初始化")
    
    print("\n步骤 3: 启动消息处理")
    print("-" * 60)
    
    print("\n系统已就绪！输入消息开始对话（输入 'exit' 退出）")
    
    await process_message(channel)

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("使用说明")
    print("=" * 60)
    print("\n这是一个简化的 IM 集成示例")
    print("完整集成请参考:")
    print("  - channels/ 目录中的飞书/钉钉/QQ 实现")
    print("  - MULTI_AGENT_IM_SOLUTION.md 文档")
    
    asyncio.run(main())
