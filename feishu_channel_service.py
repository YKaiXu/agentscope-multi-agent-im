#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书消息接收服务

功能:
1. 读取config.json配置文件
2. 检测哪些Agent配置了飞书IM平台
3. 为每个配置了飞书的Agent启动飞书Channel服务
4. 监听飞书WebSocket事件
5. 接收飞书消息并路由到对应的Agent
6. 将Agent的响应发送回飞书
"""

import asyncio
import base64
import io
import json
import logging
import mimetypes
import os
import signal
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateImageRequest,
        CreateImageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        Emoji,
        P2ImMessageReceiveV1,
    )
    LARK_AVAILABLE = True
except ImportError:
    LARK_AVAILABLE = False
    logger.warning("lark-oapi 未安装, 飞书功能将不可用")


@dataclass
class AgentConfig:
    name: str
    role: str
    model: str
    sys_prompt: str = ""
    memory_type: str = "InMemoryMemory"
    long_term_memory_enabled: bool = False
    long_term_memory_mode: str = "both"
    ltm_agent_name: str = ""
    embedding_model: str = ""
    toolkit_enabled: bool = False
    enable_meta_tool: bool = False
    parallel_tool_calls: bool = False
    knowledge_enabled: bool = False
    enable_rewrite_query: bool = False
    knowledge_documents: list = field(default_factory=list)
    plan_notebook_enabled: bool = False
    max_iters: int = 10
    print_hint_msg: bool = True
    formatter: str = "OpenAIChatFormatter"
    im_platform: str = "global"
    im_app_id: str = ""
    im_app_secret: str = ""
    enabled: bool = True


@dataclass
class FeishuAgentService:
    agent_config: AgentConfig
    channel: Any = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    model: Any = None
    agent: Any = None


class FeishuMessageRouter:
    """飞书消息路由器，支持单Agent、关键词触发、MsgHub协作模式"""
    
    def __init__(self, config: Dict[str, Any], agents: List[FeishuAgentService]):
        self.config = config
        self.agents = agents
        self.agent_map = {svc.agent_config.name: svc for svc in agents}
        
        feishu_config = config.get("im", {}).get("global_im", {}).get("feishu", {})
        self.route_mode = feishu_config.get("route_mode", "single")
        self.route_keywords = feishu_config.get("route_keywords", {})
        self.msghub_announcement = feishu_config.get("msghub_announcement", "请大家协作完成这个任务")
    
    def route_message(self, message: str) -> Tuple[str, Optional[str]]:
        """
        路由消息，返回 (模式, 目标Agent名称或None)
        """
        if self.route_mode == "single":
            if len(self.agents) == 1:
                return ("single", self.agents[0].agent_config.name)
            return ("single", None)
        
        elif self.route_mode == "keyword":
            for keyword, agent_name in self.route_keywords.items():
                if keyword in message:
                    return ("keyword", agent_name)
            return ("single", self.agents[0].agent_config.name if self.agents else None)
        
        elif self.route_mode == "msghub":
            return ("msghub", None)
        
        return ("single", None)
    
    async def process_with_msghub(self, message: str) -> str:
        """使用MsgHub模式处理消息，所有Agent协作"""
        try:
            from agentscope.msghub import MsgHub
            from agentscope.message import Msg
            
            agents = [svc.agent for svc in self.agents if svc.agent]
            if not agents:
                return "没有可用的Agent"
            
            responses = []
            async with MsgHub(
                participants=agents,
                announcement=Msg("system", self.msghub_announcement + f"\n\n用户消息：{message}", "system"),
            ):
                for svc in self.agents:
                    if svc.agent:
                        try:
                            response = await svc.agent()
                            if response:
                                responses.append(f"**{svc.agent_config.name}**: {getattr(response, 'content', str(response))}")
                        except Exception as e:
                            logger.warning(f"Agent {svc.agent_config.name} 响应失败: {e}")
            
            if responses:
                return "\n\n---\n\n".join(responses)
            return "所有Agent都未能响应"
            
        except Exception as e:
            logger.exception(f"MsgHub处理失败: {e}")
            return f"MsgHub处理失败: {e}"


class SimpleFeishuChannel:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        agent: Any,
        agent_name: str,
        media_dir: str = "~/.copaw/media",
        router: Optional[FeishuMessageRouter] = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.agent = agent
        self.agent_name = agent_name
        self.router = router
        self._media_dir = Path(media_dir).expanduser()
        self._media_dir.mkdir(parents=True, exist_ok=True)

        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()

        self._tenant_access_token: Optional[str] = None
        self._tenant_access_token_expire_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._http: Optional[aiohttp.ClientSession] = None

        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._receive_id_store: Dict[str, Tuple[str, str]] = {}
        self._bot_open_id: Optional[str] = None

    async def _get_bot_info(self) -> Optional[str]:
        if self._bot_open_id:
            return self._bot_open_id

        if not self._http:
            return None

        try:
            token = await self._get_tenant_access_token()
            url = "https://open.feishu.cn/open-apis/bot/v3/info"
            headers = {"Authorization": f"Bearer {token}"}
            async with self._http.get(url, headers=headers) as resp:
                data = await resp.json(content_type=None)
                if data.get("code") == 0:
                    bot_info = data.get("bot", {})
                    self._bot_open_id = bot_info.get("open_id")
                    if self._bot_open_id:
                        logger.info(f"获取机器人open_id成功: {self._bot_open_id}")
                        return self._bot_open_id
        except Exception:
            logger.exception("获取机器人信息失败")
        return None

    async def _get_tenant_access_token(self) -> str:
        now = time.time()
        if (
            self._tenant_access_token
            and now < self._tenant_access_token_expire_at - 300
        ):
            return self._tenant_access_token

        async with self._token_lock:
            now = time.time()
            if (
                self._tenant_access_token
                and now < self._tenant_access_token_expire_at - 300
            ):
                return self._tenant_access_token

            url = (
                "https://open.feishu.cn/open-apis/auth/v3/"
                "tenant_access_token/internal"
            )
            payload = {
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            }
            async with self._http.post(url, json=payload) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise RuntimeError(
                        f"Feishu token failed status={resp.status}"
                    )

            if data.get("code") != 0:
                raise RuntimeError(
                    f"Feishu token error code={data.get('code')}"
                )

            token = data.get("tenant_access_token")
            if not token:
                raise RuntimeError("Feishu token missing in response")

            expire = int(data.get("expire", 3600))
            self._tenant_access_token = token
            self._tenant_access_token_expire_at = now + expire
            logger.info(f"获取飞书token成功, 有效期: {expire}秒")
            return token

    async def _send_text(
        self,
        receive_id_type: str,
        receive_id: str,
        text: str,
    ) -> bool:
        if not self._client:
            return False

        try:
            post_content = {
                "zh_cn": {
                    "content": [[{"tag": "md", "text": text}]]
                }
            }
            content = json.dumps(post_content, ensure_ascii=False)

            req = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type("post")
                    .content(content)
                    .build()
                )
                .build()
            )
            resp = self._client.im.v1.message.create(req)
            if not resp.success():
                logger.warning(
                    f"飞书发送失败 code={getattr(resp, 'code', '')} "
                    f"msg={getattr(resp, 'msg', '')}"
                )
                return False
            logger.info(f"飞书消息发送成功: {self.agent_name}")
            return True
        except Exception:
            logger.exception("飞书发送消息失败")
            return False

    async def _add_reaction(self, message_id: str, emoji_type: str = "Typing") -> None:
        if not self._client:
            return
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._add_reaction_sync,
                message_id,
                emoji_type,
            )
        except Exception:
            pass

    def _add_reaction_sync(self, message_id: str, emoji_type: str) -> None:
        try:
            req = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(
                        Emoji.builder().emoji_type(emoji_type).build()
                    )
                    .build()
                )
                .build()
            )
            self._client.im.v1.message_reaction.create(req)
        except Exception:
            pass

    def _on_message_sync(self, data: "P2ImMessageReceiveV1") -> None:
        logger.info(f"[DEBUG] _on_message_sync 被调用, data type: {type(data)}")
        if data:
            logger.info(f"[DEBUG] data.event: {getattr(data, 'event', None)}")
        if not self._loop or not self._loop.is_running():
            logger.warning("[DEBUG] loop未运行, 跳过消息处理")
            return
        asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)

    async def _on_message(self, data: "P2ImMessageReceiveV1") -> None:
        if not data or not getattr(data, "event", None):
            return

        try:
            event = data.event
            message = getattr(event, "message", None)
            sender = getattr(event, "sender", None)
            if not message or not sender:
                return

            message_id = str(getattr(message, "message_id", "") or "").strip()
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            sender_type = getattr(sender, "sender_type", "") or ""
            if sender_type == "bot":
                return

            sender_id_obj = getattr(sender, "sender_id", None)
            sender_id = ""
            if sender_id_obj and getattr(sender_id_obj, "open_id", None):
                sender_id = str(getattr(sender_id_obj, "open_id", "")).strip()
            if not sender_id:
                sender_id = f"unknown_{message_id[:8]}"

            chat_id = str(getattr(message, "chat_id", "") or "").strip()
            chat_type = str(
                getattr(message, "chat_type", "p2p") or "p2p"
            ).strip()
            msg_type = str(
                getattr(message, "message_type", "text") or "text"
            ).strip()
            content_raw = getattr(message, "content", None) or "{}"
            mentions = getattr(message, "mentions", None) or []

            await self._add_reaction(message_id, "Typing")

            user_message = ""
            if msg_type == "text":
                try:
                    content_json = json.loads(content_raw) if content_raw else {}
                    user_message = content_json.get("text", "")
                except json.JSONDecodeError:
                    user_message = str(content_raw)

            if not user_message.strip():
                return

            if chat_type == "group":
                bot_open_id = await self._get_bot_info()
                is_mentioned = False

                if mentions and bot_open_id:
                    for mention in mentions:
                        mention_id = getattr(mention, "id", None)
                        if mention_id:
                            mention_open_id = getattr(mention_id, "open_id", "")
                            if mention_open_id == bot_open_id:
                                is_mentioned = True
                                break

                if not is_mentioned:
                    user_message_lower = user_message.lower()
                    if "<at" in user_message_lower and "user_id" in user_message_lower:
                        if bot_open_id and bot_open_id in user_message:
                            is_mentioned = True

                if not is_mentioned:
                    logger.info(
                        f"群聊消息未@机器人, 忽略: chat={chat_id[:20]}"
                    )
                    return

                user_message = user_message.replace(f"<at user_id=\"{bot_open_id}\"></at>", "").strip()
                user_message = user_message.replace(f"<at user_id='{bot_open_id}'></at>", "").strip()
                user_message = user_message.replace(f"@_user_{bot_open_id}", "").strip()
                user_message = user_message.strip()

            logger.info(
                f"飞书收到消息 from={sender_id[:20]} chat={chat_id[:20]} "
                f"msg={user_message[:50]}..."
            )

            receive_id = chat_id if chat_type == "group" else sender_id
            receive_id_type = "chat_id" if chat_type == "group" else "open_id"

            try:
                from agentscope.message import Msg

                response_text = ""
                
                if self.router:
                    mode, target_agent = self.router.route_message(user_message)
                    
                    if mode == "msghub":
                        response_text = await self.router.process_with_msghub(user_message)
                    elif mode == "keyword" and target_agent:
                        target_svc = self.router.agent_map.get(target_agent)
                        if target_svc and target_svc.agent:
                            msg = Msg(name="user", content=user_message, role="user")
                            response = await target_svc.agent(msg)
                            response_text = getattr(response, "content", str(response)) if response else ""
                        else:
                            response_text = f"Agent {target_agent} 不可用"
                    else:
                        msg = Msg(name="user", content=user_message, role="user")
                        response = await self.agent(msg)
                        response_text = getattr(response, "content", str(response)) if response else ""
                else:
                    msg = Msg(name="user", content=user_message, role="user")
                    response = await self.agent(msg)
                    if hasattr(response, "content"):
                        if isinstance(response.content, str):
                            response_text = response.content
                        elif isinstance(response.content, list):
                            texts = []
                            for item in response.content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    texts.append(item.get("text", ""))
                                elif isinstance(item, str):
                                    texts.append(item)
                            response_text = "\n".join(texts)

                if response_text:
                    logger.info(
                        f"Agent {self.agent_name} 响应: {response_text[:50]}..."
                    )
                    await self._send_text(receive_id_type, receive_id, response_text)

            except Exception as e:
                logger.exception(f"Agent处理消息失败: {e}")
                await self._send_text(
                    receive_id_type, receive_id,
                    f"处理消息时出错: {str(e)}"
                )

        except Exception:
            logger.exception("飞书消息处理失败")

    def _run_ws_forever(self) -> None:
        ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)
        try:
            import lark_oapi.ws.client as ws_client
            ws_client.loop = ws_loop
        except ImportError:
            pass

        try:
            if self._ws_client:
                logger.info(f"飞书WebSocket连接中 ({self.agent_name})...")
                self._ws_client.start()
        except Exception:
            logger.exception(f"飞书WebSocket线程失败 ({self.agent_name})")
        finally:
            self._stop_event.set()

    async def start(self) -> None:
        if not LARK_AVAILABLE:
            raise RuntimeError(
                "lark-oapi 未安装, 请运行: pip install lark-oapi"
            )

        if not self.app_id or not self.app_secret:
            raise RuntimeError("飞书 app_id 和 app_secret 是必需的")

        self._loop = asyncio.get_running_loop()
        self._client = (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(self.app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_sync)
            .build()
        )

        self._ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        self._stop_event.clear()
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever,
            daemon=True,
        )
        self._ws_thread.start()

        if self._http is None:
            self._http = aiohttp.ClientSession()

        await self._get_bot_info()

        logger.info(
            f"飞书Channel已启动: {self.agent_name} (App ID: {self.app_id[:12]}...)"
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception:
                pass
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
        if self._http is not None:
            await self._http.close()
            self._http = None
        self._client = None
        self._ws_client = None
        logger.info(f"飞书Channel已停止: {self.agent_name}")


class FeishuChannelService:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self.feishu_agents: List[FeishuAgentService] = []
        self.global_feishu_config: Dict[str, Any] = {}
        self._running = False
        self._stop_event = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def load_config(self) -> bool:
        try:
            if not self.config_path.exists():
                logger.error(f"配置文件不存在: {self.config_path}")
                return False

            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)

            logger.info(f"成功加载配置文件: {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return False

    def detect_feishu_agents(self) -> List[AgentConfig]:
        feishu_agents = []

        if "im" in self.config and "global_im" in self.config["im"]:
            self.global_feishu_config = self.config["im"]["global_im"].get(
                "feishu", {}
            )

        agents_config = self.config.get("agents", [])
        for agent_data in agents_config:
            im_platform = agent_data.get("im_platform", "global")

            if im_platform == "feishu":
                agent = AgentConfig(
                    name=agent_data.get("name", "Unknown"),
                    role=agent_data.get("role", ""),
                    model=agent_data.get("model", "GLM-4.7-Flash"),
                    sys_prompt=agent_data.get("sys_prompt", agent_data.get("system_prompt", "")),
                    memory_type=agent_data.get("memory_type", "InMemoryMemory"),
                    long_term_memory_enabled=agent_data.get("long_term_memory_enabled", False),
                    long_term_memory_mode=agent_data.get("long_term_memory_mode", "both"),
                    ltm_agent_name=agent_data.get("ltm_agent_name", agent_data.get("name", "Unknown")),
                    embedding_model=agent_data.get("embedding_model", ""),
                    toolkit_enabled=agent_data.get("toolkit_enabled", False),
                    enable_meta_tool=agent_data.get("enable_meta_tool", False),
                    parallel_tool_calls=agent_data.get("parallel_tool_calls", False),
                    knowledge_enabled=agent_data.get("knowledge_enabled", False),
                    enable_rewrite_query=agent_data.get("enable_rewrite_query", False),
                    knowledge_documents=agent_data.get("knowledge_documents", []),
                    plan_notebook_enabled=agent_data.get("plan_notebook_enabled", False),
                    max_iters=agent_data.get("max_iters", 10),
                    print_hint_msg=agent_data.get("print_hint_msg", True),
                    formatter=agent_data.get("formatter", "OpenAIChatFormatter"),
                    im_platform="feishu",
                    im_app_id=agent_data.get("im_app_id", ""),
                    im_app_secret=agent_data.get("im_app_secret", ""),
                    enabled=agent_data.get("enabled", True),
                )
                feishu_agents.append(agent)
                logger.info(
                    f"检测到飞书Agent: {agent.name} (App ID: {agent.im_app_id[:8]}...)"
                )

        return feishu_agents

    def get_api_config(self, llm_id: str) -> Dict[str, str]:
        llms = self.config.get("llms", [])
        for llm in llms:
            if llm.get("id") == llm_id:
                return {
                    "api_key": llm.get("api_key", ""),
                    "base_url": llm.get("base_url", ""),
                    "model_id": llm.get("model_id", ""),
                }
        return {}

    def get_embedding_config(self, emb_id: str) -> Dict[str, Any]:
        embeddings = self.config.get("embeddings", [])
        for emb in embeddings:
            if emb.get("id") == emb_id:
                return {
                    "provider": emb.get("provider", "OpenAI"),
                    "model_name": emb.get("model_name", ""),
                    "dimensions": emb.get("dimensions", 1024),
                    "api_key": emb.get("api_key", ""),
                    "base_url": emb.get("base_url", ""),
                }
        return {}

    def create_embedding_model(self, emb_config: Dict[str, Any]) -> Any:
        try:
            provider = emb_config.get("provider", "OpenAI")
            
            if provider == "OpenAI":
                from agentscope.embedding import OpenAITextEmbedding
                return OpenAITextEmbedding(
                    model_name=emb_config.get("model_name", "text-embedding-3-small"),
                    api_key=emb_config.get("api_key", ""),
                    base_url=emb_config.get("base_url", "https://api.openai.com/v1"),
                )
            elif provider == "DashScope":
                from agentscope.embedding import DashScopeTextEmbedding
                return DashScopeTextEmbedding(
                    model_name=emb_config.get("model_name", "text-embedding-v3"),
                    api_key=emb_config.get("api_key", ""),
                    dimensions=emb_config.get("dimensions", 1024),
                )
            elif provider == "Gemini":
                from agentscope.embedding import GeminiTextEmbedding
                return GeminiTextEmbedding(
                    model_name=emb_config.get("model_name", "text-embedding-004"),
                    api_key=emb_config.get("api_key", ""),
                )
            elif provider == "Ollama":
                from agentscope.embedding import OllamaTextEmbedding
                return OllamaTextEmbedding(
                    model_name=emb_config.get("model_name", "nomic-embed-text"),
                    base_url=emb_config.get("base_url", "http://localhost:11434"),
                )
            elif provider == "自定义":
                from agentscope.embedding import OpenAITextEmbedding
                return OpenAITextEmbedding(
                    model_name=emb_config.get("model_name", ""),
                    api_key=emb_config.get("api_key", ""),
                    base_url=emb_config.get("base_url", ""),
                )
            elif provider == "XFMaas":
                from agentscope.embedding import OpenAITextEmbedding
                return OpenAITextEmbedding(
                    api_key=emb_config.get("api_key", ""),
                    model_name=emb_config.get("model_name", ""),
                    dimensions=emb_config.get("dimensions", 1024),
                    base_url=emb_config.get("base_url", ""),
                )
            else:
                logger.error(f"不支持的Embedding提供商: {provider}")
                return None
        except Exception as e:
            logger.error(f"创建Embedding模型失败: {e}")
            return None

    async def create_agent(self, agent_config: AgentConfig) -> Any:
        try:
            import agentscope
            from agentscope.agent import ReActAgent
            from agentscope.model import OpenAIChatModel
            from agentscope.memory import InMemoryMemory
            from agentscope.formatter import OpenAIChatFormatter

            model_id = agent_config.model
            if not model_id:
                llms = self.config.get("llms", [])
                if llms:
                    model_id = llms[0].get("id", "")
                    logger.info(f"Agent {agent_config.name} 未指定模型，自动使用默认模型: {model_id}")
                else:
                    logger.error(f"Agent {agent_config.name} 未指定模型且无可用LLM配置")
                    return None

            api_config = self.get_api_config(model_id)
            if not api_config.get("api_key"):
                logger.error(f"Agent {agent_config.name} 缺少API配置")
                return None

            model = OpenAIChatModel(
                model_name=api_config.get("model_id", model_id),
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
                if agent_config.embedding_model:
                    try:
                        from agentscope.memory import Mem0LongTermMemory
                        import mem0.vector_stores.configs as vector_configs
                        
                        emb_config = self.get_embedding_config(agent_config.embedding_model)
                        if emb_config:
                            embedding_model = self.create_embedding_model(emb_config)
                            if embedding_model:
                                from pathlib import Path
                                data_dir = Path(__file__).parent / "data" / "qdrant"
                                data_dir.mkdir(parents=True, exist_ok=True)
                                
                                vector_store_config = vector_configs.VectorStoreConfig(
                                    provider="qdrant",
                                    config={
                                        "collection_name": f"ltm_{agent_config.name}",
                                        "path": str(data_dir),
                                    }
                                )
                                
                                long_term_memory = Mem0LongTermMemory(
                                    agent_name=agent_config.name,
                                    user_name="default_user",
                                    model=model,
                                    embedding_model=embedding_model,
                                    vector_store_config=vector_store_config,
                                )
                                agent_kwargs["long_term_memory"] = long_term_memory
                                logger.info(f"Agent {agent_config.name} 启用长期记忆 (Mem0LongTermMemory + Qdrant)")
                            else:
                                logger.warning(f"Agent {agent_config.name} Embedding模型创建失败，跳过长期记忆")
                        else:
                            logger.warning(f"Agent {agent_config.name} 未找到Embedding配置，跳过长期记忆")
                    except Exception as e:
                        logger.warning(f"Agent {agent_config.name} 长期记忆初始化失败: {e}，跳过")
                else:
                    logger.warning(f"Agent {agent_config.name} 启用了长期记忆但未配置Embedding模型，跳过")

            if agent_config.toolkit_enabled:
                from agentscope.tools import default_toolset
                agent_kwargs["toolkit"] = default_toolset
                agent_kwargs["enable_meta_tool"] = agent_config.enable_meta_tool
                agent_kwargs["parallel_tool_calls"] = agent_config.parallel_tool_calls

            if agent_config.knowledge_enabled:
                from agentscope.knowledge import Knowledge
                knowledge = Knowledge(agent_config.name)
                if agent_config.knowledge_documents:
                    for doc_path in agent_config.knowledge_documents:
                        try:
                            knowledge.add_document(doc_path)
                            logger.info(f"Agent {agent_config.name} 加载知识库文档: {doc_path}")
                        except Exception as e:
                            logger.warning(f"加载知识库文档失败 {doc_path}: {e}")
                agent_kwargs["knowledge"] = knowledge
                agent_kwargs["enable_rewrite_query"] = agent_config.enable_rewrite_query

            if agent_config.plan_notebook_enabled:
                from agentscope.notebook import Notebook
                notebook = Notebook(agent_config.name)
                agent_kwargs["plan_notebook"] = notebook

            agent = ReActAgent(**agent_kwargs)

            logger.info(f"成功创建Agent: {agent_config.name}")
            return agent

        except Exception as e:
            logger.error(f"创建Agent失败 {agent_config.name}: {e}")
            return None

    async def create_feishu_channel(
        self, agent_config: AgentConfig, agent: Any, router: Optional[FeishuMessageRouter] = None
    ) -> Optional[SimpleFeishuChannel]:
        try:
            app_id = agent_config.im_app_id
            app_secret = agent_config.im_app_secret

            if not app_id or not app_secret:
                global_app_id = self.global_feishu_config.get("app_id", "")
                global_app_secret = self.global_feishu_config.get(
                    "app_secret", ""
                )
                if global_app_id and global_app_secret:
                    app_id = global_app_id
                    app_secret = global_app_secret
                    logger.info(
                        f"Agent {agent_config.name} 使用全局飞书配置"
                    )
                else:
                    logger.error(
                        f"Agent {agent_config.name} 缺少飞书配置 (app_id/app_secret)"
                    )
                    return None

            channel = SimpleFeishuChannel(
                app_id=app_id,
                app_secret=app_secret,
                agent=agent,
                agent_name=agent_config.name,
                router=router,
            )

            logger.info(
                f"成功创建飞书Channel: {agent_config.name} (App ID: {app_id[:8]}...)"
            )
            return channel

        except Exception as e:
            logger.exception(
                f"创建飞书Channel失败 {agent_config.name}: {e}"
            )
            return None

    async def initialize_agents(self) -> bool:
        try:
            import agentscope

            agentscope.init(
                project="feishu_channel_service",
            )

            feishu_agent_configs = self.detect_feishu_agents()

            if not feishu_agent_configs:
                logger.warning("没有检测到配置飞书IM的Agent")
                return False

            for agent_config in feishu_agent_configs:
                agent = await self.create_agent(agent_config)
                if not agent:
                    continue

                service = FeishuAgentService(
                    agent_config=agent_config,
                    agent=agent,
                )
                self.feishu_agents.append(service)

            if not self.feishu_agents:
                logger.error("没有成功初始化任何飞书Agent服务")
                return False

            router = FeishuMessageRouter(self.config, self.feishu_agents)
            logger.info(f"消息路由器已创建，模式: {router.route_mode}")

            for svc in self.feishu_agents:
                channel = await self.create_feishu_channel(
                    svc.agent_config, svc.agent, router
                )
                if not channel:
                    continue
                svc.channel = channel

            logger.info(f"成功初始化 {len(self.feishu_agents)} 个飞书Agent服务")
            return True

        except Exception as e:
            logger.exception(f"初始化Agent失败: {e}")
            return False

    async def start_channels(self) -> None:
        for service in self.feishu_agents:
            try:
                logger.info(f"启动飞书Channel: {service.agent_config.name}")
                await service.channel.start()
                logger.info(
                    f"飞书Channel已启动: {service.agent_config.name}"
                )
            except Exception as e:
                logger.exception(
                    f"启动飞书Channel失败 {service.agent_config.name}: {e}"
                )

    async def stop_channels(self) -> None:
        for service in self.feishu_agents:
            try:
                if service.channel:
                    logger.info(f"停止飞书Channel: {service.agent_config.name}")
                    await service.channel.stop()
            except Exception as e:
                logger.exception(
                    f"停止飞书Channel失败 {service.agent_config.name}: {e}"
                )

    async def run(self) -> None:
        logger.info("=" * 60)
        logger.info("飞书消息接收服务启动")
        logger.info("=" * 60)

        if not self.load_config():
            return

        if not await self.initialize_agents():
            return

        self._running = True
        self._loop = asyncio.get_running_loop()

        def signal_handler(signum, frame):
            logger.info(f"收到信号 {signum}, 正在停止服务...")
            self._stop_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            await self.start_channels()

            logger.info("=" * 60)
            logger.info("飞书消息接收服务已就绪")
            logger.info("=" * 60)
            for service in self.feishu_agents:
                logger.info(
                    f"  - Agent: {service.agent_config.name} "
                    f"(App ID: {service.agent_config.im_app_id[:8]}...)"
                )
            logger.info("按 Ctrl+C 停止服务")
            logger.info("=" * 60)

            await self._stop_event.wait()

        except Exception as e:
            logger.exception(f"服务运行错误: {e}")
        finally:
            logger.info("正在停止服务...")
            await self.stop_channels()
            self._running = False
            logger.info("服务已停止")


async def main():
    config_path = os.environ.get("CONFIG_PATH", "config.json")
    service = FeishuChannelService(config_path=config_path)
    await service.run()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("飞书消息接收服务")
    print("=" * 60)
    print("\n功能:")
    print("  1. 读取config.json配置文件")
    print("  2. 检测配置了飞书IM的Agent")
    print("  3. 为每个Agent启动飞书Channel服务")
    print("  4. 监听飞书WebSocket事件")
    print("  5. 接收消息并路由到对应Agent")
    print("  6. 将Agent响应发送回飞书")
    print("\n" + "=" * 60 + "\n")

    asyncio.run(main())
