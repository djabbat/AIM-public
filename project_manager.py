import os
import time
import threading
from datetime import datetime
import ollama
from agents.multilingual_agent import MultilingualAgent

class ProjectManager:
    def __init__(self):
        self.desktop = os.path.expanduser("~/Desktop")
        self.projects = {}
        self.watching = True
        self.analyzer = MultilingualAgent("Аналитик", "анализ проектов")
        
        print("\n" + "="*60)
        print("🚀 PROJECT MANAGER")
        print("="*60)
        print(f"📁 Проекты: {self.desktop}")
        print("="*60)
        
        self.scan_projects()
        self.watch_desktop()
    
    def scan_projects(self):
        print("\n🔍 Поиск проектов...")
        for item in os.listdir(self.desktop):
            path = os.path.join(self.desktop, item)
            if os.path.isdir(path) and not item.startswith('.'):
                self.add_project(item, path)
    
    def add_project(self, name, path):
        self.projects[name] = {
            'name': name,
            'path': path,
            'created': datetime.now(),
            'files': self.get_files(path)
        }
        print(f"  ✅ Проект: {name}")
        self.analyze_project(name)
    
    def get_files(self, path):
        files = []
        for root, dirs, filenames in os.walk(path):
            for f in filenames[:20]:
                files.append(f)
        return files
    
    def analyze_project(self, name):
        project = self.projects.get(name)
        if not project:
            return
        
        print(f"\n🤖 Анализ проекта: {name}")
        
        prompt = f"""Проект: {name}
Файлы: {project['files'][:10]}

1. Что это за проект?
2. Какие файлы нужно создать?
3. Какую структуру добавить?
4. Идеи для развития"""
        
        analysis = self.analyzer.think(prompt)
        
        # Сохраняем анализ
        with open(os.path.join(project['path'], '_ai_analysis.txt'), 'w', encoding='utf-8') as f:
            f.write(f"AI АНАЛИЗ ПРОЕКТА: {name}\n")
            f.write("="*40 + "\n")
            f.write(analysis)
        
        print(f"  ✅ Анализ сохранен")
        return analysis
    
    def watch_desktop(self):
        def monitor():
            while self.watching:
                time.sleep(5)
                current = set(os.listdir(self.desktop))
                existing = set(self.projects.keys())
                
                for item in current:
                    path = os.path.join(self.desktop, item)
                    if (os.path.isdir(path) and 
                        not item.startswith('.') and 
                        item not in existing):
                        print(f"\n✨ НОВЫЙ ПРОЕКТ: {item}")
                        self.add_project(item, path)
        
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    
    def list_projects(self):
        print("\n📋 ПРОЕКТЫ:")
        if not self.projects:
            print("  Нет проектов")
            return
        
        for name, info in self.projects.items():
            print(f"  📁 {name} ({len(info['files'])} файлов)")
    
    def develop_project(self, name):
        project = self.projects.get(name)
        if not project:
            return
        
        print(f"\n🚀 Развитие проекта: {name}")
        
        # Создаем базовую структуру
        folders = ['docs', 'src', 'tests', 'data']
        for folder in folders:
            folder_path = os.path.join(project['path'], folder)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
                print(f"  📁 Создана папка: {folder}")
        
        # Создаем README
        readme_path = os.path.join(project['path'], 'README.md')
        if not os.path.exists(readme_path):
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(f"# {name}\n\nПроект управляется AI системой\n")
            print(f"  📝 Создан README.md")
    
        elif choice == "8":
            self.analyze_any_project()
    def run(self):
        while True:
            print("\n" + "="*40)
            print("ГЛАВНОЕ МЕНЮ:")
            print("1. Показать проекты")
            print("2. Анализ проекта")
            print("3. Развить проект")
            print("4. Анализ всех проектов")
            print("5. Выход")
            print("="*40)
            
            choice = input("\n👉 Выбор: ").strip()
            
            if choice == '1':
                self.list_projects()
            
            elif choice == '2':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    self.analyze_project(name)
                else:
                    print("❌ Проект не найден")
            
            elif choice == '3':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    self.develop_project(name)
                else:
                    print("❌ Проект не найден")
            
            elif choice == '4':
                for name in self.projects:
                    self.analyze_project(name)
                    time.sleep(2)
            
            elif choice == '5':
                self.watching = False
                print("👋 До свидания!")
                break

if __name__ == "__main__":
    ProjectManager().run()

    def analyze_any_project(self):
        """Анализ любого проекта по пути"""
        path = input("\nВведите путь к проекту: ").strip()
        if os.path.exists(path):
            print(f"\n🔍 Анализ проекта: {path}")
            os.system(f"python3 todo_analyzer.py '{path}'")
        else:
            print("❌ Путь не существует")

