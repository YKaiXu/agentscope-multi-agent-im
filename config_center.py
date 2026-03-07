#!/usr/bin/env python3
from flask import Flask, render_template_string, request, jsonify, send_file
import json
import os
import re
import requests
import subprocess
import signal
import psutil
from typing import Dict, List, Any, Tuple
from datetime import datetime
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if 'im' not in config:
                    config['im'] = {}
                if 'global_im' not in config['im']:
                    config['im']['global_im'] = {}
                for platform in ['feishu', 'dingtalk', 'qq', 'discord', 'web']:
                    if platform not in config['im'].get('global_im', {}):
                        if 'global_im' not in config['im']:
                            config['im']['global_im'] = {}
                        config['im']['global_im'][platform] = {"app_id": "", "app_secret": "", "enabled": False}
                if 'agents' not in config:
                    config['agents'] = []
                if 'workflow' not in config:
                    config['workflow'] = 'sequential'
                if 'llms' not in config:
                    config['llms'] = []
                return config
        except json.JSONDecodeError:
            pass
    return {
        "im": {
            "platform": "feishu",
            "app_id": "",
            "app_secret": "",
            "global_im": {
                "feishu": {"app_id": "", "app_secret": "", "enabled": False},
                "dingtalk": {"app_id": "", "app_secret": "", "enabled": False},
                "qq": {"app_id": "", "app_secret": "", "enabled": False},
                "discord": {"app_id": "", "app_secret": "", "enabled": False},
                "web": {"app_id": "", "app_secret": "", "enabled": True}
            }
        },
        "agents": [
            {
                "name": "研究员",
                "role": "收集和整理信息",
                "model": "GLM-4-Flash",
                "system_prompt": "你是一个专业的研究员，负责收集和整理信息。",
                "im_platform": "global",
                "enabled": true
            },
            {
                "name": "分析师",
                "role": "分析数据并给出见解",
                "model": "GLM-4-Flash",
                "system_prompt": "你是一个专业的分析师，负责分析数据并给出见解。",
                "im_platform": "global",
                "enabled": true
            },
            {
                "name": "撰写员",
                "role": "生成完整报告",
                "model": "GLM-4-Flash",
                "system_prompt": "你是一个专业的撰写员，负责生成完整报告。",
                "im_platform": "global",
                "enabled": true
            }
        ],
        "workflow": "sequential",
        "llms": []
    }

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

SERVICES_CONFIG = {
    'config_center': {
        'name': '配置中心',
        'script': 'config_center.py',
        'port': 8080,
        'description': '提供配置管理界面'
    },
    'feishu_channel': {
        'name': '飞书通道服务',
        'script': 'feishu_channel_service.py',
        'port': None,
        'description': '处理飞书消息通道'
    }
}

def get_service_status(service_name: str) -> Dict[str, Any]:
    if service_name not in SERVICES_CONFIG:
        return {'status': 'unknown', 'error': '服务不存在'}
    
    service = SERVICES_CONFIG[service_name]
    script_name = service['script']
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'status']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if cmdline and any(script_name in cmd for cmd in cmdline):
                return {
                    'status': 'running',
                    'pid': proc.info['pid'],
                    'name': service['name'],
                    'script': script_name,
                    'port': service.get('port'),
                    'description': service['description'],
                    'cpu_percent': proc.cpu_percent(interval=0.1),
                    'memory_mb': proc.memory_info().rss / 1024 / 1024
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    return {
        'status': 'stopped',
        'name': service['name'],
        'script': script_name,
        'port': service.get('port'),
        'description': service['description']
    }

def get_all_services_status() -> Dict[str, Dict[str, Any]]:
    statuses = {}
    for service_name in SERVICES_CONFIG:
        statuses[service_name] = get_service_status(service_name)
    return statuses

def start_service(service_name: str) -> Dict[str, Any]:
    if service_name not in SERVICES_CONFIG:
        return {'success': False, 'error': '服务不存在'}
    
    current_status = get_service_status(service_name)
    if current_status['status'] == 'running':
        return {'success': False, 'error': '服务已在运行中', 'status': current_status}
    
    service = SERVICES_CONFIG[service_name]
    script_path = os.path.join(os.path.dirname(__file__), service['script'])
    
    if not os.path.exists(script_path):
        return {'success': False, 'error': f'脚本文件不存在: {script_path}'}
    
    try:
        venv_python = os.path.join(os.path.dirname(__file__), '..', 'agentscope_env', 'bin', 'python')
        if not os.path.exists(venv_python):
            venv_python = 'python3'
        
        subprocess.Popen(
            [venv_python, script_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=os.path.dirname(__file__)
        )
        
        import time
        time.sleep(2)
        
        new_status = get_service_status(service_name)
        if new_status['status'] == 'running':
            return {'success': True, 'message': f'{service["name"]}启动成功', 'status': new_status}
        else:
            return {'success': False, 'error': '服务启动失败，请检查日志', 'status': new_status}
    except Exception as e:
        return {'success': False, 'error': f'启动服务时发生错误: {str(e)}'}

def stop_service(service_name: str) -> Dict[str, Any]:
    if service_name not in SERVICES_CONFIG:
        return {'success': False, 'error': '服务不存在'}
    
    current_status = get_service_status(service_name)
    if current_status['status'] != 'running':
        return {'success': False, 'error': '服务未在运行', 'status': current_status}
    
    try:
        pid = current_status['pid']
        proc = psutil.Process(pid)
        proc.terminate()
        
        import time
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        
        new_status = get_service_status(service_name)
        return {
            'success': True, 
            'message': f'{SERVICES_CONFIG[service_name]["name"]}已停止',
            'status': new_status
        }
    except psutil.NoSuchProcess:
        new_status = get_service_status(service_name)
        return {'success': True, 'message': '服务已停止', 'status': new_status}
    except Exception as e:
        return {'success': False, 'error': f'停止服务时发生错误: {str(e)}'}

def restart_service(service_name: str) -> Dict[str, Any]:
    if service_name not in SERVICES_CONFIG:
        return {'success': False, 'error': '服务不存在'}
    
    current_status = get_service_status(service_name)
    if current_status['status'] == 'running':
        stop_result = stop_service(service_name)
        if not stop_result.get('success'):
            return stop_result
        
        import time
        time.sleep(1)
    
    return start_service(service_name)

def validate_agent(agent: Dict, index: int) -> List[str]:
    errors = []
    if not agent.get('name', '').strip():
        errors.append(f"Agent {index + 1}: 名称不能为空")
    if not agent.get('role', '').strip():
        errors.append(f"Agent {index + 1}: 角色不能为空")
    if not agent.get('model', '').strip():
        errors.append(f"Agent {index + 1}: 模型不能为空")
    if not agent.get('system_prompt', '').strip():
        errors.append(f"Agent {index + 1}: 系统提示词不能为空")
    im_platform = agent.get('im_platform', 'global')
    if im_platform != 'global':
        if not agent.get('im_app_id', '').strip():
            errors.append(f"Agent {index + 1} ({agent.get('name')}): 使用独立IM配置时，App ID不能为空")
        if not agent.get('im_app_secret', '').strip():
            errors.append(f"Agent {index + 1} ({agent.get('name')}): 使用独立IM配置时，App Secret不能为空")
    return errors

def validate_llm(llm: Dict, index: int) -> List[str]:
    errors = []
    if not llm.get('provider', '').strip():
        errors.append(f"LLM {index + 1}: Provider不能为空")
    if not llm.get('base_url', '').strip():
        errors.append(f"LLM {index + 1}: Base URL不能为空")
    else:
        url_pattern = re.compile(
            r'^https?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        if not url_pattern.match(llm.get('base_url', '')):
            errors.append(f"LLM {index + 1}: Base URL格式不正确")
    if not llm.get('api_key', '').strip():
        errors.append(f"LLM {index + 1}: API Key不能为空")
    if not llm.get('model_id', '').strip():
        errors.append(f"LLM {index + 1}: Model ID不能为空")
    if not llm.get('display_name', '').strip():
        errors.append(f"LLM {index + 1}: 显示名称不能为空")
    if not llm.get('id', '').strip():
        errors.append(f"LLM {index + 1}: ID不能为空")
    return errors

def validate_global_im(global_im: Dict) -> List[str]:
    errors = []
    warnings = []
    for platform, config in global_im.items():
        if config.get('enabled', False):
            if not config.get('app_id', '').strip():
                errors.append(f"全局IM配置 - {platform}: 已启用但App ID为空")
            if not config.get('app_secret', '').strip():
                errors.append(f"全局IM配置 - {platform}: 已启用但App Secret为空")
    return errors, warnings

def validate_config(config: Dict) -> Tuple[bool, List[str], List[str]]:
    errors = []
    warnings = []
    if 'agents' in config:
        for i, agent in enumerate(config['agents']):
            errors.extend(validate_agent(agent, i))
    if not config.get('agents'):
        warnings.append("未配置任何Agent，系统将无法正常工作")
    if 'llms' in config:
        for i, llm in enumerate(config['llms']):
            errors.extend(validate_llm(llm, i))
    if config.get('im', {}).get('global_im'):
        im_errors, im_warnings = validate_global_im(config['im']['global_im'])
        errors.extend(im_errors)
        warnings.extend(im_warnings)
    workflow = config.get('workflow', '')
    if workflow not in ['sequential', 'parallel', 'conditional']:
        errors.append(f"工作流模式 '{workflow}' 无效，必须是 sequential、parallel 或 conditional")
    return len(errors) == 0, errors, warnings

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多 Agent + IM 配置中心</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 32px;
            margin-bottom: 10px;
            font-weight: 600;
        }
        
        .header p {
            font-size: 14px;
            opacity: 0.9;
        }
        
        .tabs {
            display: flex;
            background: #f8f9fa;
            border-bottom: 2px solid #e9ecef;
            overflow-x: auto;
        }
        
        .tab {
            flex: 1;
            padding: 18px 20px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
            border-bottom: 3px solid transparent;
            font-weight: 500;
            color: #6c757d;
            min-width: 150px;
            white-space: nowrap;
        }
        
        .tab:hover {
            background: #e9ecef;
            color: #495057;
        }
        
        .tab.active {
            background: white;
            color: #667eea;
            border-bottom-color: #667eea;
        }
        
        .tab-content {
            display: none;
            padding: 30px;
            animation: fadeIn 0.3s;
        }
        
        .tab-content.active {
            display: block;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .section {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 25px;
            border: 1px solid #e9ecef;
        }
        
        .section h2 {
            color: #667eea;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
            font-size: 20px;
            font-weight: 600;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #2c3e50;
            font-size: 14px;
        }
        
        .form-group input,
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.3s;
            background: white;
        }
        
        .form-group input:focus,
        .form-group select:focus,
        .form-group textarea:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .form-group textarea {
            min-height: 120px;
            resize: vertical;
            font-family: 'Courier New', monospace;
        }
        
        .help-text {
            font-size: 12px;
            color: #7f8c8d;
            margin-top: 6px;
            font-style: italic;
        }
        
        .agent-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            transition: all 0.3s;
        }
        
        .agent-card:hover {
            border-color: #667eea;
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.1);
        }
        
        .agent-card h3 {
            color: #667eea;
            margin-bottom: 15px;
            font-size: 18px;
            font-weight: 600;
        }
        
        .agent-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            margin-right: 10px;
            margin-bottom: 10px;
            transition: all 0.3s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.3);
        }
        
        .btn-success {
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
            color: white;
        }
        
        .btn-success:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(17, 153, 142, 0.3);
        }
        
        .btn-danger {
            background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
            color: white;
        }
        
        .btn-danger:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(235, 51, 73, 0.3);
        }
        
        .btn-secondary {
            background: #6c757d;
            color: white;
        }
        
        .btn-secondary:hover {
            background: #5a6268;
            transform: translateY(-2px);
        }
        
        .status {
            padding: 15px 20px;
            border-radius: 8px;
            margin-top: 20px;
            font-weight: 500;
            animation: slideIn 0.3s;
        }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-20px); }
            to { opacity: 1; transform: translateX(0); }
        }
        
        .status-success {
            background: #d4edda;
            color: #155724;
            border-left: 4px solid #28a745;
        }
        
        .status-error {
            background: #f8d7da;
            color: #721c24;
            border-left: 4px solid #dc3545;
        }
        
        .status-info {
            background: #d1ecf1;
            color: #0c5460;
            border-left: 4px solid #17a2b8;
        }
        
        .im-platform-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 15px;
            transition: all 0.3s;
        }
        
        .im-platform-card:hover {
            border-color: #667eea;
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.1);
        }
        
        .im-platform-card h4 {
            color: #667eea;
            margin-bottom: 15px;
            font-size: 16px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .im-platform-card .toggle-switch {
            float: right;
            position: relative;
            width: 50px;
            height: 26px;
        }
        
        .toggle-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: 0.4s;
            border-radius: 26px;
        }
        
        .slider:before {
            position: absolute;
            content: "";
            height: 20px;
            width: 20px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: 0.4s;
            border-radius: 50%;
        }
        
        input:checked + .slider {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        
        input:checked + .slider:before {
            transform: translateX(24px);
        }
        
        .api-section {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        .api-section h3 {
            color: #667eea;
            margin-bottom: 15px;
            font-size: 16px;
            font-weight: 600;
        }
        
        .workflow-info {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        
        .workflow-info h3 {
            margin-bottom: 10px;
            font-size: 18px;
        }
        
        .workflow-info p {
            font-size: 14px;
            opacity: 0.9;
            line-height: 1.6;
        }
        
        .workflow-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 15px;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .workflow-card:hover {
            border-color: #667eea;
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.1);
        }
        
        .workflow-card.selected {
            border-color: #667eea;
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.05) 0%, rgba(118, 75, 162, 0.05) 100%);
        }
        
        .workflow-card h4 {
            color: #667eea;
            margin-bottom: 10px;
            font-size: 16px;
        }
        
        .workflow-card p {
            color: #6c757d;
            font-size: 14px;
            line-height: 1.5;
        }
        
        .service-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 15px;
            transition: all 0.3s;
        }
        
        .service-card:hover {
            border-color: #667eea;
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.1);
        }
        
        .service-card h4 {
            color: #667eea;
            margin-bottom: 15px;
            font-size: 18px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .service-status {
            display: inline-block;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            margin-left: auto;
        }
        
        .service-status.running {
            background: #d4edda;
            color: #155724;
        }
        
        .service-status.stopped {
            background: #f8d7da;
            color: #721c24;
        }
        
        .service-status.unknown {
            background: #e2e3e5;
            color: #383d41;
        }
        
        .service-info {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .service-info-item {
            background: #f8f9fa;
            padding: 10px 15px;
            border-radius: 8px;
            font-size: 13px;
        }
        
        .service-info-item strong {
            color: #667eea;
            display: block;
            margin-bottom: 5px;
        }
        
        .service-actions {
            margin-top: 15px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        .action-buttons {
            background: #f8f9fa;
            padding: 25px;
            border-top: 2px solid #e9ecef;
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }
        
        .password-toggle {
            position: relative;
        }
        
        .password-toggle input {
            padding-right: 45px;
        }
        
        .password-toggle button {
            position: absolute;
            right: 10px;
            top: 50%;
            transform: translateY(-50%);
            background: none;
            border: none;
            cursor: pointer;
            color: #6c757d;
            font-size: 18px;
        }
        
        @media (max-width: 768px) {
            .tabs {
                flex-direction: column;
            }
            
            .tab {
                min-width: auto;
            }
            
            .agent-grid {
                grid-template-columns: 1fr;
            }
            
            .header h1 {
                font-size: 24px;
            }
            
            .action-buttons {
                flex-direction: column;
            }
            
            .btn {
                width: 100%;
                justify-content: center;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 多 Agent + IM 配置中心</h1>
            <p>统一管理您的智能代理、IM平台和API配置</p>
        </div>
        
        <div class="tabs">
            <div class="tab active" onclick="switchTab('im')">📱 IM配置</div>
            <div class="tab" onclick="switchTab('agent')">🤖 Agent配置</div>
            <div class="tab" onclick="switchTab('llm')">🧠 LLM配置</div>
            <div class="tab" onclick="switchTab('workflow')">🔄 工作流配置</div>
            <div class="tab" onclick="switchTab('services')">⚙️ 服务管理</div>
        </div>
        
        <div id="statusMessage"></div>
        
        <!-- IM配置选项卡 -->
        <div id="tab-im" class="tab-content active">
            <div class="section">
                <h2>🌐 全局IM平台配置</h2>
                <p class="help-text" style="margin-bottom: 20px;">
                    配置全局IM平台。<strong style="color: #667eea;">注意：全局配置仅对选择"使用全局配置"的Agent生效</strong>。
                    如果Agent配置了独立的IM平台，将优先使用Agent自己的配置，不受此处的enabled状态影响。
                </p>
                
                <div id="globalImConfig"></div>
            </div>
            
            <div class="section">
                <h2>👤 Agent独立IM配置</h2>
                <p class="help-text" style="margin-bottom: 20px;">
                    为特定Agent配置独立的IM平台。<strong style="color: #667eea;">重要：Agent独立配置优先于全局配置</strong>，
                    当Agent配置了独立IM平台后，将完全使用Agent自己的配置，不受全局IM配置enabled状态的影响。
                    只有当Agent选择"使用全局配置"时，才会使用全局IM配置并受其enabled状态控制。
                </p>
                <div id="agentImConfig"></div>
            </div>
        </div>
        
        <!-- Agent配置选项卡 -->
        <div id="tab-agent" class="tab-content">
            <div class="section">
                <h2>🤖 Agent管理</h2>
                <p class="help-text" style="margin-bottom: 20px;">
                    配置您的智能代理。每个Agent可以选择使用全局IM配置或独立的IM平台配置。
                    <strong style="color: #667eea;">Agent独立IM配置优先于全局配置</strong>，选择独立配置后将不受全局enabled状态影响。
                </p>
                <div id="llmStatusBanner"></div>
                <div id="agentsList"></div>
                <button class="btn btn-primary" onclick="addAgent()">➕ 添加Agent</button>
            </div>
        </div>
        
        <!-- LLM配置选项卡 -->
        <div id="tab-llm" class="tab-content">
            <div class="section">
                <h2>🧠 LLM模型配置</h2>
                <p class="help-text" style="margin-bottom: 20px;">
                    配置和管理您的LLM模型。支持同一Provider配置多个Model，每个模型可以有独立的API Key和配置。
                    <strong style="color: #667eea;">配置LLM是使用Agent功能的前提条件</strong>，请确保至少配置一个LLM。
                </p>
                
                <div id="llmList"></div>
                <button class="btn btn-primary" onclick="showLLMForm()">➕ 添加LLM</button>
            </div>
        </div>
        
        <!-- LLM添加/编辑表单模态框 -->
        <div id="llmModal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000;">
            <div style="position: relative; max-width: 600px; margin: 50px auto; background: white; border-radius: 15px; padding: 30px; max-height: 90vh; overflow-y: auto;">
                <h2 id="llmModalTitle" style="color: #667eea; margin-bottom: 25px;">添加LLM配置</h2>
                
                <div class="form-group">
                    <label>Provider名称 *</label>
                    <select id="llmProvider" onchange="updateProviderDefaults()">
                        <option value="">选择Provider</option>
                        <option value="智普AI">智普AI (ZhipuAI)</option>
                        <option value="硅基流动">硅基流动 (SiliconFlow)</option>
                        <option value="阿里云">阿里云 (DashScope)</option>
                        <option value="OpenAI">OpenAI</option>
                        <option value="自定义">自定义</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label>Base URL *</label>
                    <input type="text" id="llmBaseUrl" placeholder="API端点URL">
                </div>
                
                <div class="form-group">
                    <label>API Key *</label>
                    <div class="password-toggle">
                        <input type="password" id="llmApiKey" placeholder="输入API Key">
                        <button type="button" onclick="togglePassword('llmApiKey')">👁️</button>
                    </div>
                </div>
                
                <div class="form-group">
                    <label>Model ID *</label>
                    <input type="text" id="llmModelId" placeholder="例如: glm-4-flash, gpt-4">
                </div>
                
                <div class="form-group">
                    <label>显示名称 *</label>
                    <input type="text" id="llmDisplayName" placeholder="例如: GLM-4-Flash, GPT-4">
                </div>
                
                <input type="hidden" id="llmEditId" value="">
                
                <div style="margin-top: 25px; display: flex; gap: 10px;">
                    <button class="btn btn-success" onclick="saveLLM()">💾 保存</button>
                    <button class="btn btn-primary" onclick="testLLMConnection()">🧪 测试连接</button>
                    <button class="btn btn-secondary" onclick="closeLLMForm()">取消</button>
                </div>
            </div>
        </div>
        
        <!-- 工作流配置选项卡 -->
        <div id="tab-workflow" class="tab-content">
            <div class="workflow-info">
                <h3>📋 工作流模式说明</h3>
                <p>选择适合您任务的工作流模式。不同的模式会影响Agent之间的协作方式和执行顺序。</p>
            </div>
            
            <div class="section">
                <h2>🔄 工作流模式选择</h2>
                
                <div class="workflow-card" onclick="selectWorkflow('sequential')" id="workflow-sequential">
                    <h4>📋 顺序执行模式</h4>
                    <p>Agent按照配置顺序依次执行，前一个Agent的输出作为下一个Agent的输入。适合需要逐步处理的任务，如：研究→分析→撰写报告。</p>
                </div>
                
                <div class="workflow-card" onclick="selectWorkflow('parallel')" id="workflow-parallel">
                    <h4>⚡ 并行执行模式</h4>
                    <p>所有Agent同时执行，各自独立处理输入。适合需要多角度同时分析的任务，如：多个Agent同时分析同一份数据的不同维度。</p>
                </div>
                
                <div class="workflow-card" onclick="selectWorkflow('conditional')" id="workflow-conditional">
                    <h4>🔀 条件执行模式</h4>
                    <p>根据条件动态选择执行的Agent。适合需要根据输入内容决定处理流程的场景，如：根据问题类型选择不同的专家Agent。</p>
                </div>
            </div>
        </div>
        
        <!-- 服务管理选项卡 -->
        <div id="tab-services" class="tab-content">
            <div class="workflow-info">
                <h3>⚙️ 服务管理</h3>
                <p>管理和监控系统的各个服务组件。可以查看服务状态、启动、停止或重启服务。</p>
            </div>
            
            <div class="section">
                <h2>📊 服务状态监控</h2>
                <div id="servicesList"></div>
                <button class="btn btn-primary" onclick="refreshServicesStatus()" style="margin-top: 15px;">🔄 刷新状态</button>
            </div>
        </div>
        
        <!-- 操作按钮 -->
        <div class="action-buttons">
            <button class="btn btn-success" onclick="saveConfiguration()">💾 保存配置</button>
            <button class="btn btn-primary" onclick="testConfiguration()">🧪 测试配置</button>
            <button class="btn btn-secondary" onclick="exportConfiguration()">📤 导出配置</button>
            <button class="btn btn-secondary" onclick="importConfiguration()">📥 导入配置</button>
            <button class="btn btn-danger" onclick="resetConfiguration()">🔄 重置配置</button>
        </div>
    </div>
    
    <input type="file" id="importFile" accept=".json" style="display: none" onchange="handleImport(event)">

    <script>
        let agents = [];
        let config = {};
        let currentWorkflow = 'sequential';
        let llms = [];
        
        const imPlatforms = {
            feishu: { name: '飞书', icon: '📱' },
            dingtalk: { name: '钉钉', icon: '💬' },
            qq: { name: 'QQ', icon: '🐧' },
            discord: { name: 'Discord', icon: '🎮' },
            web: { name: 'Web界面', icon: '🌐' }
        };
        
        const providerDefaults = {
            '智普AI': 'https://open.bigmodel.cn/api/paas/v4/',
            '硅基流动': 'https://api.siliconflow.cn/v1/',
            '阿里云': 'https://dashscope.aliyuncs.com/api/v1/',
            'OpenAI': 'https://api.openai.com/v1/',
            '自定义': ''
        };
        
        function getModels() {
            if (llms && llms.length > 0) {
                return llms.map(llm => ({
                    value: llm.id,
                    name: `[${llm.provider}] ${llm.display_name}`,
                    group: llm.provider
                }));
            }
            return [];
        }
        
        function updateLLMStatusBanner() {
            const banner = document.getElementById('llmStatusBanner');
            if (!banner) return;
            
            if (!llms || llms.length === 0) {
                banner.innerHTML = `
                    <div style="padding: 15px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 5px; margin-bottom: 15px; color: #721c24;">
                        <strong>⚠️ 当前未配置任何LLM</strong><br>
                        <small>请先在"LLM配置"标签页添加LLM配置，然后再配置Agent。</small>
                    </div>
                `;
            } else {
                banner.innerHTML = `
                    <div style="padding: 15px; background: #d4edda; border: 1px solid #c3e6cb; border-radius: 5px; margin-bottom: 15px; color: #155724;">
                        <strong>✅ 已配置 ${llms.length} 个LLM</strong>
                    </div>
                `;
            }
        }
        
        function switchTab(tabName) {
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            
            const tabElement = document.querySelector(`.tab[onclick*="switchTab('${tabName}')"]`);
            if (tabElement) {
                tabElement.classList.add('active');
            }
            
            const tabContent = document.getElementById('tab-' + tabName);
            if (tabContent) {
                tabContent.classList.add('active');
            }
            
            if (tabName === 'services') {
                loadServicesStatus();
            } else if (tabName === 'agent') {
                updateLLMStatusBanner();
            }
        }
        
        function togglePassword(inputId) {
            const input = document.getElementById(inputId);
            const button = input.nextElementSibling;
            
            if (input.type === 'password') {
                input.type = 'text';
                button.textContent = '🙈';
            } else {
                input.type = 'password';
                button.textContent = '👁️';
            }
        }
        
        function selectWorkflow(mode) {
            currentWorkflow = mode;
            document.querySelectorAll('.workflow-card').forEach(card => {
                card.classList.remove('selected');
            });
            document.getElementById('workflow-' + mode).classList.add('selected');
        }
        
        async function loadConfiguration() {
            try {
                const response = await fetch('/api/config');
                config = await response.json();
                
                if (config.im && config.im.global_im) {
                    renderGlobalImConfig(config.im.global_im);
                }
                
                if (config.llms) {
                    llms = config.llms;
                    renderLLMs();
                }
                
                if (config.agents) {
                    agents = config.agents;
                    renderAgents();
                    renderAgentImConfig();
                }
                
                if (config.workflow) {
                    currentWorkflow = config.workflow;
                    selectWorkflow(config.workflow);
                }
                
                showStatus('✅ 配置加载成功！', 'success');
            } catch (error) {
                showStatus('❌ 加载配置失败: ' + error.message, 'error');
            }
        }
        
        function renderGlobalImConfig(globalIm) {
            const container = document.getElementById('globalImConfig');
            container.innerHTML = '';
            
            Object.keys(imPlatforms).forEach(platformKey => {
                const platform = imPlatforms[platformKey];
                const config = globalIm[platformKey] || { app_id: '', app_secret: '', enabled: false };
                
                container.innerHTML += `
                    <div class="im-platform-card">
                        <h4>
                            ${platform.icon} ${platform.name}
                            <label class="toggle-switch">
                                <input type="checkbox" 
                                       id="im-${platformKey}-enabled" 
                                       ${config.enabled ? 'checked' : ''}
                                       onchange="updateGlobalIm('${platformKey}', 'enabled', this.checked)">
                                <span class="slider"></span>
                            </label>
                        </h4>
                        <div class="agent-grid">
                            <div class="form-group">
                                <label>App ID</label>
                                <input type="text" 
                                       id="im-${platformKey}-appid" 
                                       value="${config.app_id || ''}"
                                       placeholder="输入App ID"
                                       onchange="updateGlobalIm('${platformKey}', 'app_id', this.value)">
                            </div>
                            <div class="form-group">
                                <label>App Secret</label>
                                <div class="password-toggle">
                                    <input type="password" 
                                           id="im-${platformKey}-secret" 
                                           value="${config.app_secret || ''}"
                                           placeholder="输入App Secret"
                                           onchange="updateGlobalIm('${platformKey}', 'app_secret', this.value)">
                                    <button type="button" onclick="togglePassword('im-${platformKey}-secret')">👁️</button>
                                </div>
                            </div>
                        </div>
                        <div style="margin-top: 15px;">
                            <button class="btn btn-primary" onclick="testImConnection('${platformKey}')">🧪 测试连接</button>
                        </div>
                    </div>
                `;
            });
        }
        
        async function testImConnection(platformKey) {
            const appId = document.getElementById(`im-${platformKey}-appid`).value;
            const appSecret = document.getElementById(`im-${platformKey}-secret`).value;
            
            if (!appId || !appSecret) {
                showStatus('❌ 请先填写App ID和App Secret', 'error');
                return;
            }
            
            showStatus('⏳ 正在测试连接...', 'info');
            
            try {
                const response = await fetch('/api/test-im', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        platform: platformKey,
                        app_id: appId,
                        app_secret: appSecret
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    let message = '✅ ' + result.message;
                    if (result.warning) {
                        message += '<br><small style="color: #856404;">⚠️ ' + result.warning + '</small>';
                    }
                    showStatus(message, 'success');
                } else {
                    showStatus('❌ ' + result.error, 'error');
                }
            } catch (error) {
                showStatus('❌ 测试失败: ' + error.message, 'error');
            }
        }
        
        function updateGlobalIm(platform, field, value) {
            if (!config.im) config.im = {};
            if (!config.im.global_im) config.im.global_im = {};
            if (!config.im.global_im[platform]) config.im.global_im[platform] = {};
            config.im.global_im[platform][field] = value;
        }
        
        function renderAgentImConfig() {
            const container = document.getElementById('agentImConfig');
            container.innerHTML = '';
            
            if (agents.length === 0) {
                container.innerHTML = '<p class="help-text">请先在Agent配置选项卡中添加Agent</p>';
                return;
            }
            
            agents.forEach((agent, index) => {
                const imPlatform = agent.im_platform || 'global';
                let imConfigHtml = '';
                let statusInfo = '';
                
                if (imPlatform !== 'global') {
                    const platform = imPlatforms[imPlatform];
                    statusInfo = `
                        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 12px 15px; border-radius: 8px; margin-top: 15px; font-size: 13px;">
                            <strong>✅ 独立配置已启用</strong><br>
                            此Agent将使用独立的${platform.icon} ${platform.name}配置，不受全局IM配置enabled状态的影响。
                        </div>
                    `;
                    imConfigHtml = `
                        <div class="agent-grid" style="margin-top: 15px;">
                            <div class="form-group">
                                <label>App ID</label>
                                <input type="text" 
                                       id="agent-${index}-im-appid"
                                       value="${agent.im_app_id || ''}"
                                       placeholder="输入App ID"
                                       onchange="updateAgentIm(${index}, 'im_app_id', this.value)">
                            </div>
                            <div class="form-group">
                                <label>App Secret</label>
                                <div class="password-toggle">
                                    <input type="password" 
                                           id="agent-${index}-im-secret"
                                           value="${agent.im_app_secret || ''}"
                                           placeholder="输入App Secret"
                                           onchange="updateAgentIm(${index}, 'im_app_secret', this.value)">
                                    <button type="button" onclick="togglePassword('agent-${index}-im-secret')">👁️</button>
                                </div>
                            </div>
                        </div>
                    `;
                } else {
                    statusInfo = `
                        <div style="background: #f8f9fa; color: #6c757d; padding: 12px 15px; border-radius: 8px; margin-top: 15px; font-size: 13px; border-left: 4px solid #6c757d;">
                            <strong>ℹ️ 使用全局配置</strong><br>
                            此Agent将使用全局IM配置，受全局enabled状态控制。请在上方"全局IM平台配置"中启用并配置相应的IM平台。
                        </div>
                    `;
                }
                
                container.innerHTML += `
                    <div class="im-platform-card">
                        <h4>🤖 ${agent.name}</h4>
                        <div class="form-group">
                            <label>IM平台选择</label>
                            <select onchange="updateAgentIm(${index}, 'im_platform', this.value)">
                                <option value="global" ${imPlatform === 'global' ? 'selected' : ''}>使用全局配置</option>
                                ${Object.keys(imPlatforms).map(key => 
                                    `<option value="${key}" ${imPlatform === key ? 'selected' : ''}>${imPlatforms[key].icon} ${imPlatforms[key].name}</option>`
                                ).join('')}
                            </select>
                        </div>
                        ${statusInfo}
                        ${imConfigHtml}
                    </div>
                `;
            });
        }
        
        function updateAgentIm(index, field, value) {
            agents[index][field] = value;
            if (field === 'im_platform') {
                renderAgentImConfig();
            }
        }
        
        function renderAgents() {
            const container = document.getElementById('agentsList');
            container.innerHTML = '';
            
            updateLLMStatusBanner();
            
            if (!llms || llms.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #6c757d;">
                        <p style="font-size: 16px; margin-bottom: 10px;">请先配置LLM后再添加Agent</p>
                        <button class="btn btn-primary" onclick="switchTab('llm')">前往配置LLM</button>
                    </div>
                `;
                return;
            }
            
            const models = getModels();
            
            agents.forEach((agent, index) => {
                const modelOptions = models.map(model => 
                    `<option value="${model.value}" ${agent.model === model.value ? 'selected' : ''}>${model.name}</option>`
                ).join('');
                
                const isEnabled = agent.enabled !== false;
                
                container.innerHTML += `
                    <div class="agent-card">
                        <h3>
                            🤖 Agent ${index + 1}: ${agent.name}
                            <label class="toggle-switch" style="float: right;">
                                <input type="checkbox" 
                                       ${isEnabled ? 'checked' : ''}
                                       onchange="updateAgent(${index}, 'enabled', this.checked)">
                                <span class="slider"></span>
                            </label>
                        </h3>
                        <div class="agent-grid">
                            <div class="form-group">
                                <label>名称</label>
                                <input type="text" 
                                       value="${agent.name}" 
                                       onchange="updateAgent(${index}, 'name', this.value)"
                                       placeholder="Agent名称">
                            </div>
                            <div class="form-group">
                                <label>角色</label>
                                <input type="text" 
                                       value="${agent.role}" 
                                       onchange="updateAgent(${index}, 'role', this.value)"
                                       placeholder="Agent角色描述">
                            </div>
                            <div class="form-group">
                                <label>模型</label>
                                <select onchange="updateAgent(${index}, 'model', this.value)">
                                    ${modelOptions}
                                </select>
                            </div>
                            <div class="form-group">
                                <label>专属IM平台</label>
                                <select onchange="updateAgent(${index}, 'im_platform', this.value)">
                                    <option value="global" ${(agent.im_platform || 'global') === 'global' ? 'selected' : ''}>使用全局配置</option>
                                    ${Object.keys(imPlatforms).map(key => 
                                        `<option value="${key}" ${agent.im_platform === key ? 'selected' : ''}>${imPlatforms[key].icon} ${imPlatforms[key].name}</option>`
                                    ).join('')}
                                </select>
                            </div>
                        </div>
                        <div class="form-group">
                            <label>系统提示词</label>
                            <textarea onchange="updateAgent(${index}, 'system_prompt', this.value)"
                                      placeholder="定义Agent的行为和职责...">${agent.system_prompt || ''}</textarea>
                        </div>
                        <button class="btn btn-danger" onclick="removeAgent(${index})">🗑️ 删除Agent</button>
                    </div>
                `;
            });
        }
        
        function addAgent() {
            if (!llms || llms.length === 0) {
                showStatus('❌ 请先配置LLM，然后再添加Agent', 'error');
                return;
            }
            
            const models = getModels();
            agents.push({
                name: `Agent ${agents.length + 1}`,
                role: "执行任务",
                model: models[0].value,
                system_prompt: "你是一个专业的助手，负责执行分配的任务。",
                im_platform: "global",
                enabled: true
            });
            renderAgents();
            renderAgentImConfig();
            showStatus('✅ 已添加新Agent', 'success');
        }
        
        function updateAgent(index, field, value) {
            agents[index][field] = value;
            if (field === 'name') {
                renderAgentImConfig();
            }
        }
        
        async function removeAgent(index) {
            if (confirm(`确定要删除Agent "${agents[index].name}" 吗？`)) {
                try {
                    const response = await fetch(`/api/agent/${index}`, {
                        method: 'DELETE'
                    });
                    const result = await response.json();
                    if (result.success) {
                        agents.splice(index, 1);
                        renderAgents();
                        renderAgentImConfig();
                        showStatus('✅ Agent已删除', 'success');
                    } else {
                        showStatus('❌ 删除失败: ' + result.error, 'error');
                    }
                } catch (error) {
                    showStatus('❌ 删除失败: ' + error.message, 'error');
                }
            }
        }
        
        function renderLLMs() {
            const container = document.getElementById('llmList');
            container.innerHTML = '';
            
            if (!llms || llms.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #6c757d;">
                        <p style="font-size: 16px; margin-bottom: 10px;">暂无LLM配置</p>
                        <p style="font-size: 14px;">点击"添加LLM"按钮开始配置您的第一个模型</p>
                    </div>
                `;
                return;
            }
            
            llms.forEach((llm, index) => {
                container.innerHTML += `
                    <div class="agent-card">
                        <h3>🧠 ${llm.display_name}</h3>
                        <div class="agent-grid">
                            <div class="form-group">
                                <label>Provider</label>
                                <input type="text" value="${llm.provider}" readonly style="background: #f8f9fa;">
                            </div>
                            <div class="form-group">
                                <label>Model ID</label>
                                <input type="text" value="${llm.model_id}" readonly style="background: #f8f9fa;">
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Base URL</label>
                            <input type="text" value="${llm.base_url}" readonly style="background: #f8f9fa;">
                        </div>
                        <div style="margin-top: 15px;">
                            <button class="btn btn-primary" onclick="editLLM('${llm.id}')">✏️ 编辑</button>
                            <button class="btn btn-danger" onclick="deleteLLM('${llm.id}')">🗑️ 删除</button>
                        </div>
                    </div>
                `;
            });
        }
        
        function showLLMForm(editId = null) {
            document.getElementById('llmModal').style.display = 'block';
            document.getElementById('llmModalTitle').textContent = editId ? '编辑LLM配置' : '添加LLM配置';
            
            if (editId) {
                const llm = llms.find(l => l.id === editId);
                if (llm) {
                    document.getElementById('llmProvider').value = llm.provider;
                    document.getElementById('llmBaseUrl').value = llm.base_url;
                    document.getElementById('llmApiKey').value = llm.api_key;
                    document.getElementById('llmModelId').value = llm.model_id;
                    document.getElementById('llmDisplayName').value = llm.display_name;
                    document.getElementById('llmEditId').value = editId;
                }
            } else {
                document.getElementById('llmProvider').value = '';
                document.getElementById('llmBaseUrl').value = '';
                document.getElementById('llmApiKey').value = '';
                document.getElementById('llmModelId').value = '';
                document.getElementById('llmDisplayName').value = '';
                document.getElementById('llmEditId').value = '';
            }
        }
        
        function closeLLMForm() {
            document.getElementById('llmModal').style.display = 'none';
        }
        
        function updateProviderDefaults() {
            const provider = document.getElementById('llmProvider').value;
            if (provider && providerDefaults[provider]) {
                document.getElementById('llmBaseUrl').value = providerDefaults[provider];
            }
        }
        
        async function saveLLM() {
            const provider = document.getElementById('llmProvider').value;
            const baseUrl = document.getElementById('llmBaseUrl').value;
            const apiKey = document.getElementById('llmApiKey').value;
            const modelId = document.getElementById('llmModelId').value;
            const displayName = document.getElementById('llmDisplayName').value;
            const editId = document.getElementById('llmEditId').value;
            
            if (!provider || !baseUrl || !apiKey || !modelId || !displayName) {
                showStatus('❌ 请填写所有必填字段', 'error');
                return;
            }
            
            if (editId) {
                const index = llms.findIndex(l => l.id === editId);
                if (index !== -1) {
                    llms[index] = {
                        id: editId,
                        provider: provider,
                        base_url: baseUrl,
                        api_key: apiKey,
                        model_id: modelId,
                        display_name: displayName
                    };
                }
            } else {
                const newLLM = {
                    id: 'llm_' + Date.now(),
                    provider: provider,
                    base_url: baseUrl,
                    api_key: apiKey,
                    model_id: modelId,
                    display_name: displayName
                };
                llms.push(newLLM);
            }
            
            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        im: config.im,
                        agents: agents,
                        workflow: currentWorkflow,
                        llms: llms
                    })
                });
                const result = await response.json();
                if (result.success) {
                    showStatus(editId ? '✅ LLM配置已更新并保存' : '✅ LLM配置已添加并保存', 'success');
                    renderLLMs();
                    closeLLMForm();
                } else {
                    showStatus('❌ 保存失败: ' + result.error, 'error');
                }
            } catch (error) {
                showStatus('❌ 保存失败: ' + error.message, 'error');
            }
        }
        
        function editLLM(id) {
            showLLMForm(id);
        }
        
        async function deleteLLM(id) {
            const llm = llms.find(l => l.id === id);
            if (confirm(`确定要删除LLM "${llm.display_name}" 吗？`)) {
                try {
                    const response = await fetch(`/api/llm/${id}`, {
                        method: 'DELETE'
                    });
                    const result = await response.json();
                    if (result.success) {
                        llms = llms.filter(l => l.id !== id);
                        renderLLMs();
                        showStatus('✅ LLM已删除', 'success');
                    } else {
                        showStatus('❌ 删除失败: ' + result.error, 'error');
                    }
                } catch (error) {
                    showStatus('❌ 删除失败: ' + error.message, 'error');
                }
            }
        }
        
        async function testLLMConnection() {
            const provider = document.getElementById('llmProvider').value;
            const baseUrl = document.getElementById('llmBaseUrl').value;
            const apiKey = document.getElementById('llmApiKey').value;
            const modelId = document.getElementById('llmModelId').value;
            
            if (!provider || !baseUrl || !apiKey || !modelId) {
                showStatus('❌ 请先填写Provider、Base URL、API Key和Model ID', 'error');
                return;
            }
            
            showStatus('⏳ 正在测试连接...', 'info');
            
            try {
                const response = await fetch('/api/test-llm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider: provider,
                        base_url: baseUrl,
                        api_key: apiKey,
                        model_id: modelId
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    let message = '✅ ' + result.message;
                    if (result.warning) {
                        message += '<br><small style="color: #856404;">⚠️ ' + result.warning + '</small>';
                    }
                    showStatus(message, 'success');
                } else {
                    showStatus('❌ ' + result.error, 'error');
                }
            } catch (error) {
                showStatus('❌ 测试失败: ' + error.message, 'error');
            }
        }
        
        async function saveConfiguration() {
            if (agents && agents.length > 0) {
                for (let i = 0; i < agents.length; i++) {
                    const agent = agents[i];
                    if (agent.model && !llms.find(l => l.id === agent.model)) {
                        showStatus(`❌ Agent "${agent.name}" 引用的LLM配置不存在，请先配置LLM`, 'error');
                        return;
                    }
                }
            }
            
            const configToSave = {
                im: {
                    platform: 'multi',
                    global_im: config.im?.global_im || {}
                },
                agents: agents,
                workflow: currentWorkflow,
                llms: llms
            };
            
            try {
                showStatus('⏳ 正在保存配置...', 'info');
                
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(configToSave)
                });
                
                const result = await response.json();
                if (result.success) {
                    let message = '✅ ' + result.message;
                    if (result.warnings && result.warnings.length > 0) {
                        message += '<br><small style="color: #856404;">⚠️ 警告: ' + result.warnings.join('; ') + '</small>';
                    }
                    showStatus(message, 'success');
                } else {
                    let errorMsg = result.error;
                    if (result.errors && result.errors.length > 0) {
                        errorMsg = result.errors.join('<br>');
                    }
                    showStatus('❌ 保存失败:<br>' + errorMsg, 'error');
                }
            } catch (error) {
                showStatus('❌ 保存失败: ' + error.message, 'error');
            }
        }
        
        async function testConfiguration() {
            showStatus('⏳ 正在测试配置...', 'info');
            
            try {
                const response = await fetch('/api/test');
                const result = await response.json();
                
                if (result.success) {
                    let message = '✅ ' + result.message;
                    if (result.details) {
                        message += '<br><small>';
                        message += `Agent数量: ${result.details.agents.count} | `;
                        message += `LLM数量: ${result.details.llms.count} | `;
                        message += `工作流: ${result.details.workflow.mode}`;
                        if (result.details.im.platforms.length > 0) {
                            message += ` | 已启用IM: ${result.details.im.platforms.join(', ')}`;
                        }
                        message += '</small>';
                    }
                    if (result.warnings && result.warnings.length > 0) {
                        message += '<br><small style="color: #856404;">⚠️ ' + result.warnings.join('; ') + '</small>';
                    }
                    showStatus(message, 'success');
                } else {
                    let errorMsg = result.error;
                    if (result.errors && result.errors.length > 0) {
                        errorMsg = result.errors.join('<br>');
                    }
                    showStatus('❌ 配置测试失败:<br>' + errorMsg, 'error');
                }
            } catch (error) {
                showStatus('❌ 测试失败: ' + error.message, 'error');
            }
        }
        
        async function exportConfiguration() {
            showStatus('⏳ 正在导出配置...', 'info');
            
            try {
                const response = await fetch('/api/export');
                
                if (!response.ok) {
                    const error = await response.json();
                    showStatus('❌ 导出失败: ' + (error.error || '未知错误'), 'error');
                    return;
                }
                
                const blob = await response.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = response.headers.get('content-disposition')?.split('filename=')[1]?.replace(/"/g, '') || 'config_backup.json';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                
                showStatus('✅ 配置已成功导出', 'success');
            } catch (error) {
                showStatus('❌ 导出失败: ' + error.message, 'error');
            }
        }
        
        function importConfiguration() {
            document.getElementById('importFile').click();
        }
        
        async function handleImport(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            showStatus('⏳ 正在导入配置...', 'info');
            
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const response = await fetch('/api/import', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.success) {
                    if (result.config.im && result.config.im.global_im) {
                        config.im = result.config.im;
                        renderGlobalImConfig(config.im.global_im);
                    }
                    
                    if (result.config.agents) {
                        agents = result.config.agents;
                        renderAgents();
                        renderAgentImConfig();
                    }
                    
                    if (result.config.workflow) {
                        currentWorkflow = result.config.workflow;
                        selectWorkflow(currentWorkflow);
                    }
                    
                    if (result.config.llms) {
                        llms = result.config.llms;
                        renderLLMs();
                    }
                    
                    let message = '✅ ' + result.message;
                    if (result.warnings && result.warnings.length > 0) {
                        message += '<br><small style="color: #856404;">⚠️ ' + result.warnings.join('; ') + '</small>';
                    }
                    showStatus(message, 'success');
                } else {
                    let errorMsg = result.error;
                    if (result.errors && result.errors.length > 0) {
                        errorMsg = result.errors.join('<br>');
                    }
                    showStatus('❌ 导入失败:<br>' + errorMsg, 'error');
                }
            } catch (error) {
                showStatus('❌ 导入失败: ' + error.message, 'error');
            }
            
            event.target.value = '';
        }
        
        function resetConfiguration() {
            if (confirm('确定要重置所有配置吗？这将恢复到上次保存的状态。')) {
                loadConfiguration();
            }
        }
        
        function showStatus(message, type) {
            const statusDiv = document.getElementById('statusMessage');
            statusDiv.innerHTML = `<div class="status status-${type}">${message}</div>`;
            
            if (type === 'success' || type === 'info') {
                setTimeout(() => {
                    statusDiv.innerHTML = '';
                }, 5000);
            }
        }
        
        async function loadServicesStatus() {
            try {
                const response = await fetch('/api/services/status');
                const result = await response.json();
                
                if (result.success) {
                    renderServices(result.services);
                } else {
                    showStatus('❌ 加载服务状态失败: ' + result.error, 'error');
                }
            } catch (error) {
                showStatus('❌ 加载服务状态失败: ' + error.message, 'error');
            }
        }
        
        function renderServices(services) {
            const container = document.getElementById('servicesList');
            container.innerHTML = '';
            
            const statusText = {
                'running': '运行中',
                'stopped': '已停止',
                'unknown': '未知'
            };
            
            const statusIcon = {
                'running': '✅',
                'stopped': '⏹️',
                'unknown': '❓'
            };
            
            Object.keys(services).forEach(serviceKey => {
                const service = services[serviceKey];
                const statusClass = service.status || 'unknown';
                
                let infoHtml = '';
                if (service.status === 'running') {
                    infoHtml = `
                        <div class="service-info">
                            <div class="service-info-item">
                                <strong>PID</strong>
                                ${service.pid || 'N/A'}
                            </div>
                            <div class="service-info-item">
                                <strong>端口</strong>
                                ${service.port || 'N/A'}
                            </div>
                            <div class="service-info-item">
                                <strong>CPU</strong>
                                ${service.cpu_percent ? service.cpu_percent.toFixed(1) + '%' : 'N/A'}
                            </div>
                            <div class="service-info-item">
                                <strong>内存</strong>
                                ${service.memory_mb ? service.memory_mb.toFixed(1) + ' MB' : 'N/A'}
                            </div>
                        </div>
                    `;
                } else {
                    infoHtml = `
                        <div class="service-info">
                            <div class="service-info-item">
                                <strong>端口</strong>
                                ${service.port || 'N/A'}
                            </div>
                        </div>
                    `;
                }
                
                let actionsHtml = '';
                if (service.status === 'running') {
                    actionsHtml = `
                        <button class="btn btn-danger" onclick="stopService('${serviceKey}')">⏹️ 停止</button>
                        <button class="btn btn-primary" onclick="restartService('${serviceKey}')">🔄 重启</button>
                    `;
                } else {
                    actionsHtml = `
                        <button class="btn btn-success" onclick="startService('${serviceKey}')">▶️ 启动</button>
                    `;
                }
                
                container.innerHTML += `
                    <div class="service-card">
                        <h4>
                            🖥️ ${service.name || serviceKey}
                            <span class="service-status ${statusClass}">
                                ${statusIcon[statusClass]} ${statusText[statusClass]}
                            </span>
                        </h4>
                        <p style="color: #6c757d; margin-bottom: 10px; font-size: 14px;">
                            ${service.description || '无描述'}
                        </p>
                        <div style="color: #7f8c8d; font-size: 12px; margin-bottom: 10px;">
                            <strong>脚本:</strong> ${service.script || 'N/A'}
                        </div>
                        ${infoHtml}
                        <div class="service-actions">
                            ${actionsHtml}
                        </div>
                    </div>
                `;
            });
        }
        
        async function startService(serviceName) {
            showStatus('⏳ 正在启动服务...', 'info');
            
            try {
                const response = await fetch(`/api/services/${serviceName}/start`, {
                    method: 'POST'
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showStatus('✅ ' + result.message, 'success');
                    await loadServicesStatus();
                } else {
                    showStatus('❌ ' + result.error, 'error');
                }
            } catch (error) {
                showStatus('❌ 启动服务失败: ' + error.message, 'error');
            }
        }
        
        async function stopService(serviceName) {
            showStatus('⏳ 正在停止服务...', 'info');
            
            try {
                const response = await fetch(`/api/services/${serviceName}/stop`, {
                    method: 'POST'
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showStatus('✅ ' + result.message, 'success');
                    await loadServicesStatus();
                } else {
                    showStatus('❌ ' + result.error, 'error');
                }
            } catch (error) {
                showStatus('❌ 停止服务失败: ' + error.message, 'error');
            }
        }
        
        async function restartService(serviceName) {
            showStatus('⏳ 正在重启服务...', 'info');
            
            try {
                const response = await fetch(`/api/services/${serviceName}/restart`, {
                    method: 'POST'
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showStatus('✅ ' + result.message, 'success');
                    await loadServicesStatus();
                } else {
                    showStatus('❌ ' + result.error, 'error');
                }
            } catch (error) {
                showStatus('❌ 重启服务失败: ' + error.message, 'error');
            }
        }
        
        async function refreshServicesStatus() {
            showStatus('⏳ 正在刷新服务状态...', 'info');
            await loadServicesStatus();
            showStatus('✅ 服务状态已刷新', 'success');
        }
        
        window.onload = function() {
            loadConfiguration();
            loadServicesStatus();
        };
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'GET':
        return jsonify(load_config())
    else:
        try:
            config = request.json
            if not config:
                return jsonify({'success': False, 'error': '配置数据为空'})
            is_valid, errors, warnings = validate_config(config)
            if not is_valid:
                return jsonify({
                    'success': False, 
                    'error': '配置验证失败:\n' + '\n'.join(errors),
                    'errors': errors,
                    'warnings': warnings
                })
            save_config(config)
            result = {'success': True, 'message': '配置保存成功'}
            if warnings:
                result['warnings'] = warnings
            return jsonify(result)
        except json.JSONDecodeError:
            return jsonify({'success': False, 'error': '配置数据格式错误，不是有效的JSON'})
        except Exception as e:
            return jsonify({'success': False, 'error': f'保存配置时发生错误: {str(e)}'})

@app.route('/api/validate', methods=['POST'])
def validate_config_api():
    try:
        config = request.json
        if not config:
            return jsonify({'valid': False, 'error': '配置数据为空'})
        is_valid, errors, warnings = validate_config(config)
        return jsonify({
            'valid': is_valid,
            'errors': errors,
            'warnings': warnings
        })
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)})

@app.route('/api/test')
def test_config():
    try:
        config = load_config()
        results = {
            'success': True,
            'message': '配置测试完成',
            'details': {
                'agents': {'count': 0, 'status': 'ok'},
                'llms': {'count': 0, 'status': 'ok'},
                'im': {'platforms': [], 'status': 'ok'},
                'workflow': {'mode': '', 'status': 'ok'}
            },
            'warnings': [],
            'errors': []
        }
        if config.get('agents'):
            results['details']['agents']['count'] = len(config['agents'])
            for i, agent in enumerate(config['agents']):
                agent_errors = validate_agent(agent, i)
                if agent_errors:
                    results['errors'].extend(agent_errors)
        else:
            results['warnings'].append('未配置任何Agent')
        if config.get('llms'):
            results['details']['llms']['count'] = len(config['llms'])
            for i, llm in enumerate(config['llms']):
                llm_errors = validate_llm(llm, i)
                if llm_errors:
                    results['errors'].extend(llm_errors)
        else:
            results['warnings'].append('未配置任何LLM模型，将使用默认配置')
        if config.get('im', {}).get('global_im'):
            enabled_platforms = []
            for platform, im_config in config['im']['global_im'].items():
                if im_config.get('enabled', False):
                    enabled_platforms.append(platform)
                    if not im_config.get('app_id') or not im_config.get('app_secret'):
                        results['errors'].append(f'全局IM平台 {platform} 已启用但配置不完整')
            results['details']['im']['platforms'] = enabled_platforms
        workflow = config.get('workflow', 'sequential')
        results['details']['workflow']['mode'] = workflow
        if workflow not in ['sequential', 'parallel', 'conditional']:
            results['errors'].append(f'工作流模式 {workflow} 无效')
        if results['errors']:
            results['success'] = False
            results['message'] = '配置测试发现问题'
        return jsonify(results)
    except Exception as e:
        return jsonify({'success': False, 'error': f'测试配置时发生错误: {str(e)}'})

@app.route('/api/test-llm', methods=['POST'])
def test_llm():
    try:
        data = request.json
        provider = data.get('provider', '').strip()
        base_url = data.get('base_url', '').strip()
        api_key = data.get('api_key', '').strip()
        model_id = data.get('model_id', '').strip()
        if not all([provider, base_url, api_key, model_id]):
            missing = []
            if not provider: missing.append('Provider')
            if not base_url: missing.append('Base URL')
            if not api_key: missing.append('API Key')
            if not model_id: missing.append('Model ID')
            return jsonify({'success': False, 'error': f'缺少必要参数: {", ".join(missing)}'})
        headers = {
            'Content-Type': 'application/json'
        }
        if '智普' in provider or 'zhipu' in provider.lower():
            headers['Authorization'] = f'Bearer {api_key}'
        else:
            headers['Authorization'] = f'Bearer {api_key}'
        test_data = {
            'model': model_id,
            'messages': [{'role': 'user', 'content': 'Hi'}],
            'max_tokens': 5,
            'temperature': 0.1
        }
        api_url = f"{base_url.rstrip('/')}/chat/completions"
        try:
            response = requests.post(
                api_url,
                headers=headers,
                json=test_data,
                timeout=15
            )
            if response.status_code == 200:
                try:
                    result = response.json()
                    if 'choices' in result or 'data' in result:
                        return jsonify({
                            'success': True, 
                            'message': f'连接测试成功！Provider: {provider}, Model: {model_id}'
                        })
                    else:
                        return jsonify({
                            'success': True, 
                            'message': '连接测试成功（响应格式非标准）',
                            'warning': 'API响应格式可能与预期不同'
                        })
                except:
                    return jsonify({'success': True, 'message': '连接测试成功'})
            elif response.status_code == 401:
                return jsonify({'success': False, 'error': 'API Key无效或已过期'})
            elif response.status_code == 404:
                return jsonify({'success': False, 'error': 'API端点不存在，请检查Base URL'})
            elif response.status_code == 429:
                return jsonify({'success': False, 'error': 'API请求频率超限，请稍后重试'})
            elif response.status_code == 500:
                return jsonify({'success': False, 'error': 'API服务器内部错误'})
            else:
                error_msg = f'API返回错误 (HTTP {response.status_code})'
                try:
                    error_detail = response.json()
                    if 'error' in error_detail:
                        error_msg += f': {error_detail["error"].get("message", str(error_detail["error"]))}'
                except:
                    error_msg += f': {response.text[:200]}'
                return jsonify({'success': False, 'error': error_msg})
        except requests.exceptions.Timeout:
            return jsonify({'success': False, 'error': '连接超时（15秒），请检查网络或Base URL是否正确'})
        except requests.exceptions.ConnectionError as e:
            return jsonify({'success': False, 'error': f'无法连接到服务器，请检查Base URL是否正确: {str(e)[:100]}'})
        except requests.exceptions.RequestException as e:
            return jsonify({'success': False, 'error': f'请求失败: {str(e)}'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'测试过程发生错误: {str(e)}'})

@app.route('/api/test-im', methods=['POST'])
def test_im():
    try:
        data = request.json
        platform = data.get('platform', '').strip()
        app_id = data.get('app_id', '').strip()
        app_secret = data.get('app_secret', '').strip()
        if not all([platform, app_id, app_secret]):
            missing = []
            if not platform: missing.append('平台')
            if not app_id: missing.append('App ID')
            if not app_secret: missing.append('App Secret')
            return jsonify({'success': False, 'error': f'缺少必要参数: {", ".join(missing)}'})
        if platform == 'feishu':
            try:
                token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
                response = requests.post(
                    token_url,
                    json={"app_id": app_id, "app_secret": app_secret},
                    timeout=10
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get('code') == 0:
                        return jsonify({'success': True, 'message': '飞书连接测试成功！App ID和Secret有效'})
                    else:
                        return jsonify({
                            'success': False, 
                            'error': f"飞书认证失败: {result.get('msg', '未知错误')}"
                        })
                else:
                    return jsonify({'success': False, 'error': f'飞书API请求失败: HTTP {response.status_code}'})
            except requests.exceptions.Timeout:
                return jsonify({'success': False, 'error': '连接飞书服务器超时'})
            except requests.exceptions.ConnectionError:
                return jsonify({'success': False, 'error': '无法连接到飞书服务器，请检查网络'})
            except Exception as e:
                return jsonify({'success': False, 'error': f'飞书测试失败: {str(e)}'})
        elif platform == 'dingtalk':
            try:
                token_url = "https://oapi.dingtalk.com/gettoken"
                response = requests.get(
                    token_url,
                    params={"appkey": app_id, "appsecret": app_secret},
                    timeout=10
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get('errcode') == 0:
                        return jsonify({'success': True, 'message': '钉钉连接测试成功！'})
                    else:
                        return jsonify({
                            'success': False, 
                            'error': f"钉钉认证失败: {result.get('errmsg', '未知错误')}"
                        })
                else:
                    return jsonify({'success': False, 'error': f'钉钉API请求失败: HTTP {response.status_code}'})
            except requests.exceptions.Timeout:
                return jsonify({'success': False, 'error': '连接钉钉服务器超时'})
            except requests.exceptions.ConnectionError:
                return jsonify({'success': False, 'error': '无法连接到钉钉服务器，请检查网络'})
            except Exception as e:
                return jsonify({'success': False, 'error': f'钉钉测试失败: {str(e)}'})
        elif platform == 'web':
            return jsonify({'success': True, 'message': 'Web界面无需测试，配置已保存'})
        else:
            return jsonify({
                'success': True, 
                'message': f'{platform}平台配置已保存（暂不支持在线测试）',
                'warning': '该平台的连接测试功能尚未实现'
            })
    except Exception as e:
        return jsonify({'success': False, 'error': f'测试过程发生错误: {str(e)}'})

@app.route('/api/llm/<llm_id>', methods=['DELETE'])
def delete_llm_api(llm_id):
    try:
        config = load_config()
        if 'llms' not in config:
            return jsonify({'success': False, 'error': '配置中没有LLM列表'})
        original_count = len(config['llms'])
        config['llms'] = [llm for llm in config['llms'] if llm.get('id') != llm_id]
        if len(config['llms']) == original_count:
            return jsonify({'success': False, 'error': f'未找到ID为 {llm_id} 的LLM配置'})
        save_config(config)
        return jsonify({'success': True, 'message': 'LLM配置已删除'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/agent/<int:agent_index>', methods=['DELETE'])
def delete_agent_api(agent_index):
    try:
        config = load_config()
        if 'agents' not in config or agent_index >= len(config['agents']) or agent_index < 0:
            return jsonify({'success': False, 'error': f'Agent索引 {agent_index} 无效'})
        deleted_agent = config['agents'].pop(agent_index)
        save_config(config)
        return jsonify({'success': True, 'message': f'Agent "{deleted_agent.get("name", "")}" 已删除'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/export', methods=['GET'])
def export_config():
    try:
        config = load_config()
        config['_export_info'] = {
            'export_time': datetime.now().isoformat(),
            'version': '1.0',
            'source': 'multi_agent_im_config_center'
        }
        config_json = json.dumps(config, ensure_ascii=False, indent=2)
        buffer = BytesIO(config_json.encode('utf-8'))
        buffer.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'config_backup_{timestamp}.json'
        return send_file(
            buffer,
            mimetype='application/json',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({'success': False, 'error': f'导出配置失败: {str(e)}'})

def validate_import_config(config: Dict) -> Tuple[bool, List[str], List[str]]:
    errors = []
    warnings = []
    if not isinstance(config, dict):
        errors.append('配置必须是一个JSON对象')
        return False, errors, warnings
    required_sections = ['im', 'agents']
    for section in required_sections:
        if section not in config:
            errors.append(f'缺少必需的配置节: {section}')
    if 'im' in config:
        im_config = config['im']
        if not isinstance(im_config, dict):
            errors.append('im配置必须是对象类型')
        elif 'global_im' in im_config:
            if not isinstance(im_config['global_im'], dict):
                errors.append('global_im配置必须是对象类型')
            else:
                valid_platforms = ['feishu', 'dingtalk', 'qq', 'discord', 'web']
                for platform, platform_config in im_config['global_im'].items():
                    if platform not in valid_platforms:
                        warnings.append(f'未知的IM平台: {platform}')
                    if not isinstance(platform_config, dict):
                        errors.append(f'IM平台 {platform} 的配置必须是对象类型')
                    else:
                        for field in ['app_id', 'app_secret', 'enabled']:
                            if field not in platform_config:
                                if field != 'enabled':
                                    warnings.append(f'IM平台 {platform} 缺少字段: {field}')
                        if 'enabled' in platform_config and not isinstance(platform_config['enabled'], bool):
                            errors.append(f'IM平台 {platform} 的enabled字段必须是布尔值')
    if 'agents' in config:
        if not isinstance(config['agents'], list):
            errors.append('agents配置必须是数组类型')
        else:
            for i, agent in enumerate(config['agents']):
                if not isinstance(agent, dict):
                    errors.append(f'Agent {i + 1} 必须是对象类型')
                else:
                    required_agent_fields = ['name', 'role', 'model', 'system_prompt']
                    for field in required_agent_fields:
                        if field not in agent:
                            errors.append(f'Agent {i + 1} 缺少必需字段: {field}')
                        elif not isinstance(agent.get(field), str):
                            errors.append(f'Agent {i + 1} 的 {field} 字段必须是字符串')
                    if 'enabled' in agent and not isinstance(agent['enabled'], bool):
                        errors.append(f'Agent {i + 1} 的enabled字段必须是布尔值')
    if 'llms' in config:
        if not isinstance(config['llms'], list):
            errors.append('llms配置必须是数组类型')
        else:
            for i, llm in enumerate(config['llms']):
                if not isinstance(llm, dict):
                    errors.append(f'LLM {i + 1} 必须是对象类型')
                else:
                    required_llm_fields = ['provider', 'base_url', 'api_key', 'model_id', 'display_name', 'id']
                    for field in required_llm_fields:
                        if field not in llm:
                            errors.append(f'LLM {i + 1} 缺少必需字段: {field}')
    if 'workflow' in config:
        valid_workflows = ['sequential', 'parallel', 'conditional']
        if config['workflow'] not in valid_workflows:
            errors.append(f'工作流模式无效: {config["workflow"]}，必须是 {", ".join(valid_workflows)} 之一')
    return len(errors) == 0, errors, warnings

@app.route('/api/import', methods=['POST'])
def import_config():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '没有上传文件'})
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': '没有选择文件'})
        if not file.filename.endswith('.json'):
            return jsonify({'success': False, 'error': '文件格式不正确，请上传JSON文件'})
        try:
            content = file.read().decode('utf-8')
            imported_config = json.loads(content)
        except json.JSONDecodeError as e:
            return jsonify({'success': False, 'error': f'JSON解析失败: {str(e)}'})
        except UnicodeDecodeError:
            return jsonify({'success': False, 'error': '文件编码错误，请使用UTF-8编码的文件'})
        is_valid, errors, warnings = validate_import_config(imported_config)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': '配置验证失败',
                'errors': errors,
                'warnings': warnings
            })
        if '_export_info' in imported_config:
            del imported_config['_export_info']
        is_valid, validate_errors, validate_warnings = validate_config(imported_config)
        all_warnings = warnings + validate_warnings
        save_config(imported_config)
        result = {
            'success': True,
            'message': '配置导入成功',
            'config': imported_config,
            'warnings': all_warnings if all_warnings else []
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': f'导入配置失败: {str(e)}'})

@app.route('/api/services/status', methods=['GET'])
def get_services_status_api():
    try:
        statuses = get_all_services_status()
        return jsonify({
            'success': True,
            'services': statuses
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'获取服务状态失败: {str(e)}'})

@app.route('/api/services/<service_name>/<action>', methods=['POST'])
def manage_service(service_name, action):
    try:
        if service_name not in SERVICES_CONFIG:
            return jsonify({'success': False, 'error': f'服务 {service_name} 不存在'})
        
        if action == 'start':
            result = start_service(service_name)
        elif action == 'stop':
            result = stop_service(service_name)
        elif action == 'restart':
            result = restart_service(service_name)
        else:
            return jsonify({'success': False, 'error': f'不支持的操作: {action}'})
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': f'操作失败: {str(e)}'})

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("多 Agent + IM 配置中心启动中...")
    print("=" * 60)
    print("\n访问地址: http://localhost:8080")
    print("配置文件: config.json")
    print("\nAPI端点:")
    print("  GET  /api/config                - 获取配置")
    print("  POST /api/config                - 保存配置")
    print("  POST /api/validate              - 验证配置")
    print("  GET  /api/test                  - 测试配置")
    print("  POST /api/test-llm              - 测试LLM连接")
    print("  POST /api/test-im               - 测试IM连接")
    print("  GET  /api/export                - 导出配置文件")
    print("  POST /api/import                - 导入配置文件")
    print("  GET  /api/services/status       - 获取所有服务状态")
    print("  POST /api/services/<name>/<action> - 服务管理(start/stop/restart)")
    print("\n按 Ctrl+C 停止服务\n")
    app.run(host='0.0.0.0', port=8080, debug=False)
