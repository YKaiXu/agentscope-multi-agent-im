#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web聊天服务

基于Streamlit实现Web聊天界面，支持多Agent对话
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('web_channel.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent
CONFIG_FILE = PROJECT_DIR / "config.json"

@dataclass
class AgentConfig:
    name: str
    role: str
    model: str
    sys_prompt: str = ""
    enabled: bool = True
    im_platform: str = "global"
    max_iters: int = 10
    print_hint_msg: bool = True
    formatter: str = "OpenAIChatFormatter"
    long_term_memory_enabled: bool = False
    long_term_memory_mode: str = "both"
    ltm_agent_name: str = ""
    toolkit_enabled: bool = False
    enable_meta_tool: bool = False
    parallel_tool_calls: bool = False
    knowledge_enabled: bool = False
    knowledge_documents: List[str] = field(default_factory=list)
    enable_rewrite_query: bool = False
    plan_notebook_enabled: bool = False

def load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"agents": [], "llms": [], "im": {"global_im": {}}}

def save_config(config: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def get_agent_configs(config: Dict[str, Any]) -> List[AgentConfig]:
    agents = []
    for agent_data in config.get("agents", []):
        if agent_data.get("enabled", True):
            agent = AgentConfig(
                name=agent_data.get("name", ""),
                role=agent_data.get("role", ""),
                model=agent_data.get("model", ""),
                sys_prompt=agent_data.get("sys_prompt", ""),
                enabled=agent_data.get("enabled", True),
                im_platform=agent_data.get("im_platform", "global"),
                max_iters=agent_data.get("max_iters", 10),
                print_hint_msg=agent_data.get("print_hint_msg", True),
                formatter=agent_data.get("formatter", "OpenAIChatFormatter"),
                long_term_memory_enabled=agent_data.get("long_term_memory_enabled", False),
                long_term_memory_mode=agent_data.get("long_term_memory_mode", "both"),
                ltm_agent_name=agent_data.get("ltm_agent_name", ""),
                toolkit_enabled=agent_data.get("toolkit_enabled", False),
                enable_meta_tool=agent_data.get("enable_meta_tool", False),
                parallel_tool_calls=agent_data.get("parallel_tool_calls", False),
                knowledge_enabled=agent_data.get("knowledge_enabled", False),
                knowledge_documents=agent_data.get("knowledge_documents", []),
                enable_rewrite_query=agent_data.get("enable_rewrite_query", False),
                plan_notebook_enabled=agent_data.get("plan_notebook_enabled", False),
            )
            agents.append(agent)
    return agents

def get_api_config(llm_id: str, config: Dict[str, Any]) -> Dict[str, str]:
    llms = config.get("llms", [])
    for llm in llms:
        if llm.get("id") == llm_id:
            return {
                "api_key": llm.get("api_key", ""),
                "base_url": llm.get("base_url", ""),
                "model_id": llm.get("model_id", ""),
            }
    return {}

async def create_agent(agent_config: AgentConfig, config: Dict[str, Any]) -> Any:
    try:
        import agentscope
        from agentscope.agent import ReActAgent
        from agentscope.model import OpenAIChatModel
        from agentscope.memory import InMemoryMemory
        from agentscope.formatter import OpenAIChatFormatter

        api_config = get_api_config(agent_config.model, config)
        if not api_config.get("api_key"):
            logger.error(f"Agent {agent_config.name} 缺少API配置")
            return None

        model = OpenAIChatModel(
            model_name=api_config.get("model_id", agent_config.model),
            api_key=api_config["api_key"],
            client_kwargs={"base_url": api_config["base_url"]},
        )

        sys_prompt = agent_config.sys_prompt or f"你是一个{agent_config.role}。"

        memory = InMemoryMemory()
        formatter = OpenAIChatFormatter()

        agent_kwargs = {
            "name": agent_config.name,
            "sys_prompt": sys_prompt,
            "model": model,
            "memory": memory,
            "formatter": formatter,
            "max_iters": agent_config.max_iters,
            "print_hint_msg": agent_config.print_hint_msg,
        }

        if agent_config.long_term_memory_enabled:
            from agentscope.memory import LongTermMemory
            ltm_name = agent_config.ltm_agent_name or agent_config.name
            long_term_memory = LongTermMemory(
                ltm_name,
                mode=agent_config.long_term_memory_mode,
            )
            agent_kwargs["long_term_memory"] = long_term_memory
            logger.info(f"Agent {agent_config.name} 启用长期记忆: {ltm_name}")

        if agent_config.toolkit_enabled:
            from agentscope.tools import default_toolset
            agent_kwargs["toolkit"] = default_toolset
            agent_kwargs["enable_meta_tool"] = agent_config.enable_meta_tool
            agent_kwargs["parallel_tool_calls"] = agent_config.parallel_tool_calls

        agent = ReActAgent(**agent_kwargs)
        logger.info(f"成功创建Agent: {agent_config.name}")
        return agent

    except Exception as e:
        logger.error(f"创建Agent失败 {agent_config.name}: {e}")
        return None

class WebChatService:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.agents: Dict[str, Any] = {}
        self.chat_history: List[Dict[str, str]] = []
        
    async def initialize(self):
        agent_configs = get_agent_configs(self.config)
        for agent_config in agent_configs:
            agent = await create_agent(agent_config, self.config)
            if agent:
                self.agents[agent_config.name] = agent
        logger.info(f"初始化了 {len(self.agents)} 个Agent")
    
    async def chat_single(self, agent_name: str, message: str) -> str:
        if agent_name not in self.agents:
            return f"Agent {agent_name} 不存在"
        
        from agentscope.message import Msg
        agent = self.agents[agent_name]
        msg = Msg(name="user", content=message, role="user")
        
        try:
            response = await agent(msg)
            return getattr(response, "content", str(response)) if response else "无响应"
        except Exception as e:
            logger.error(f"Agent {agent_name} 响应失败: {e}")
            return f"错误: {e}"
    
    async def chat_msghub(self, message: str) -> str:
        if not self.agents:
            return "没有可用的Agent"
        
        try:
            from agentscope.msghub import MsgHub
            from agentscope.message import Msg
            
            agents = list(self.agents.values())
            responses = []
            
            async with MsgHub(
                participants=agents,
                announcement=Msg("system", f"用户消息：{message}", "system"),
            ):
                for name, agent in self.agents.items():
                    try:
                        response = await agent()
                        if response:
                            responses.append(f"**{name}**: {getattr(response, 'content', str(response))}")
                    except Exception as e:
                        logger.warning(f"Agent {name} 响应失败: {e}")
            
            if responses:
                return "\n\n---\n\n".join(responses)
            return "所有Agent都未能响应"
            
        except Exception as e:
            logger.error(f"MsgHub处理失败: {e}")
            return f"MsgHub处理失败: {e}"

def main():
    st.set_page_config(
        page_title="AgentScope Web Chat",
        page_icon="🤖",
        layout="wide"
    )
    
    st.title("🤖 AgentScope Web Chat")
    
    config = load_config()
    
    if "chat_service" not in st.session_state:
        service = WebChatService(config)
        asyncio.run(service.initialize())
        st.session_state.chat_service = service
    
    service = st.session_state.chat_service
    
    web_config = config.get("im", {}).get("global_im", {}).get("web", {})
    mode = web_config.get("mode", "single")
    
    if mode == "msghub":
        st.info("🌐 多Agent协作模式")
        
        if "messages" not in st.session_state:
            st.session_state.messages = []
        
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        if prompt := st.chat_input("输入消息"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("思考中..."):
                    response = asyncio.run(service.chat_msghub(prompt))
                    st.markdown(response)
            
            st.session_state.messages.append({"role": "assistant", "content": response})
    else:
        st.info("🌐 单Agent对话模式")
        
        agent_names = list(service.agents.keys())
        if not agent_names:
            st.error("没有可用的Agent，请先在配置中心创建Agent")
            return
        
        selected_agent = st.selectbox("选择Agent", agent_names)
        
        if f"messages_{selected_agent}" not in st.session_state:
            st.session_state[f"messages_{selected_agent}"] = []
        
        for message in st.session_state[f"messages_{selected_agent}"]:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        if prompt := st.chat_input("输入消息"):
            st.session_state[f"messages_{selected_agent}"].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("思考中..."):
                    response = asyncio.run(service.chat_single(selected_agent, prompt))
                    st.markdown(response)
            
            st.session_state[f"messages_{selected_agent}"].append({"role": "assistant", "content": response})

if __name__ == "__main__":
    main()
