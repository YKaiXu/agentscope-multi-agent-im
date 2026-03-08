#!/usr/bin/env python3
import json
import subprocess
import os
from pathlib import Path
import streamlit as st

CONFIG_PATH = Path(__file__).parent / "config.json"

ROLE_TEMPLATES = {
    "自定义": "",
    "技术助手": """你是一个专业的技术助手。

【性格特征】
- 热情开朗，乐于助人
- 对技术问题特别感兴趣
- 回答简洁明了，注重实用性

【行为准则】
- 总是先理解用户意图再回答
- 提供代码示例时添加详细注释
- 遇到不确定的问题会诚实承认""",

    "研究员": """你是一个专业的研究员，负责收集和整理信息。

【性格特征】
- 严谨细致，追求准确
- 善于从多个角度分析问题
- 注重信息来源的可靠性

【行为准则】
- 确保信息的准确性和完整性
- 提供数据支持和引用来源
- 区分事实和观点""",

    "分析师": """你是一个专业的分析师，负责分析数据并给出见解。

【性格特征】
- 逻辑清晰，善于推理
- 关注数据背后的趋势
- 提供有深度的分析

【行为准则】
- 基于数据进行分析
- 提供可操作的建议
- 识别潜在风险和机会""",

    "撰写员": """你是一个专业的撰写员，负责生成完整报告。

【性格特征】
- 文笔流畅，结构清晰
- 注重内容的可读性
- 善于总结和归纳

【行为准则】
- 确保报告结构清晰、内容完整
- 使用专业但易懂的语言
- 提供摘要和关键结论""",

    "客服助手": """你是一个友好的客服助手。

【性格特征】
- 热情友好，有耐心
- 善于倾听和理解用户需求
- 积极解决问题

【行为准则】
- 快速响应用户问题
- 提供清晰的解决方案
- 无法解决时引导用户联系人工客服""",

    "创意策划": """你是一个富有创意的策划师。

【性格特征】
- 思维活跃，富有想象力
- 善于发现新的可能性
- 注重创意的可行性

【行为准则】
- 提供多个创意方案
- 考虑实施的可行性
- 结合用户需求和市场趋势"""
}

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"agents": [], "llms": [], "im": {"global_im": {}, "platform": "multi"}, "workflow": "sequential"}

def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

st.set_page_config(page_title="多Agent配置中心", page_icon="🤖", layout="wide")

st.title("🤖 多Agent IM 配置中心")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🤖 Agent配置", "🧠 LLM配置", "🔢 Embedding配置", "💬 IM配置", "🔄 工作流", "⚙️ 服务管理"])

with tab1:
    config = load_config()
    
    st.subheader("Agent列表")
    
    llms_list = config.get("llms", [])
    llm_display_map = {llm["id"]: f"{llm.get('provider', '')} - {llm.get('display_name', llm['id'])}" for llm in llms_list}
    
    if config.get("agents"):
        for i, agent in enumerate(config["agents"]):
            with st.expander(f"{'✅' if agent.get('enabled', True) else '❌'} {agent['name']} - {agent.get('role', '')}"):
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    model_display = llm_display_map.get(agent.get('model', ''), agent.get('model', ''))
                    st.write(f"**模型**: {model_display}")
                    st.write(f"**IM平台**: {agent.get('im_platform', 'global')}")
                    features = []
                    if agent.get('long_term_memory_enabled'): features.append("长期记忆")
                    if agent.get('toolkit_enabled'): features.append("工具集")
                    if agent.get('knowledge_enabled'): features.append("知识库")
                    if agent.get('plan_notebook_enabled'): features.append("计划笔记本")
                    if features:
                        st.write(f"**能力**: {', '.join(features)}")
                with col2:
                    if st.button("✏️ 编辑", key=f"edit_{i}"):
                        st.session_state.edit_index = i
                        st.rerun()
                with col3:
                    if st.button("🗑️ 删除", key=f"del_{i}"):
                        config["agents"].pop(i)
                        save_config(config)
                        st.success("已删除")
                        st.rerun()
    
    st.divider()
    
    edit_idx = st.session_state.get("edit_index", None)
    if edit_idx is not None and edit_idx < len(config.get("agents", [])):
        st.subheader(f"编辑 Agent: {config['agents'][edit_idx]['name']}")
        agent = config["agents"][edit_idx]
    else:
        st.subheader("添加新 Agent")
        agent = {
            "name": "", "role": "", "sys_prompt": "", "model": "",
            "memory_type": "InMemoryMemory", "long_term_memory_enabled": False,
            "long_term_memory_mode": "both", "toolkit_enabled": False,
            "enable_meta_tool": False, "parallel_tool_calls": False,
            "knowledge_enabled": False, "enable_rewrite_query": False,
            "knowledge_documents": [],
            "plan_notebook_enabled": False, "max_iters": 10,
            "print_hint_msg": True, "formatter": "OpenAIChatFormatter",
            "im_platform": "global", "im_app_id": "", "im_app_secret": "",
            "enabled": True
        }
        edit_idx = None
    
    llm_options = [llm["id"] for llm in llms_list]
    
    is_editing = edit_idx is not None
    key_suffix = f"_edit_{edit_idx}" if is_editing else "_add"
    
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("名称", value=agent.get("name", ""), key=f"agent_name{key_suffix}")
        role = st.text_input("角色", value=agent.get("role", ""), key=f"agent_role{key_suffix}")
        current_model_idx = llm_options.index(agent.get("model", "")) if agent.get("model") in llm_options else 0
        model = st.selectbox(
            "模型", 
            llm_options, 
            index=current_model_idx, 
            format_func=lambda x: llm_display_map.get(x, x),
            key=f"agent_model{key_suffix}"
        )
    with col2:
        im_platform = st.selectbox("IM平台", ["global", "feishu", "web"], 
                                   index=["global", "feishu", "web"].index(agent.get("im_platform", "global")), key=f"agent_im{key_suffix}")
        enabled = st.checkbox("启用", value=agent.get("enabled", True), key=f"agent_enabled{key_suffix}")
    
    st.markdown("**角色模板** (选择后自动填充系统提示词)")
    role_template = st.selectbox(
        "选择角色模板",
        list(ROLE_TEMPLATES.keys()),
        index=0,
        key=f"role_template_select{key_suffix}"
    )
    
    default_prompt = agent.get("sys_prompt", "")
    if role_template != "自定义" and ROLE_TEMPLATES[role_template]:
        default_prompt = ROLE_TEMPLATES[role_template]
    
    st.markdown("""
    **系统提示词格式建议：**
    ```
    【角色定义】
    你是一个[角色名称]...

    【性格特征】
    - 特征1
    - 特征2

    【行为准则】
    - 准则1
    - 准则2

    【背景故事】(可选)
    ...
    ```
    """)
    
    sys_prompt = st.text_area(
        "系统提示词 (定义角色、性格、行为准则)", 
        value=default_prompt, 
        height=150, 
        placeholder="【角色定义】\n你是一个...\n\n【性格特征】\n- ...\n\n【行为准则】\n- ...",
        key=f"agent_prompt{key_suffix}"
    )
    
    if im_platform != "global":
        col1, col2 = st.columns(2)
        with col1:
            im_app_id = st.text_input("App ID", value=agent.get("im_app_id", ""), key=f"agent_app_id{key_suffix}")
        with col2:
            im_app_secret = st.text_input("App Secret", value=agent.get("im_app_secret", ""), type="password", key=f"agent_app_secret{key_suffix}")
    else:
        im_app_id = ""
        im_app_secret = ""
    
    with st.expander("🔧 高级配置 (AgentScope参数)", expanded=False):
        st.markdown("### 📝 基础配置")
        col1, col2 = st.columns(2)
        with col1:
            memory_type = st.selectbox("Memory类型", ["InMemoryMemory"], key=f"agent_memory{key_suffix}")
            max_iters = st.number_input("最大迭代次数", min_value=1, max_value=100, value=agent.get("max_iters", 10), key=f"agent_iters{key_suffix}")
            formatter = st.selectbox("Formatter", ["OpenAIChatFormatter", "DashScopeChatFormatter"],
                                     index=["OpenAIChatFormatter", "DashScopeChatFormatter"].index(agent.get("formatter", "OpenAIChatFormatter")), key=f"agent_formatter{key_suffix}")
        with col2:
            print_hint = st.checkbox("打印提示信息", value=agent.get("print_hint_msg", True), key=f"agent_hint{key_suffix}")
        
        st.divider()
        st.markdown("### 🧠 长期记忆配置 (类似soul的记忆功能)")
        ltm_enabled = st.checkbox("启用长期记忆", value=agent.get("long_term_memory_enabled", False), key=f"agent_ltm{key_suffix}")
        
        if ltm_enabled:
            col1, col2 = st.columns(2)
            with col1:
                ltm_mode = st.selectbox(
                    "记忆模式", 
                    ["both", "agent_control", "static_control"], 
                    index=["both", "agent_control", "static_control"].index(agent.get("long_term_memory_mode", "both")),
                    format_func=lambda x: {"both": "双向模式(推荐)", "agent_control": "Agent自主控制", "static_control": "自动控制"}.get(x, x),
                    key=f"agent_ltm_mode{key_suffix}"
                )
            with col2:
                ltm_agent_name = st.text_input("记忆Agent名称", value=agent.get("ltm_agent_name", name or "agent"), 
                                               help="用于区分不同Agent的记忆存储", key=f"agent_ltm_name{key_suffix}")
            
            config_for_emb = load_config()
            embeddings = config_for_emb.get("embeddings", [])
            if embeddings:
                emb_options = [emb.get("id", "") for emb in embeddings]
                emb_display = {emb.get("id", ""): emb.get("display_name", emb.get("id", "")) for emb in embeddings}
                current_emb = agent.get("embedding_model", "")
                if current_emb not in emb_options:
                    current_emb = emb_options[0] if emb_options else ""
                
                embedding_model = st.selectbox(
                    "Embedding模型",
                    emb_options,
                    index=emb_options.index(current_emb) if current_emb in emb_options else 0,
                    format_func=lambda x: emb_display.get(x, x),
                    key=f"agent_emb{key_suffix}"
                )
                st.success(f"✅ 已选择Embedding: {emb_display.get(embedding_model, embedding_model)}")
            else:
                st.warning("⚠️ 请先在「Embedding配置」页面添加Embedding模型")
                embedding_model = ""
            
            st.info("💡 长期记忆使用Mem0LongTermMemory + Qdrant向量存储")
        else:
            ltm_mode = "both"
            ltm_agent_name = name or "agent"
            embedding_model = ""
        
        st.divider()
        st.markdown("### 🔧 工具集配置")
        toolkit_enabled = st.checkbox("启用工具集", value=agent.get("toolkit_enabled", False), key=f"agent_toolkit{key_suffix}")
        
        if toolkit_enabled:
            col1, col2 = st.columns(2)
            with col1:
                meta_tool = st.checkbox("启用Meta Tool (Agent自主管理工具)", value=agent.get("enable_meta_tool", False), key=f"agent_meta{key_suffix}")
            with col2:
                parallel_tool = st.checkbox("并行工具调用", value=agent.get("parallel_tool_calls", False), key=f"agent_parallel{key_suffix}")
        else:
            meta_tool = False
            parallel_tool = False
        
        st.divider()
        st.markdown("### 📚 知识库配置 (RAG)")
        knowledge_enabled = st.checkbox("启用知识库", value=agent.get("knowledge_enabled", False), key=f"agent_knowledge{key_suffix}")
        
        if knowledge_enabled:
            rewrite_query = st.checkbox("启用查询重写", value=agent.get("enable_rewrite_query", False), key=f"agent_rewrite{key_suffix}")
            knowledge_docs = st.text_area(
                "知识库文档路径 (每行一个)", 
                value="\n".join(agent.get("knowledge_documents", [])),
                help="支持PDF、TXT、MD等格式，如: docs/*.pdf",
                key=f"agent_knowledge_docs{key_suffix}"
            )
        else:
            rewrite_query = False
            knowledge_docs = ""
        
        st.divider()
        st.markdown("### 📋 计划笔记本配置")
        notebook_enabled = st.checkbox("启用计划笔记本", value=agent.get("plan_notebook_enabled", False), key=f"agent_notebook{key_suffix}")
        if notebook_enabled:
            st.info("💡 计划笔记本允许Agent制定和管理计划与子任务")
    
    col1, col2 = st.columns(2)
    with col1:
        save_btn_key = f"agent_save_edit_{edit_idx}" if is_editing else "agent_save_add"
        if st.button("💾 保存", type="primary", key=save_btn_key):
            knowledge_doc_list = [d.strip() for d in knowledge_docs.split("\n") if d.strip()] if knowledge_docs else []
            
            new_agent = {
                "name": name, "role": role, "sys_prompt": sys_prompt, "model": model,
                "memory_type": memory_type, 
                "long_term_memory_enabled": ltm_enabled,
                "long_term_memory_mode": ltm_mode,
                "ltm_agent_name": ltm_agent_name if ltm_enabled else "",
                "embedding_model": embedding_model if ltm_enabled else "",
                "toolkit_enabled": toolkit_enabled,
                "enable_meta_tool": meta_tool, "parallel_tool_calls": parallel_tool,
                "knowledge_enabled": knowledge_enabled, 
                "enable_rewrite_query": rewrite_query,
                "knowledge_documents": knowledge_doc_list,
                "plan_notebook_enabled": notebook_enabled, 
                "max_iters": max_iters,
                "print_hint_msg": print_hint, "formatter": formatter,
                "im_platform": im_platform, "im_app_id": im_app_id, "im_app_secret": im_app_secret,
                "enabled": enabled
            }
            if edit_idx is not None:
                config["agents"][edit_idx] = new_agent
                del st.session_state.edit_index
            else:
                config["agents"].append(new_agent)
            save_config(config)
            st.success("保存成功！")
            st.rerun()
    with col2:
        if edit_idx is not None:
            cancel_btn_key = f"agent_cancel_edit_{edit_idx}"
            if st.button("❌ 取消编辑", key=cancel_btn_key):
                del st.session_state.edit_index
                st.rerun()

with tab2:
    config = load_config()
    
    st.subheader("LLM配置")
    
    edit_llm_idx = st.session_state.get("edit_llm_index", None)
    
    if config.get("llms"):
        for i, llm in enumerate(config["llms"]):
            with st.expander(f"{llm.get('display_name', llm.get('id', ''))} - {llm.get('provider', '')}"):
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.write(f"**Model ID**: {llm.get('model_id', '')}")
                    st.write(f"**Base URL**: {llm.get('base_url', '')}")
                with col2:
                    if st.button("✏️ 编辑", key=f"edit_llm_{i}"):
                        st.session_state.edit_llm_index = i
                        st.rerun()
                with col3:
                    if st.button("🗑️ 删除", key=f"del_llm_{i}"):
                        old_id = config["llms"][i].get("id", "")
                        config["llms"].pop(i)
                        for agent in config.get("agents", []):
                            if agent.get("model") == old_id:
                                agent["model"] = ""
                        save_config(config)
                        st.success("已删除")
                        st.rerun()
    
    st.divider()
    
    if edit_llm_idx is not None:
        if edit_llm_idx >= len(config.get("llms", [])):
            edit_llm_idx = None
            if "edit_llm_index" in st.session_state:
                del st.session_state.edit_llm_index
    
    if edit_llm_idx is not None and edit_llm_idx < len(config.get("llms", [])):
        st.subheader(f"编辑 LLM: {config['llms'][edit_llm_idx].get('display_name', '')}")
        llm = config["llms"][edit_llm_idx]
        llm_id_fixed = llm.get("id", "")
    else:
        st.subheader("添加新 LLM")
        llm = {}
        llm_id_fixed = None
        edit_llm_idx = None
    
    llm_key_suffix = f"_edit_{edit_llm_idx}" if edit_llm_idx is not None else "_add"
    
    col1, col2 = st.columns(2)
    with col1:
        if edit_llm_idx is not None:
            st.text_input("ID (唯一标识符)", value=llm.get("id", ""), disabled=True, key=f"llm_id_display{llm_key_suffix}")
            llm_id = llm.get("id", "")
        else:
            llm_id = st.text_input("ID (唯一标识符)", value=f"llm_{int(__import__('time').time())}", key=f"llm_id{llm_key_suffix}")
        provider = st.text_input("提供商", value=llm.get("provider", "智普AI"), key=f"llm_provider{llm_key_suffix}")
        model_id = st.text_input("模型ID", value=llm.get("model_id", "glm-4-flash"), key=f"llm_model_id{llm_key_suffix}")
    with col2:
        display_name = st.text_input("显示名称", value=llm.get("display_name", "GLM-4-Flash"), key=f"llm_display{llm_key_suffix}")
        base_url = st.text_input("Base URL", value=llm.get("base_url", "https://open.bigmodel.cn/api/paas/v4/"), key=f"llm_url{llm_key_suffix}")
        api_key = st.text_input("API Key", type="password", value=llm.get("api_key", ""), key=f"llm_key{llm_key_suffix}")
    
    col1, col2 = st.columns(2)
    with col1:
        btn_key = "llm_save_edit" if edit_llm_idx is not None else "llm_save_add"
        if st.button("💾 保存", type="primary", key=btn_key):
            llm_data = {
                "id": llm_id, 
                "provider": provider, 
                "model_id": model_id,
                "display_name": display_name, 
                "base_url": base_url, 
                "api_key": api_key
            }
            if edit_llm_idx is not None:
                config["llms"][edit_llm_idx] = llm_data
                del st.session_state.edit_llm_index
                st.success("更新成功！")
            else:
                config["llms"].append(llm_data)
                st.success("添加成功！")
            save_config(config)
            st.rerun()
    with col2:
        if edit_llm_idx is not None:
            cancel_llm_btn_key = f"llm_cancel_edit_{edit_llm_idx}"
            if st.button("❌ 取消编辑", key=cancel_llm_btn_key):
                del st.session_state.edit_llm_index
                st.rerun()

with tab3:
    config = load_config()
    
    st.subheader("Embedding模型配置")
    st.info("Embedding模型用于长期记忆和知识库的向量化")
    
    embeddings = config.get("embeddings", [])
    
    if embeddings:
        st.markdown("### 已配置的Embedding模型")
        for i, emb in enumerate(embeddings):
            with st.expander(f"🔢 {emb.get('display_name', emb.get('id', f'Embedding {i+1}'))}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.text_input("ID", value=emb.get("id", ""), disabled=True, key=f"emb_id_display_{i}")
                    st.text_input("提供商", value=emb.get("provider", ""), disabled=True, key=f"emb_provider_display_{i}")
                    st.text_input("模型名称", value=emb.get("model_name", ""), disabled=True, key=f"emb_model_display_{i}")
                with col2:
                    st.text_input("向量维度", value=str(emb.get("dimensions", 1024)), disabled=True, key=f"emb_dim_display_{i}")
                    st.text_input("API Key", value="***" + emb.get("api_key", "")[-4:] if emb.get("api_key") else "", disabled=True, key=f"emb_key_display_{i}")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✏️ 编辑", key=f"emb_edit_{i}"):
                        st.session_state.edit_emb_index = i
                        st.rerun()
                with col2:
                    if st.button("🗑️ 删除", key=f"emb_delete_{i}"):
                        embeddings.pop(i)
                        config["embeddings"] = embeddings
                        save_config(config)
                        st.success("删除成功！")
                        st.rerun()
    
    st.divider()
    
    edit_emb_idx = st.session_state.get("edit_emb_index")
    
    if edit_emb_idx is not None and edit_emb_idx < len(embeddings):
        st.subheader(f"编辑 Embedding: {embeddings[edit_emb_idx].get('display_name', '')}")
        emb = embeddings[edit_emb_idx]
        emb_id_fixed = emb.get("id", "")
    else:
        st.subheader("添加新 Embedding模型")
        emb = {}
        emb_id_fixed = None
        edit_emb_idx = None
    
    emb_key_suffix = f"_edit_{edit_emb_idx}" if edit_emb_idx is not None else "_add"
    
    col1, col2 = st.columns(2)
    with col1:
        if edit_emb_idx is not None:
            st.text_input("ID (唯一标识符)", value=emb.get("id", ""), disabled=True, key=f"emb_id{emb_key_suffix}")
            emb_id = emb.get("id", "")
        else:
            emb_id = st.text_input("ID (唯一标识符)", value=f"emb_{int(__import__('time').time())}", key=f"emb_id{emb_key_suffix}")
        
        provider = st.selectbox(
            "提供商",
            ["OpenAI", "DashScope", "Gemini", "Ollama"],
            index=["OpenAI", "DashScope", "Gemini", "Ollama"].index(emb.get("provider", "DashScope")),
            key=f"emb_provider{emb_key_suffix}"
        )
        
        if provider == "OpenAI":
            default_model = "text-embedding-3-small"
            default_dim = 1536
            default_url = "https://api.openai.com/v1"
        elif provider == "DashScope":
            default_model = "text-embedding-v3"
            default_dim = 1024
            default_url = ""
        elif provider == "Gemini":
            default_model = "text-embedding-004"
            default_dim = 768
            default_url = ""
        else:
            default_model = "nomic-embed-text"
            default_dim = 768
            default_url = "http://localhost:11434"
        
        model_name = st.text_input("模型名称", value=emb.get("model_name", default_model), key=f"emb_model{emb_key_suffix}")
    
    with col2:
        display_name = st.text_input("显示名称", value=emb.get("display_name", f"{provider} Embedding"), key=f"emb_display{emb_key_suffix}")
        dimensions = st.number_input("向量维度", min_value=128, max_value=4096, value=emb.get("dimensions", default_dim), key=f"emb_dim{emb_key_suffix}")
        api_key = st.text_input("API Key", type="password", value=emb.get("api_key", ""), key=f"emb_key{emb_key_suffix}")
        
        if provider in ["OpenAI", "Ollama"]:
            base_url = st.text_input("Base URL", value=emb.get("base_url", default_url), key=f"emb_url{emb_key_suffix}")
        else:
            base_url = emb.get("base_url", "")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 保存 Embedding配置", type="primary", key=f"save_emb{emb_key_suffix}"):
            emb_data = {
                "id": emb_id,
                "provider": provider,
                "model_name": model_name,
                "display_name": display_name,
                "dimensions": dimensions,
                "api_key": api_key,
            }
            if base_url:
                emb_data["base_url"] = base_url
            
            if "embeddings" not in config:
                config["embeddings"] = []
            
            if edit_emb_idx is not None:
                config["embeddings"][edit_emb_idx] = emb_data
            else:
                config["embeddings"].append(emb_data)
            
            save_config(config)
            st.success("保存成功！")
            if "edit_emb_index" in st.session_state:
                del st.session_state.edit_emb_index
            st.rerun()
    
    with col2:
        if edit_emb_idx is not None:
            cancel_emb_btn_key = f"emb_cancel_edit_{edit_emb_idx}"
            if st.button("❌ 取消编辑", key=cancel_emb_btn_key):
                del st.session_state.edit_emb_index
                st.rerun()

with tab4:
    config = load_config()
    
    st.subheader("IM平台全局配置")
    
    platforms = ["feishu", "web"]
    
    for platform in platforms:
        with st.expander(f"📱 {platform.upper()}"):
            platform_config = config.get("im", {}).get("global_im", {}).get(platform, {})
            
            col1, col2 = st.columns(2)
            with col1:
                app_id = st.text_input("App ID", value=platform_config.get("app_id", ""), key=f"im_{platform}_id")
            with col2:
                app_secret = st.text_input("App Secret", type="password", value=platform_config.get("app_secret", ""), key=f"im_{platform}_secret")
            
            enabled = st.checkbox("启用", value=platform_config.get("enabled", False), key=f"im_{platform}_enabled")
            
            if platform == "feishu":
                st.divider()
                st.markdown("**消息路由配置**")
                
                route_mode = st.selectbox(
                    "路由模式",
                    ["single", "keyword", "msghub"],
                    index=["single", "keyword", "msghub"].index(platform_config.get("route_mode", "single")),
                    format_func=lambda x: {"single": "单Agent模式", "keyword": "关键词触发", "msghub": "MsgHub协作"}.get(x, x),
                    key=f"im_{platform}_route_mode"
                )
                
                if route_mode == "keyword":
                    route_keywords = st.text_area(
                        "关键词映射 (每行: 关键词=Agent名称)",
                        value="\n".join([f"{k}={v}" for k, v in platform_config.get("route_keywords", {}).items()]),
                        help="例如：研究=研究员\n分析=分析师",
                        key=f"im_{platform}_keywords"
                    )
                else:
                    route_keywords = ""
                
                if route_mode == "msghub":
                    st.info("💡 MsgHub模式下，所有启用的Agent将参与协作讨论")
                    msghub_announcement = st.text_input(
                        "协作触发消息",
                        value=platform_config.get("msghub_announcement", "请大家协作完成这个任务"),
                        key=f"im_{platform}_msghub_msg"
                    )
                else:
                    msghub_announcement = ""
            
            if platform == "web":
                st.divider()
                st.markdown("**Web聊天配置**")
                web_port = st.number_input(
                    "端口",
                    min_value=8000,
                    max_value=9999,
                    value=platform_config.get("port", 8502),
                    key=f"im_{platform}_port"
                )
                web_mode = st.selectbox(
                    "聊天模式",
                    ["single", "msghub"],
                    index=["single", "msghub"].index(platform_config.get("mode", "single")),
                    format_func=lambda x: {"single": "单Agent对话", "msghub": "多Agent协作"}.get(x, x),
                    key=f"im_{platform}_mode"
                )
            
            if st.button(f"💾 保存 {platform}", key=f"save_im_{platform}"):
                if "im" not in config:
                    config["im"] = {"global_im": {}}
                if "global_im" not in config["im"]:
                    config["im"]["global_im"] = {}
                
                platform_data = {
                    "app_id": app_id, "app_secret": app_secret, "enabled": enabled
                }
                
                if platform == "feishu":
                    platform_data["route_mode"] = route_mode
                    if route_mode == "keyword" and route_keywords:
                        kw_map = {}
                        for line in route_keywords.strip().split("\n"):
                            if "=" in line:
                                k, v = line.split("=", 1)
                                kw_map[k.strip()] = v.strip()
                        platform_data["route_keywords"] = kw_map
                    if route_mode == "msghub":
                        platform_data["msghub_announcement"] = msghub_announcement
                
                if platform == "web":
                    platform_data["port"] = web_port
                    platform_data["mode"] = web_mode
                
                config["im"]["global_im"][platform] = platform_data
                save_config(config)
                st.success("保存成功！")

with tab5:
    config = load_config()
    
    st.subheader("工作流配置")
    
    st.markdown("""
    **AgentScope 工作流模式说明：**
    - **Sequential**: 顺序管道，前一个Agent输出作为后一个输入
    - **Fanout Parallel**: 扇出并行，相同输入分发给多个Agent并行执行
    - **Fanout Sequential**: 扇出顺序，相同输入分发给多个Agent顺序执行
    - **MsgHub**: 群聊模式，多Agent之间消息广播讨论
    """)
    
    workflow_options = ["sequential", "fanout_parallel", "fanout_sequential", "msghub"]
    workflow_labels = {
        "sequential": "顺序管道 (Sequential)",
        "fanout_parallel": "扇出并行 (Fanout Parallel)",
        "fanout_sequential": "扇出顺序 (Fanout Sequential)",
        "msghub": "群聊模式 (MsgHub)"
    }
    
    current_workflow = config.get("workflow", "sequential")
    if current_workflow not in workflow_options:
        current_workflow = "sequential"
    
    workflow = st.radio(
        "选择工作流模式",
        workflow_options,
        index=workflow_options.index(current_workflow),
        format_func=lambda x: workflow_labels.get(x, x)
    )
    
    if workflow == "msghub":
        st.info("💡 群聊模式需要配置announcement消息，用于启动对话")
        announcement = st.text_area(
            "Announcement消息",
            value=config.get("workflow_announcement", "请大家开始协作完成任务"),
            help="进入MsgHub时广播给所有Agent的消息"
        )
    else:
        announcement = None
    
    if st.button("💾 保存工作流配置", type="primary", key="workflow_save_btn"):
        config["workflow"] = workflow
        if announcement:
            config["workflow_announcement"] = announcement
        save_config(config)
        st.success("保存成功！")

with tab6:
    st.subheader("服务管理")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**配置中心服务**")
        if st.button("🔄 重启配置中心", key="svc_restart_config"):
            result = subprocess.run(["sudo", "systemctl", "restart", "multi-agent-config"], capture_output=True, text=True)
            if result.returncode == 0:
                st.success("重启成功！")
            else:
                st.error(f"重启失败: {result.stderr}")
        
        if st.button("📊 查看状态", key="svc_status"):
            result = subprocess.run(["sudo", "systemctl", "status", "multi-agent-config"], capture_output=True, text=True)
            st.code(result.stdout)
    
    with col2:
        st.markdown("**飞书消息服务**")
        if st.button("▶️ 启动飞书服务", key="svc_start_feishu"):
            st.info("请在终端运行: python feishu_channel_service.py")
        
        if st.button("📋 查看日志", key="svc_view_log"):
            log_path = Path(__file__).parent / "streamlit.log"
            if log_path.exists():
                with open(log_path, "r") as f:
                    st.code(f.read()[-5000:])
            else:
                st.warning("日志文件不存在")
