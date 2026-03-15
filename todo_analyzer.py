#!/usr/bin/env python3
import os
import sys
import ollama
from datetime import datetime

class TodoAnalyzer:
    def __init__(self, project_path):
        self.project_path = os.path.abspath(project_path)
        self.project_name = os.path.basename(self.project_path)
        self.files = []
        self.todo_content = None
        
        print(f"\n🔍 АНАЛИЗ ПРОЕКТА: {self.project_name}")
        print("="*60)
        
    def scan_files(self):
        """Сканирует файлы проекта"""
        for root, dirs, files in os.walk(self.project_path):
            # Пропускаем служебные папки
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['venv', '__pycache__', 'node_modules']]
            
            for file in files:
                file_path = os.path.join(root, file)
                self.files.append(file_path)
                
                if file.lower() == 'todo.md':
                    self.read_todo(file_path)
        
        print(f"📁 Найдено файлов: {len(self.files)}")
    
    def read_todo(self, filepath):
        """Читает TODO.md"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.todo_content = f.read()
            print(f"✅ Найден TODO.md")
        except:
            pass
    
    def analyze(self):
        """Анализирует проект по TODO.md"""
        self.scan_files()
        
        if not self.todo_content:
            print("\n❌ TODO.md не найден. Создаю...")
            self.create_todo()
            return
        
        print("\n🤖 Анализ по TODO.md...")
        
        prompt = f"""Проект: {self.project_name}

TODO.md:
{self.todo_content[:2000]}

Файлы проекта:
{chr(10).join([f"- {os.path.basename(f)}" for f in self.files[:20]])}

Проанализируй и предложи:
1. Какие задачи из TODO уже выполнены?
2. Какие задачи делать дальше?
3. Конкретные шаги для следующей задачи"""
        
        try:
            response = ollama.chat(model="llama3.2", messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            analysis = response['message']['content']
            
            # Сохраняем
            output = os.path.join(self.project_path, '_todo_analysis.md')
            with open(output, 'w', encoding='utf-8') as f:
                f.write(f"# Анализ задач\n")
                f.write(f"Проект: {self.project_name}\n")
                f.write(f"Дата: {datetime.now()}\n")
                f.write("="*40 + "\n\n")
                f.write(analysis)
            
            print(f"\n✅ Анализ сохранен: {output}")
            print("\n" + "="*40)
            print(analysis[:500] + "...")
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def create_todo(self):
        """Создает TODO.md если его нет"""
        prompt = f"""Проект: {self.project_name}

Файлы:
{chr(10).join([f"- {os.path.basename(f)}" for f in self.files[:20]])}

Создай TODO.md для этого проекта:
- Что уже сделано
- Что нужно сделать
- Приоритеты
- Следующие шаги"""
        
        try:
            response = ollama.chat(model="llama3.2", messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            todo = response['message']['content']
            
            todo_file = os.path.join(self.project_path, 'TODO.md')
            with open(todo_file, 'w', encoding='utf-8') as f:
                f.write(f"# TODO: {self.project_name}\n\n")
                f.write(todo)
            
            print(f"\n✅ TODO.md создан: {todo_file}")
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def next_task(self):
        """Предлагает следующую задачу"""
        if not self.todo_content:
            print("❌ Нет TODO.md")
            return
        
        prompt = f"""Из TODO.md:
{self.todo_content[:1000]}

Какую задачу делать СЛЕДУЮЩЕЙ? Почему?"""
        
        try:
            response = ollama.chat(model="llama3.2", messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            suggestion = response['message']['content']
            
            print("\n🎯 СЛЕДУЮЩАЯ ЗАДАЧА:")
            print("="*40)
            print(suggestion)
            
            # Сохраняем
            with open(os.path.join(self.project_path, '_next_task.txt'), 'w', encoding='utf-8') as f:
                f.write(f"Следующая задача:\n{suggestion}")
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = input("Путь к проекту: ").strip()
    
    if os.path.exists(path):
        analyzer = TodoAnalyzer(path)
        
        print("\n1. Анализ по TODO")
        print("2. Создать TODO")
        print("3. Следующая задача")
        print("4. Всё вместе")
        
        choice = input("\nВыбор: ").strip()
        
        if choice == '1':
            analyzer.analyze()
        elif choice == '2':
            analyzer.scan_files()
            analyzer.create_todo()
        elif choice == '3':
            analyzer.scan_files()
            analyzer.next_task()
        elif choice == '4':
            analyzer.scan_files()
            if not analyzer.todo_content:
                analyzer.create_todo()
            analyzer.analyze()
            analyzer.next_task()
        else:
            print("❌ Неверный выбор")
    else:
        print("❌ Путь не существует")
