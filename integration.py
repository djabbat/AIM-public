#!/usr/bin/env python3
import os
import json
import subprocess
import requests
from datetime import datetime

class IntegrationHub:
    """Интеграция с популярными инструментами разработки"""
    
    def __init__(self):
        self.integrations = {}
        self.config_dir = os.path.expanduser("~/AIM/integrations")
        os.makedirs(self.config_dir, exist_ok=True)
        self.load_configs()
    
    def load_configs(self):
        """Загружает конфигурации интеграций"""
        config_file = os.path.join(self.config_dir, 'integrations.json')
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                self.integrations = json.load(f)
    
    def save_configs(self):
        """Сохраняет конфигурации интеграций"""
        config_file = os.path.join(self.config_dir, 'integrations.json')
        with open(config_file, 'w') as f:
            json.dump(self.integrations, f, indent=2)

class GitHubIntegration:
    """Интеграция с GitHub"""
    
    def __init__(self, token=None):
        self.token = token or os.getenv('GITHUB_TOKEN')
        self.base_url = "https://api.github.com"
        self.headers = {'Authorization': f'token {self.token}'} if self.token else {}
    
    def create_repo(self, name, description="", private=False):
        """Создает репозиторий на GitHub"""
        url = f"{self.base_url}/user/repos"
        data = {
            'name': name,
            'description': description,
            'private': private,
            'auto_init': True
        }
        try:
            response = requests.post(url, json=data, headers=self.headers)
            if response.status_code == 201:
                return response.json()['html_url']
        except:
            pass
        return None
    
    def create_gist(self, files, description="", public=True):
        """Создает gist"""
        url = f"{self.base_url}/gists"
        data = {
            'description': description,
            'public': public,
            'files': files
        }
        try:
            response = requests.post(url, json=data, headers=self.headers)
            if response.status_code == 201:
                return response.json()['html_url']
        except:
            pass
        return None
    
    def get_repo_info(self, repo):
        """Получает информацию о репозитории"""
        url = f"{self.base_url}/repos/{repo}"
        try:
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return None

class GitLabIntegration:
    """Интеграция с GitLab"""
    
    def __init__(self, token=None):
        self.token = token or os.getenv('GITLAB_TOKEN')
        self.base_url = "https://gitlab.com/api/v4"
        self.headers = {'Authorization': f'Bearer {self.token}'} if self.token else {}
    
    def create_project(self, name, description=""):
        """Создает проект в GitLab"""
        url = f"{self.base_url}/projects"
        data = {
            'name': name,
            'description': description,
            'visibility': 'public'
        }
        try:
            response = requests.post(url, json=data, headers=self.headers)
            if response.status_code == 201:
                return response.json()['web_url']
        except:
            pass
        return None

class JiraIntegration:
    """Интеграция с Jira"""
    
    def __init__(self, url=None, email=None, token=None):
        self.url = url or os.getenv('JIRA_URL')
        self.email = email or os.getenv('JIRA_EMAIL')
        self.token = token or os.getenv('JIRA_TOKEN')
        self.auth = (self.email, self.token) if self.email and self.token else None
    
    def create_issue(self, project, summary, description, issue_type="Task"):
        """Создает задачу в Jira"""
        if not self.auth:
            return None
        
        url = f"{self.url}/rest/api/3/issue"
        data = {
            'fields': {
                'project': {'key': project},
                'summary': summary,
                'description': description,
                'issuetype': {'name': issue_type}
            }
        }
        try:
            response = requests.post(url, json=data, auth=self.auth)
            if response.status_code == 201:
                return response.json()['key']
        except:
            pass
        return None

class TrelloIntegration:
    """Интеграция с Trello"""
    
    def __init__(self, key=None, token=None):
        self.key = key or os.getenv('TRELLO_KEY')
        self.token = token or os.getenv('TRELLO_TOKEN')
        self.base_url = "https://api.trello.com/1"
        self.auth = {'key': self.key, 'token': self.token} if self.key and self.token else {}
    
    def create_card(self, list_id, name, description=""):
        """Создает карточку в Trello"""
        if not self.auth:
            return None
        
        url = f"{self.base_url}/cards"
        params = {
            'idList': list_id,
            'name': name,
            'desc': description,
            **self.auth
        }
        try:
            response = requests.post(url, params=params)
            if response.status_code == 200:
                return response.json()['url']
        except:
            pass
        return None
    
    def get_boards(self):
        """Получает список досок"""
        if not self.auth:
            return []
        
        url = f"{self.base_url}/members/me/boards"
        try:
            response = requests.get(url, params=self.auth)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return []

class SlackIntegration:
    """Интеграция со Slack"""
    
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url or os.getenv('SLACK_WEBHOOK')
    
    def send_message(self, message, channel=None):
        """Отправляет сообщение в Slack"""
        if not self.webhook_url:
            return False
        
        data = {'text': message}
        if channel:
            data['channel'] = channel
        
        try:
            response = requests.post(self.webhook_url, json=data)
            return response.status_code == 200
        except:
            return False

class VSCodeIntegration:
    """Интеграция с VS Code"""
    
    def __init__(self):
        self.vscode_path = self.find_vscode()
    
    def find_vscode(self):
        """Находит путь к VS Code"""
        common_paths = [
            '/usr/bin/code',
            '/usr/local/bin/code',
            'C:\\Program Files\\Microsoft VS Code\\Code.exe',
            os.path.expanduser('~/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code')
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
        return None
    
    def open_in_vscode(self, path):
        """Открывает папку в VS Code"""
        if self.vscode_path and os.path.exists(path):
            try:
                subprocess.run([self.vscode_path, path])
                return True
            except:
                pass
        return False
    
    def install_extension(self, extension_id):
        """Устанавливает расширение VS Code"""
        if self.vscode_path:
            try:
                subprocess.run([self.vscode_path, '--install-extension', extension_id])
                return True
            except:
                pass
        return False

class DockerIntegration:
    """Интеграция с Docker"""
    
    def __init__(self):
        self.docker_available = self.check_docker()
    
    def check_docker(self):
        """Проверяет наличие Docker"""
        try:
            result = subprocess.run(['docker', '--version'], capture_output=True)
            return result.returncode == 0
        except:
            return False
    
    def create_dockerfile(self, project_path, project_type):
        """Создает Dockerfile для проекта"""
        dockerfile_content = {
            'python': """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]""",
            'node': """FROM node:18
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
CMD ["npm", "start"]""",
            'default': """FROM ubuntu:latest
WORKDIR /app
COPY . .
CMD ["bash"]"""
        }
        
        content = dockerfile_content.get(project_type, dockerfile_content['default'])
        dockerfile_path = os.path.join(project_path, 'Dockerfile')
        
        with open(dockerfile_path, 'w') as f:
            f.write(content)
        
        return dockerfile_path
    
    def build_image(self, project_path, tag):
        """Собирает Docker образ"""
        if not self.docker_available:
            return False
        
        try:
            subprocess.run(['docker', 'build', '-t', tag, project_path])
            return True
        except:
            return False

class APIIntegration:
    """Интеграция с внешними API"""
    
    def __init__(self):
        self.apis = {}
    
    def register_api(self, name, base_url, api_key=None):
        """Регистрирует API"""
        self.apis[name] = {
            'base_url': base_url,
            'api_key': api_key,
            'headers': {'Authorization': f'Bearer {api_key}'} if api_key else {}
        }
    
    def call_api(self, name, endpoint, method='GET', data=None):
        """Вызывает API"""
        if name not in self.apis:
            return None
        
        api = self.apis[name]
        url = f"{api['base_url']}/{endpoint.lstrip('/')}"
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=api['headers'])
            elif method == 'POST':
                response = requests.post(url, json=data, headers=api['headers'])
            else:
                return None
            
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return None

class IntegrationManager:
    """Менеджер всех интеграций"""
    
    def __init__(self):
        self.github = GitHubIntegration()
        self.gitlab = GitLabIntegration()
        self.jira = JiraIntegration()
        self.trello = TrelloIntegration()
        self.slack = SlackIntegration()
        self.vscode = VSCodeIntegration()
        self.docker = DockerIntegration()
        self.api = APIIntegration()
        self.hub = IntegrationHub()
    
    def setup_project_integrations(self, project_path, project_name):
        """Настраивает все интеграции для проекта"""
        results = []
        
        # GitHub
        if self.github.token:
            repo_url = self.github.create_repo(project_name, f"AI generated project {project_name}")
            if repo_url:
                results.append(f"✅ GitHub: {repo_url}")
        
        # Docker
        if self.docker.docker_available:
            dockerfile = self.docker.create_dockerfile(project_path, 'python')
            results.append(f"✅ Docker: {dockerfile}")
        
        # VS Code
        if self.vscode.vscode_path:
            results.append(f"✅ VS Code: готов к открытию")
        
        return results
    
    def send_notification(self, message):
        """Отправляет уведомление во все каналы"""
        results = []
        
        if self.slack.webhook_url:
            if self.slack.send_message(message):
                results.append("✅ Slack")
        
        return results

# Тестирование
if __name__ == "__main__":
    manager = IntegrationManager()
    print("🔌 Интеграции загружены")
    print(f"  Docker: {'✅' if manager.docker.docker_available else '❌'}")
    print(f"  VS Code: {'✅' if manager.vscode.vscode_path else '❌'}")
    print(f"  GitHub: {'✅' if manager.github.token else '❌'}")
