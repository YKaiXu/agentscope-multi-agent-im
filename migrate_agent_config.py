#!/usr/bin/env python3
import json
import os

CONFIG_FILE = '/home/yupeng/.df/multi_agent_im/config.json'

def migrate_agent_config(old_agent):
    """迁移旧的Agent配置到新的AgentScope兼容格式"""
    new_agent = {
        'name': old_agent.get('name', ''),
        'role': old_agent.get('role', ''),
        'sys_prompt': old_agent.get('system_prompt', old_agent.get('sys_prompt', '')),
        'model': old_agent.get('model', ''),
        'memory_type': 'InMemoryMemory',
        'long_term_memory_enabled': False,
        'long_term_memory_mode': 'both',
        'toolkit_enabled': False,
        'enable_meta_tool': False,
        'parallel_tool_calls': False,
        'knowledge_enabled': False,
        'enable_rewrite_query': False,
        'plan_notebook_enabled': False,
        'max_iters': 10,
        'print_hint_msg': True,
        'formatter': 'OpenAIChatFormatter',
        'im_platform': old_agent.get('im_platform', 'global'),
        'im_app_id': old_agent.get('im_app_id', ''),
        'im_app_secret': old_agent.get('im_app_secret', ''),
        'enabled': old_agent.get('enabled', True)
    }
    return new_agent

def migrate_config():
    """迁移整个配置文件"""
    if not os.path.exists(CONFIG_FILE):
        print("配置文件不存在")
        return
    
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    if 'agents' in config and config['agents']:
        print(f"开始迁移 {len(config['agents'])} 个Agent配置...")
        
        for i, agent in enumerate(config['agents']):
            print(f"  迁移Agent {i+1}: {agent.get('name', 'Unknown')}")
            config['agents'][i] = migrate_agent_config(agent)
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        print("✅ 配置迁移完成")
    else:
        print("无需迁移")

if __name__ == '__main__':
    migrate_config()
