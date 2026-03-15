#!/usr/bin/env python3
import os
import sys
import ollama
from datetime import datetime
import re

class ProjectAnalyzer:
    def __init__(self, project_path):
        self.project_path = os.path.abspath(project_path)
        self.project_name = os.path.basename(self.project_path)
        self.files = []
        self.todo_content = None
        self.readme_content = None
        self.model = "llama3.2"
        
        print(f"\n🔍 АНАЛИЗ ПРОЕКТА: {self.project_name}")
        print("="*60)
        
    def scan_project(self):
        """Сканирует все файлы проекта"""
        print("\n📁 Структура проекта:")
        for root, dirs, files in os.walk(self.project_path):
            # Пропускаем служебные папки
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['venv', '__pycache__', 'node_modules']]
            
            level = root.replace(self.project_path, '').count(os.sep)
            indent = '  ' * level
            print(f"{indent}📂 {os.path.basename(root)}/")
            
            subindent = '  ' * (level + 1)
            for file in files[:5]:  # Показываем первые 5 файлов
                file_path = os.path.join(root, file)
                self.files.append(file_path)
                
                # Ищем специальные файлы
                if file.lower() == 'todo.md':
                    self.read_todo(file_path)
                elif file.lower() == 'readme.md':
                    self.read_readme(file_path)
                
                size = os.path.getsize(file_path)
                print(f"{subindent}📄 {file} ({size} bytes)")
    
    def read_todo(self, filepath):
        """Читает TODO.md файл"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.todo_content = f.read()
            print(f"\n✅ Найден TODO.md: {len(self.todo_content)} символов")
        except:
            pass
    
    def read_readme(self, filepath):
        """Читает README.md файл"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.readme_content = f.read()
            print(f"✅ Найден README.md: {len(self.readme_content)} символов")
        except:
            pass
    
    def analyze_with_todo(self):
        """Анализирует проект согласно TODO.md"""
        if not self.todo_content:
            print("\n❌ TODO.md не найден. Создайте его для анализа.")
            return
        
        print("\n🤖 AI АНАЛИЗ ПО TODO.md")
        print("="*40)
        
        prompt = f"""Проект: {self.project_name}
        
TODO.md:
{self.todo_content[:2000]}

README.md:
{self.readme_content[:1000] if self.readme_content else 'Нет README'}

Файлы проекта:
{chr(10).join([f"- {os.path.basename(f)}" for f in self.files[:20]])}

Проанализируй проект согласно TODO.md и предложи:
1. Какие задачи из TODO уже выполнены?
2. Какие задачи нужно делать дальше?
3. В каком порядке их выполнять?
4. Конкретные шаги для следующей задачи
5. Какие файлы нужно создать/изменить?

Ответ дай структурированно."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'system', 'content': 'Ты помогаешь развивать проекты по TODO списку'},
                {'role': 'user', 'content': prompt}
            ])
            
            analysis = response['message']['content']
            
            # Сохраняем анализ
            output_file = os.path.join(self.project_path, '_ai_todo_analysis.md')
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# AI АНАЛИЗ ПО TODO.md\n")
                f.write(f"Проект: {self.project_name}\n")
                f.write(f"Дата: {datetime.now()}\n")
                f.write("="*60 + "\n\n")
                f.write(analysis)
            
            print(f"\n✅ Анализ сохранен: {output_file}")
            print("\n" + "="*40)
            print("РЕЗУЛЬТАТ АНАЛИЗА:")
            print("="*40)
            print(analysis)
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def create_todo_from_analysis(self):
        """Создает TODO.md если его нет"""
        if self.todo_content:
            return
        
        print("\n📝 Создание TODO.md...")
        
        prompt = f"""Проект: {self.project_name}
        
Файлы:
{chr(10).join([f"- {os.path.basename(f)}" for f in self.files[:20]])}

Создай TODO.md для этого проекта со списком задач:
- Что уже сделано (по файлам)
- Что нужно сделать
- Приоритеты
- Следующие шаги

Формат как markdown."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            todo = response['message']['content']
            
            todo_file = os.path.join(self.project_path, 'TODO.md')
            with open(todo_file, 'w', encoding='utf-8') as f:
                f.write(f"# TODO: {self.project_name}\n\n")
                f.write(f"Создано AI: {datetime.now()}\n")
                f.write("="*40 + "\n\n")
                f.write(todo)
            
            print(f"✅ TODO.md создан: {todo_file}")
            self.todo_content = todo
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def suggest_next_task(self):
        """Предлагает следующую задачу из TODO"""
        if not self.todo_content:
            print("❌ Нет TODO.md")
            return
        
        prompt = f"""На основе TODO.md:

{self.todo_content[:1000]}

Какую задачу делать СЛЕДУЮЩЕЙ?
Почему именно её?
Какие файлы нужно создать/изменить?

Ответь кратко: 1 конкретная задача."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            suggestion = response['message']['content']
            
            print(f"\n🎯 СЛЕДУЮЩАЯ ЗАДАЧА:")
            print("="*40)
            print(suggestion)
            print("="*40)
            
            # Сохраняем предложение
            next_file = os.path.join(self.project_path, '_ai_next_task.txt')
            with open(next_file, 'w', encoding='utf-8') as f:
                f.write(f"Следующая задача ({datetime.now()}):\n")
                f.write(suggestion)
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def update_todo(self):
        """Обновляет TODO.md отмечая выполненные задачи"""
        if not self.todo_content:
            return
        
        prompt = f"""Анализируя файлы проекта:
{chr(10).join([f"- {os.path.basename(f)}" for f in self.files[:30]])}

И текущий TODO.md:
{self.todo_content[:1500]}

Какие задачи УЖЕ ВЫПОЛНЕНЫ (исходя из файлов)?
Отметь их как [x].
Обнови TODO.md."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            updated = response['message']['content']
            
            todo_file = os.path.join(self.project_path, 'TODO.md')
            with open(todo_file, 'w', encoding='utf-8') as f:
                f.write(f"# TODO: {self.project_name} (обновлено {datetime.now()})\n\n")
                f.write(updated)
            
            print(f"✅ TODO.md обновлен")
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def run(self):
        """Запускает анализ"""
        self.scan_project()
        
        print("\n" + "="*60)
        print("ВЫБЕРИТЕ ДЕЙСТВИЕ:")
        print("1. Анализ по существующему TODO.md")
        print("2. Создать TODO.md (если нет)")
        print("3. Предложить следующую задачу")
        print("4. Обновить TODO (отметить выполненное)")
        print("5. Всё вместе")
        print("="*60)
        
        choice = input("\n👉 Выбор: ").strip()
        
        if choice == '1':
            self.analyze_with_todo()
        elif choice == '2':
            self.create_todo_from_analysis()
        elif choice == '3':
            self.suggest_next_task()
        elif choice == '4':
            self.update_todo()
        elif choice == '5':
            if not self.todo_content:
                self.create_todo_from_analysis()
            self.analyze_with_todo()
            self.suggest_next_task()
            self.update_todo()
        else:
            print("❌ Неверный выбор")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        project_path = sys.argv[1]
    else:
        project_path = input("Введите путь к проекту: ").strip()
    
    if os.path.exists(project_path):
        analyzer = ProjectAnalyzer(project_path)
        analyzer.run()
    else:
        print("❌ Путь не существует")
