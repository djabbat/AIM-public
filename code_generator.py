#!/usr/bin/env python3
import os
import ollama
from datetime import datetime

class ProjectStructure:
    """Класс для создания структуры проектов"""
    
    def __init__(self, model="llama3.2"):
        self.model = model
    
    def detect_project_type(self, files):
        """Определяет тип проекта по файлам"""
        files_lower = [f.lower() for f in files]
        
        if any(f.endswith('.py') for f in files_lower):
            return 'python'
        elif any(f.endswith(('.html', '.css', '.js')) for f in files_lower):
            return 'web'
        elif any(f.endswith(('.ipynb')) for f in files_lower):
            return 'jupyter'
        elif any(f.endswith(('.md', '.txt')) for f in files_lower):
            return 'documentation'
        else:
            return 'generic'
    
    def suggest_structure(self, project_name, project_type, existing_files):
        """AI предлагает структуру проекта"""
        
        prompt = f"""Проект: {project_name}
Тип: {project_type}
Существующие файлы: {existing_files[:15]}

Предложи оптимальную структуру папок и файлов для этого проекта.
Формат ответа: список папок и файлов которые нужно создать."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            return response['message']['content']
        except Exception as e:
            return f"Ошибка: {e}"
    
    def create_structure(self, project_path, structure_text):
        """Создает структуру папок и файлов"""
        created = []
        
        # Простой парсинг предложений
        lines = structure_text.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Убираем маркеры списка
            clean = line.lstrip('- *•').strip()
            
            if '/' in clean or '\\' in clean:
                # Это путь
                full_path = os.path.join(project_path, clean)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                if '.' in os.path.basename(clean):
                    # Это файл
                    if not os.path.exists(full_path):
                        with open(full_path, 'w', encoding='utf-8') as f:
                            f.write(f"# Автоматически создано AI\n")
                        created.append(f"📄 {clean}")
                else:
                    # Это папка
                    if not os.path.exists(full_path):
                        os.makedirs(full_path, exist_ok=True)
                        created.append(f"📁 {clean}/")
        
        return created
    
    def get_structure_templates(self, project_type):
        """Возвращает шаблоны структур для разных типов проектов"""
        
        templates = {
            'python': [
                'src/',
                'src/main.py',
                'src/utils/',
                'tests/',
                'tests/test_main.py',
                'data/',
                'notebooks/',
                'requirements.txt',
                'README.md',
                '.gitignore'
            ],
            'web': [
                'index.html',
                'css/',
                'css/style.css',
                'js/',
                'js/main.js',
                'images/',
                'README.md'
            ],
            'jupyter': [
                'notebooks/',
                'data/',
                'scripts/',
                'README.md',
                'requirements.txt'
            ],
            'documentation': [
                'docs/',
                'docs/getting-started.md',
                'docs/guide.md',
                'README.md'
            ],
            'generic': [
                'src/',
                'docs/',
                'tests/',
                'README.md'
            ]
        }
        
        return templates.get(project_type, templates['generic'])

class CodeGenerator:
    """Класс для генерации кода"""
    
    def __init__(self, model="llama3.2"):
        self.model = model
    
    def generate_code(self, task, language="python"):
        """Генерирует код по задаче"""
        
        prompt = f"""Напиши код на {language} для задачи:
{task}

Только код, без объяснений. Код должен быть готов к использованию."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            return response['message']['content']
        except Exception as e:
            return f"Ошибка: {e}"
    
    def generate_function(self, description, language="python"):
        """Генерирует функцию"""
        
        prompt = f"""Напиши функцию на {language} которая:
{description}

Только код функции."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            return response['message']['content']
        except Exception as e:
            return f"Ошибка: {e}"
    
    def generate_class(self, description, language="python"):
        """Генерирует класс"""
        
        prompt = f"""Напиши класс на {language} который:
{description}

Только код класса."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            return response['message']['content']
        except Exception as e:
            return f"Ошибка: {e}"
    
    def generate_test(self, code, language="python"):
        """Генерирует тесты для кода"""
        
        prompt = f"""Напиши тесты для этого кода на {language}:
{code}

Только код тестов."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            return response['message']['content']
        except Exception as e:
            return f"Ошибка: {e}"
    
    def improve_code(self, code, instructions=""):
        """Улучшает существующий код"""
        
        prompt = f"""Улучши этот код:
{code}

{instructions}

Верни улучшенную версию."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            return response['message']['content']
        except Exception as e:
            return f"Ошибка: {e}"
    
    def explain_code(self, code):
        """Объясняет код"""
        
        prompt = f"""Объясни что делает этот код простыми словами:
{code}"""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            return response['message']['content']
        except Exception as e:
            return f"Ошибка: {e}"
    
    def save_code(self, project_path, filename, code):
        """Сохраняет код в файл"""
        
        filepath = os.path.join(project_path, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(code)
        
        return filepath

# Тестирование
if __name__ == "__main__":
    print("🔧 ТЕСТ ГЕНЕРАЦИИ")
    print("="*40)
    
    struct = ProjectStructure()
    code_gen = CodeGenerator()
    
    # Тест структуры
    project_type = struct.detect_project_type(['main.py', 'utils.py'])
    print(f"Тип проекта: {project_type}")
    
    template = struct.get_structure_templates(project_type)
    print(f"\nШаблон структуры:")
    for item in template[:5]:
        print(f"  {item}")
    
    # Тест генерации кода
    code = code_gen.generate_function("сложение двух чисел")
    print(f"\nСгенерированный код:\n{code[:200]}...")
