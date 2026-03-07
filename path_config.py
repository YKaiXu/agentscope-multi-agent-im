#!/usr/bin/env python3
"""
路径配置模块 - 支持可移植性

优先级：
1. 环境变量
2. 配置文件
3. 默认值（项目内路径）
"""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).parent

def get_project_dir() -> Path:
    return Path(os.getenv("MULTI_AGENT_PROJECT_DIR", str(PROJECT_DIR)))

def get_config_path() -> Path:
    return get_project_dir() / "config.json"

def get_media_dir() -> Path:
    env_media = os.getenv("MULTI_AGENT_MEDIA_DIR")
    if env_media:
        return Path(env_media)
    
    project_media = get_project_dir() / "media"
    if project_media.exists():
        return project_media
    
    old_media = Path.home() / ".copaw" / "media"
    if old_media.exists():
        return old_media
    
    return project_media

def get_logs_dir() -> Path:
    return get_project_dir() / "logs"

def get_venv_python() -> str:
    env_venv = os.getenv("MULTI_AGENT_VENV")
    if env_venv:
        return str(Path(env_venv) / "bin" / "python")
    
    project_venv = get_project_dir().parent / "agentscope_env" / "bin" / "python"
    if project_venv.exists():
        return str(project_venv)
    
    return "python3"

def get_venv_streamlit() -> str:
    env_venv = os.getenv("MULTI_AGENT_VENV")
    if env_venv:
        return str(Path(env_venv) / "bin" / "streamlit")
    
    project_venv = get_project_dir().parent / "agentscope_env" / "bin" / "streamlit"
    if project_venv.exists():
        return str(project_venv)
    
    return "streamlit"

PROJECT_DIR = get_project_dir()
CONFIG_PATH = get_config_path()
MEDIA_DIR = get_media_dir()
LOGS_DIR = get_logs_dir()

MEDIA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
