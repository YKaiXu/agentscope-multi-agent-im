#!/usr/bin/env python3
import os
import asyncio
import json
from pathlib import Path
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

agentscope.init(
    project="multi_agent_im"
)

print("\n步骤 1: 加载配置并创建 Agent")
print("-" * 60)

def load_config(config_path: str = "config.json") -> dict:
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def get_api_config(config: dict, model: str) -> dict:
    api_config = config.get("api", {})

    if "GLM" in model.upper() or "Qwen" in model or "THUDM" in model:
        if "siliconflow" in api_config and api_config["siliconflow"].get("api_key"):
            return {
                "api_key": api_config["siliconflow"]["api_key"],
                "base_url": api_config["siliconflow"].get(
                    "base_url", "https://api.siliconflow.cn/v1/"
                ),
            }
        if "zhipu" in api_config and api_config["zhipu"].get("api_key"):
            return {
                "api_key": api_config["zhipu"]["api_key"],
                "base_url": api_config["zhipu"].get(
                    "base_url",
                    "https://open.bigmodel.cn/api/paas/v4/",
                ),
            }

    if "openai" in api_config and api_config["openai"].get("api_key"):
        return {
            "api_key": api_config["openai"]["api_key"],
            "base_url": api_config["openai"].get(
                "base_url", "https://api.openai.com/v1/"
            ),
        }

    return {}

def create_agent_from_config(agent_data: dict, config: dict) -> ReActAgent:
    name = agent_data.get("name", "Unknown")
    model_name = agent_data.get("model", "GLM-4.7-Flash")
    
    api_config = get_api_config(config, model_name)
    if not api_config.get("api_key"):
        raise ValueError(f"Agent {name} 缺少API配置")

    model = OpenAIChatModel(
        model_name=model_name,
        api_key=api_config["api_key"],
        client_kwargs={"base_url": api_config["base_url"]},
    )

    sys_prompt = agent_data.get("sys_prompt", agent_data.get("system_prompt", ""))
    if not sys_prompt:
        role = agent_data.get("role", "")
        sys_prompt = f"你是一个{role}。"

    memory = InMemoryMemory()

    formatter = OpenAIChatFormatter()

    agent_kwargs = {
        "name": name,
        "sys_prompt": sys_prompt,
        "model": model,
        "memory": memory,
        "formatter": formatter,
        "max_iters": agent_data.get("max_iters", 10),
        "print_hint_msg": agent_data.get("print_hint_msg", True),
    }

    if agent_data.get("long_term_memory_enabled", False):
        from agentscope.memory import LongTermMemory
        long_term_memory = LongTermMemory(
            name,
            mode=agent_data.get("long_term_memory_mode", "both"),
        )
        agent_kwargs["long_term_memory"] = long_term_memory

    if agent_data.get("toolkit_enabled", False):
        from agentscope.tools import default_toolset
        agent_kwargs["toolkit"] = default_toolset
        agent_kwargs["enable_meta_tool"] = agent_data.get("enable_meta_tool", False)
        agent_kwargs["parallel_tool_calls"] = agent_data.get("parallel_tool_calls", False)

    if agent_data.get("knowledge_enabled", False):
        from agentscope.knowledge import Knowledge
        knowledge = Knowledge(name)
        agent_kwargs["knowledge"] = knowledge
        agent_kwargs["enable_rewrite_query"] = agent_data.get("enable_rewrite_query", False)

    if agent_data.get("plan_notebook_enabled", False):
        from agentscope.notebook import Notebook
        notebook = Notebook(name)
        agent_kwargs["plan_notebook"] = notebook

    agent = ReActAgent(**agent_kwargs)
    return agent

config = load_config()
agents = []

agents_config = config.get("agents", [])
for agent_data in agents_config:
    if agent_data.get("enabled", True):
        try:
            agent = create_agent_from_config(agent_data, config)
            agents.append(agent)
            print(f"  ✓ 已创建 Agent: {agent.name}")
        except Exception as e:
            print(f"  ✗ 创建 Agent 失败: {agent_data.get('name', 'Unknown')} - {e}")

if not agents:
    print("\n未找到有效配置，使用默认Agent...")
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
    agents = [researcher, analyst, writer]
    print("  ✓ 已创建 3 个默认 Agent")

print(f"\n共加载 {len(agents)} 个 Agent")

print("\n步骤 2: 多 Agent 协作示例")
print("-" * 60)

async def multi_agent_workflow(user_message: str):
    print(f"\n用户输入: {user_message}")
    print("\n开始多 Agent 协作...")
    
    async with MsgHub(
        participants=agents,
        announcement=Msg("系统", f"任务: {user_message}", "system")
    ) as hub:
        await sequential_pipeline(agents)
        
        print("\n✓ 多 Agent 协作完成")

async def main():
    while True:
        try:
            user_input = input("\n请输入任务（输入 'exit' 退出）: ").strip()
            
            if user_input.lower() in ['exit', 'quit', '退出', 'q']:
                print("\n再见！")
                break
            
            if not user_input:
                continue
            
            await multi_agent_workflow(user_input)
            
        except KeyboardInterrupt:
            print("\n\n再见！")
            break
        except Exception as e:
            print(f"\n错误: {e}")

print("\n" + "=" * 60)
print("系统已就绪")
print("=" * 60)
print("\n使用方式:")
print("  1. 直接运行此脚本进行命令行交互")
print("  2. 集成 IM 模块（见 im_integration.py）")

asyncio.run(main())
