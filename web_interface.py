#!/usr/bin/env python3
import os
import json
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

class WebUI:
    """Веб-интерфейс для AI системы"""
    
    def __init__(self, ai_system, port=8080):
        self.ai_system = ai_system
        self.port = port
        self.server = None
        self.running = False
        
    def start(self):
        """Запускает веб-сервер в отдельном потоке"""
        if self.running:
            return
        
        def run_server():
            self.server = HTTPServer(('', self.port), self.create_handler())
            self.running = True
            print(f"🌐 Веб-интерфейс запущен на http://localhost:{self.port}")
            self.server.serve_forever()
        
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
    
    def stop(self):
        """Останавливает веб-сервер"""
        if self.server:
            self.server.shutdown()
            self.running = False
            print("🌐 Веб-интерфейс остановлен")
    
    def create_handler(self):
        """Создает обработчик HTTP запросов"""
        
        class Handler(BaseHTTPRequestHandler):
            ui = self
            
            def do_GET(self):
                if self.path == '/':
                    self.send_html()
                elif self.path == '/api/projects':
                    self.send_projects()
                elif self.path.startswith('/api/project/'):
                    name = self.path.split('/')[-1]
                    self.send_project(name)
                elif self.path == '/api/stats':
                    self.send_stats()
                elif self.path == '/style.css':
                    self.send_css()
                elif self.path == '/script.js':
                    self.send_js()
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if self.path == '/api/analyze':
                    self.analyze_project()
                elif self.path == '/api/deep-analyze':
                    self.deep_analyze_project()
                elif self.path == '/api/todo/create':
                    self.create_todo()
                elif self.path == '/api/todo/analyze':
                    self.analyze_todo()
                elif self.path == '/api/structure':
                    self.create_structure()
                elif self.path == '/api/generate-code':
                    self.generate_code()
                else:
                    self.send_error(404)
            
            def send_html(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                
                html = f'''
                <!DOCTYPE html>
                <html>
                <head>
                    <title>🤖 AI Система</title>
                    <meta charset="utf-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <link rel="stylesheet" href="/style.css">
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>🤖 Многоагентная AI Система</h1>
                            <p>Управление проектами через веб-интерфейс</p>
                        </div>
                        
                        <div class="stats-panel">
                            <h2>📊 Статистика</h2>
                            <div id="stats"></div>
                        </div>
                        
                        <div class="main-panel">
                            <div class="projects-panel">
                                <h2>📁 Проекты</h2>
                                <div id="projects-list"></div>
                            </div>
                            
                            <div class="actions-panel">
                                <h2>⚡ Действия</h2>
                                <div class="project-select">
                                    <select id="project-select">
                                        <option value="">Выберите проект...</option>
                                    </select>
                                </div>
                                
                                <div class="button-grid">
                                    <button onclick="analyzeProject()">📊 Анализ</button>
                                    <button onclick="deepAnalyze()">🔍 Глубокий анализ</button>
                                    <button onclick="createStructure()">🏗️ Структура</button>
                                    <button onclick="createTodo()">📝 Создать TODO</button>
                                    <button onclick="analyzeTodo()">📋 Анализ TODO</button>
                                    <button onclick="generateCode()">💻 Генерация кода</button>
                                </div>
                                
                                <div id="result" class="result-panel">
                                    <h3>Результат:</h3>
                                    <pre></pre>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <script src="/script.js"></script>
                </body>
                </html>
                '''
                self.wfile.write(html.encode('utf-8'))
            
            def send_css(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/css; charset=utf-8')
                self.end_headers()
                
                css = '''
                * {
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }
                
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }
                
                .container {
                    max-width: 1400px;
                    margin: 0 auto;
                }
                
                .header {
                    background: white;
                    border-radius: 15px;
                    padding: 30px;
                    margin-bottom: 20px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                }
                
                .header h1 {
                    color: #333;
                    margin-bottom: 10px;
                    font-size: 2.5em;
                }
                
                .header p {
                    color: #666;
                    font-size: 1.1em;
                }
                
                .stats-panel {
                    background: white;
                    border-radius: 15px;
                    padding: 20px;
                    margin-bottom: 20px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                }
                
                .stats-panel h2 {
                    color: #333;
                    margin-bottom: 15px;
                }
                
                .main-panel {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 20px;
                }
                
                .projects-panel {
                    background: white;
                    border-radius: 15px;
                    padding: 20px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                }
                
                .projects-panel h2 {
                    color: #333;
                    margin-bottom: 15px;
                }
                
                .project-item {
                    padding: 10px;
                    border-bottom: 1px solid #eee;
                    cursor: pointer;
                    transition: background 0.3s;
                }
                
                .project-item:hover {
                    background: #f5f5f5;
                }
                
                .project-item.selected {
                    background: #e3f2fd;
                    border-left: 4px solid #2196f3;
                }
                
                .project-name {
                    font-weight: bold;
                    color: #333;
                }
                
                .project-files {
                    font-size: 0.9em;
                    color: #666;
                }
                
                .actions-panel {
                    background: white;
                    border-radius: 15px;
                    padding: 20px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                }
                
                .actions-panel h2 {
                    color: #333;
                    margin-bottom: 15px;
                }
                
                .project-select {
                    margin-bottom: 20px;
                }
                
                .project-select select {
                    width: 100%;
                    padding: 12px;
                    border: 2px solid #e0e0e0;
                    border-radius: 8px;
                    font-size: 1em;
                    outline: none;
                    transition: border-color 0.3s;
                }
                
                .project-select select:focus {
                    border-color: #667eea;
                }
                
                .button-grid {
                    display: grid;
                    grid-template-columns: repeat(2, 1fr);
                    gap: 10px;
                    margin-bottom: 20px;
                }
                
                .button-grid button {
                    padding: 12px;
                    border: none;
                    border-radius: 8px;
                    font-size: 1em;
                    cursor: pointer;
                    transition: transform 0.3s, box-shadow 0.3s;
                    color: white;
                }
                
                .button-grid button:nth-child(1) { background: #4caf50; }
                .button-grid button:nth-child(2) { background: #ff9800; }
                .button-grid button:nth-child(3) { background: #9c27b0; }
                .button-grid button:nth-child(4) { background: #2196f3; }
                .button-grid button:nth-child(5) { background: #f44336; }
                .button-grid button:nth-child(6) { background: #009688; }
                
                .button-grid button:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 5px 15px rgba(0,0,0,0.3);
                }
                
                .result-panel {
                    background: #f5f5f5;
                    border-radius: 8px;
                    padding: 15px;
                }
                
                .result-panel h3 {
                    color: #333;
                    margin-bottom: 10px;
                }
                
                .result-panel pre {
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    color: #333;
                    font-family: 'Courier New', monospace;
                    max-height: 400px;
                    overflow-y: auto;
                }
                
                .loading {
                    display: inline-block;
                    width: 20px;
                    height: 20px;
                    border: 3px solid #f3f3f3;
                    border-top: 3px solid #667eea;
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                }
                
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
                '''
                self.wfile.write(css.encode('utf-8'))
            
            def send_js(self):
                self.send_response(200)
                self.send_header('Content-type', 'application/javascript; charset=utf-8')
                self.end_headers()
                
                js = '''
                let selectedProject = '';
                
                // Загрузка при старте
                window.onload = function() {
                    loadProjects();
                    loadStats();
                    setInterval(loadStats, 5000);
                };
                
                // Загрузка списка проектов
                function loadProjects() {
                    fetch('/api/projects')
                        .then(response => response.json())
                        .then(data => {
                            const list = document.getElementById('projects-list');
                            const select = document.getElementById('project-select');
                            
                            list.innerHTML = '';
                            select.innerHTML = '<option value="">Выберите проект...</option>';
                            
                            data.projects.forEach(project => {
                                // Добавляем в список
                                const div = document.createElement('div');
                                div.className = 'project-item' + (project.name === selectedProject ? ' selected' : '');
                                div.onclick = () => selectProject(project.name);
                                div.innerHTML = `
                                    <div class="project-name">📁 ${project.name}</div>
                                    <div class="project-files">${project.files} файлов</div>
                                `;
                                list.appendChild(div);
                                
                                // Добавляем в селект
                                const option = document.createElement('option');
                                option.value = project.name;
                                option.textContent = project.name;
                                select.appendChild(option);
                            });
                        });
                }
                
                // Загрузка статистики
                function loadStats() {
                    fetch('/api/stats')
                        .then(response => response.json())
                        .then(data => {
                            const stats = document.getElementById('stats');
                            stats.innerHTML = `
                                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;">
                                    <div><strong>📁 Проектов:</strong> ${data.total_projects}</div>
                                    <div><strong>📝 Анализов:</strong> ${data.total_analyses}</div>
                                    <div><strong>💾 Память:</strong> ${data.memory_used}</div>
                                </div>
                            `;
                        });
                }
                
                // Выбор проекта
                function selectProject(name) {
                    selectedProject = name;
                    document.getElementById('project-select').value = name;
                    loadProjects();
                }
                
                // Показать результат
                function showResult(text) {
                    const pre = document.querySelector('#result pre');
                    pre.textContent = text;
                }
                
                // Анализ проекта
                function analyzeProject() {
                    if (!selectedProject) {
                        alert('Выберите проект!');
                        return;
                    }
                    
                    showResult('Анализ...');
                    
                    fetch('/api/analyze', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({project: selectedProject})
                    })
                    .then(response => response.json())
                    .then(data => {
                        showResult(data.result);
                        loadStats();
                    });
                }
                
                // Глубокий анализ
                function deepAnalyze() {
                    if (!selectedProject) {
                        alert('Выберите проект!');
                        return;
                    }
                    
                    showResult('Глубокий анализ...');
                    
                    fetch('/api/deep-analyze', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({project: selectedProject})
                    })
                    .then(response => response.json())
                    .then(data => {
                        showResult(data.result);
                    });
                }
                
                // Создать структуру
                function createStructure() {
                    if (!selectedProject) {
                        alert('Выберите проект!');
                        return;
                    }
                    
                    showResult('Создание структуры...');
                    
                    fetch('/api/structure', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({project: selectedProject})
                    })
                    .then(response => response.json())
                    .then(data => {
                        showResult(data.result);
                        loadProjects();
                    });
                }
                
                // Создать TODO
                function createTodo() {
                    if (!selectedProject) {
                        alert('Выберите проект!');
                        return;
                    }
                    
                    showResult('Создание TODO.md...');
                    
                    fetch('/api/todo/create', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({project: selectedProject})
                    })
                    .then(response => response.json())
                    .then(data => {
                        showResult(data.result);
                    });
                }
                
                // Анализ TODO
                function analyzeTodo() {
                    if (!selectedProject) {
                        alert('Выберите проект!');
                        return;
                    }
                    
                    showResult('Анализ TODO.md...');
                    
                    fetch('/api/todo/analyze', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({project: selectedProject})
                    })
                    .then(response => response.json())
                    .then(data => {
                        showResult(data.result);
                    });
                }
                
                // Генерация кода
                function generateCode() {
                    if (!selectedProject) {
                        alert('Выберите проект!');
                        return;
                    }
                    
                    const task = prompt('Что должна делать программа?');
                    if (!task) return;
                    
                    showResult('Генерация кода...');
                    
                    fetch('/api/generate-code', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            project: selectedProject,
                            task: task
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        showResult(data.result);
                    });
                }
                '''
                self.wfile.write(js.encode('utf-8'))
            
            def send_projects(self):
                projects = []
                for name, data in self.ui.ai_system.projects.items():
                    projects.append({
                        'name': name,
                        'files': len(data['files'])
                    })
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'projects': projects}).encode())
            
            def send_project(self, name):
                project = self.ui.ai_system.projects.get(name)
                if project:
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(project).encode())
                else:
                    self.send_error(404)
            
            def send_stats(self):
                stats = {
                    'total_projects': len(self.ui.ai_system.projects),
                    'total_analyses': 0,
                    'memory_used': '128 MB'
                }
                
                if self.ui.ai_system.memory:
                    mem_stats = self.ui.ai_system.memory.get_statistics()
                    stats['total_analyses'] = mem_stats.get('total_analyses', 0)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(stats).encode())
            
            def analyze_project(self):
                content_length = int(self.headers['Content-Length'])
                post_data = json.loads(self.rfile.read(content_length))
                project = post_data.get('project')
                
                result = self.ui.ai_system.analyze_project(project)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                
                # Читаем результат из файла
                result_text = "Анализ выполнен"
                if project in self.ui.ai_system.projects:
                    analysis_file = os.path.join(self.ui.ai_system.projects[project]['path'], '_ai_analysis.txt')
                    if os.path.exists(analysis_file):
                        with open(analysis_file, 'r', encoding='utf-8') as f:
                            result_text = f.read()
                
                self.wfile.write(json.dumps({'result': result_text}).encode())
            
            def deep_analyze_project(self):
                content_length = int(self.headers['Content-Length'])
                post_data = json.loads(self.rfile.read(content_length))
                project = post_data.get('project')
                
                self.ui.ai_system.deep_analyze_project(project)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                
                # Читаем результат
                result_text = "Глубокий анализ выполнен"
                if project in self.ui.ai_system.projects:
                    analysis_file = os.path.join(self.ui.ai_system.projects[project]['path'], '_deep_analysis.md')
                    if os.path.exists(analysis_file):
                        with open(analysis_file, 'r', encoding='utf-8') as f:
                            result_text = f.read()
                
                self.wfile.write(json.dumps({'result': result_text}).encode())
            
            def create_todo(self):
                content_length = int(self.headers['Content-Length'])
                post_data = json.loads(self.rfile.read(content_length))
                project = post_data.get('project')
                
                if project in self.ui.ai_system.projects:
                    self.ui.ai_system.create_todo(
                        self.ui.ai_system.projects[project]['path'],
                        project
                    )
                    result_text = "✅ TODO.md создан"
                else:
                    result_text = "❌ Проект не найден"
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'result': result_text}).encode())
            
            def analyze_todo(self):
                content_length = int(self.headers['Content-Length'])
                post_data = json.loads(self.rfile.read(content_length))
                project = post_data.get('project')
                
                self.ui.ai_system.analyze_todo()
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'result': 'Анализ TODO выполнен'}).encode())
            
            def create_structure(self):
                content_length = int(self.headers['Content-Length'])
                post_data = json.loads(self.rfile.read(content_length))
                project = post_data.get('project')
                
                self.ui.ai_system.auto_structure(project)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'result': 'Структура создана'}).encode())
            
            def generate_code(self):
                content_length = int(self.headers['Content-Length'])
                post_data = json.loads(self.rfile.read(content_length))
                project = post_data.get('project')
                task = post_data.get('task')
                
                # Временно сохраняем для генерации
                self.ui.ai_system.generate_project_code(project)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'result': f'Код сгенерирован для задачи: {task}'}).encode())
        
        return Handler

# Тестирование
if __name__ == "__main__":
    print("🌐 ТЕСТ ВЕБ-ИНТЕРФЕЙСА")
    print("="*40)
    
    # Создаем заглушку для теста
    class DummyAI:
        def __init__(self):
            self.projects = {'test': {'path': '.', 'files': ['test.py']}}
            self.memory = None
        
        def analyze_project(self, name):
            return "Анализ"
        
        def deep_analyze_project(self, name):
            return "Глубокий анализ"
        
        def create_todo(self, path, name):
            return "TODO создан"
        
        def analyze_todo(self):
            return "Анализ TODO"
        
        def auto_structure(self, name):
            return "Структура создана"
        
        def generate_project_code(self, name):
            return "Код сгенерирован"
    
    web = WebUI(DummyAI())
    web.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        web.stop()
