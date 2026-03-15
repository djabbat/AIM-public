#!/usr/bin/env python3
import ollama
from datetime import datetime

class BaseAgent:
    """Базовый класс для всех агентов"""
    def __init__(self, name, role, model="llama3.2"):
        self.name = name
        self.role = role
        self.model = model
        self.memory = []
        self.tasks_completed = 0
        
    def think(self, task):
        """Агент думает над задачей"""
        prompt = f"""Ты {self.name} - {self.role}.
        
Задача: {task}

Дай конкретный ответ."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'system', 'content': f'Ты {self.name} - {self.role}'},
                {'role': 'user', 'content': prompt}
            ])
            
            answer = response['message']['content']
            
            self.memory.append({
                'task': task,
                'answer': answer,
                'time': datetime.now().isoformat()
            })
            self.tasks_completed += 1
            
            return answer
        except Exception as e:
            return f"❌ Ошибка: {e}"
    
    def get_stats(self):
        return f"{self.name}: {self.tasks_completed} задач"

class LinguistAgent(BaseAgent):
    """Агент-лингвист для работы с языками"""
    def __init__(self, model="llama3.2"):
        super().__init__(
            "🌐 Лингвист",
            "эксперт по языкам, переводу между русским, английским, казахским и грузинским",
            model
        )
        self.languages = ['ru', 'en', 'kk', 'ka']
    
    def detect_language(self, text):
        """Определяет язык текста"""
        prompt = f"Определи язык этого текста (только код языка: ru/en/kk/ka): {text[:200]}"
        response = self.think(prompt)
        for lang in self.languages:
            if lang in response.lower():
                return lang
        return 'ru'
    
    def translate(self, text, target_lang):
        """Переводит текст"""
        prompt = f"Переведи на {target_lang}: {text}"
        return self.think(prompt)

class ProgrammerAgent(BaseAgent):
    """Агент-программист для кода"""
    def __init__(self, model="llama3.2"):
        super().__init__(
            "💻 Программист",
            "эксперт по написанию кода на Python, JavaScript и других языках",
            model
        )
    
    def write_code(self, task):
        """Пишет код"""
        prompt = f"""Напиши код для задачи: {task}
Только код, без объяснений."""
        return self.think(prompt)
    
    def review_code(self, code):
        """Проверяет код"""
        prompt = f"Проверь этот код и найди ошибки:\n{code}"
        return self.think(prompt)

class AnalystAgent(BaseAgent):
    """Агент-аналитик для данных"""
    def __init__(self, model="llama3.2"):
        super().__init__(
            "📊 Аналитик",
            "специалист по анализу данных и проектов",
            model
        )
    
    def analyze_project(self, project_name, files):
        """Анализирует проект"""
        prompt = f"""Проект: {project_name}
Файлы: {files[:20]}

Тип проекта?
Что уже сделано?
Что нужно сделать?
Риски?"""
        return self.think(prompt)

class ArchitectAgent(BaseAgent):
    """Агент-архитектор для структуры"""
    def __init__(self, model="llama3.2"):
        super().__init__(
            "🏗️ Архитектор",
            "специалист по структуре проектов и архитектуре",
            model
        )
    
    def suggest_structure(self, project_name, project_type):
        """Предлагает структуру проекта"""
        prompt = f"""Проект: {project_name}
Тип: {project_type}

Предложи структуру папок и файлов."""
        return self.think(prompt)

class TesterAgent(BaseAgent):
    """Агент-тестировщик"""
    def __init__(self, model="llama3.2"):
        super().__init__(
            "🧪 Тестировщик",
            "специалист по тестированию и качеству кода",
            model
        )
    
    def create_tests(self, code):
        """Создает тесты"""
        prompt = f"Напиши тесты для этого кода:\n{code}"
        return self.think(prompt)

class Orchestrator:
    """Главный оркестратор - управляет всеми агентами"""
    def __init__(self, model="llama3.2"):
        self.model = model
        self.agents = {}
        self.task_history = []
        
        print("\n🚀 СОЗДАНИЕ МНОГОАГЕНТНОЙ СИСТЕМЫ")
        print("="*50)
        
        # Создаем всех агентов
        self.create_agents()
        
        print(f"✅ Создано агентов: {len(self.agents)}")
        print("="*50)
    
    def create_agents(self):
        """Создает всех агентов"""
        self.agents['linguist'] = LinguistAgent(self.model)
        self.agents['programmer'] = ProgrammerAgent(self.model)
        self.agents['analyst'] = AnalystAgent(self.model)
        self.agents['architect'] = ArchitectAgent(self.model)
        self.agents['tester'] = TesterAgent(self.model)
        
        # Добавляем себя как агента для общих задач
        self.agents['orchestrator'] = BaseAgent(
            "🎯 Оркестратор",
            "координатор, распределяющий задачи между агентами",
            self.model
        )
    
    def delegate(self, task):
        """Распределяет задачу между агентами"""
        print(f"\n📋 Задача: {task}")
        print("-"*40)
        
        # Определяем тип задачи
        task_lower = task.lower()
        
        if any(word in task_lower for word in ['переведи', 'язык', 'translate', 'language']):
            agent = self.agents['linguist']
        elif any(word in task_lower for word in ['код', 'напиши функцию', 'программа', 'code']):
            agent = self.agents['programmer']
        elif any(word in task_lower for word in ['анализ', 'проект', 'оцени', 'analyze']):
            agent = self.agents['analyst']
        elif any(word in task_lower for word in ['структура', 'архитектура', 'организуй']):
            agent = self.agents['architect']
        elif any(word in task_lower for word in ['тест', 'проверь', 'quality']):
            agent = self.agents['tester']
        else:
            agent = self.agents['orchestrator']
        
        print(f"🤖 Выбран агент: {agent.name}")
        
        # Агент выполняет задачу
        result = agent.think(task)
        
        # Сохраняем в историю
        self.task_history.append({
            'task': task,
            'agent': agent.name,
            'result': result[:200],
            'time': datetime.now().isoformat()
        })
        
        return result
    
    def stats(self):
        """Показывает статистику агентов"""
        print("\n📊 СТАТИСТИКА АГЕНТОВ")
        print("="*40)
        for agent in self.agents.values():
            print(f"  {agent.get_stats()}")
        print(f"  Всего задач: {len(self.task_history)}")
    
    def collaborate(self, task, agents_needed):
        """Несколько агентов работают вместе"""
        print(f"\n🤝 КОЛЛАБОРАЦИЯ АГЕНТОВ")
        print(f"Задача: {task}")
        print(f"Агенты: {', '.join(agents_needed)}")
        print("-"*40)
        
        results = {}
        for agent_name in agents_needed:
            if agent_name in self.agents:
                print(f"\n🤔 {self.agents[agent_name].name} работает...")
                results[agent_name] = self.agents[agent_name].think(task)
        
        # Оркестратор собирает результаты
        summary = self.agents['orchestrator'].think(
            f"Собери результаты работы агентов в один ответ.\n"
            f"Задача: {task}\n"
            f"Результаты: {results}"
        )
        
        return summary

# Тест системы
if __name__ == "__main__":
    ai = Orchestrator()
    
    while True:
        print("\n" + "="*50)
        print("🤖 МНОГОАГЕНТНАЯ СИСТЕМА")
        print("="*50)
        print("1. Выполнить задачу")
        print("2. Статистика агентов")
        print("3. Коллаборация агентов")
        print("4. Выход")
        print("="*50)
        
        choice = input("\n👉 Выбор: ").strip()
        
        if choice == '1':
            task = input("Задача: ").strip()
            result = ai.delegate(task)
            print(f"\n✅ Результат:\n{result}")
        
        elif choice == '2':
            ai.stats()
        
        elif choice == '3':
            task = input("Задача для коллаборации: ").strip()
            print("Доступные агенты: linguist, programmer, analyst, architect, tester")
            agents = input("Агенты (через запятую): ").strip().split(',')
            agents = [a.strip() for a in agents]
            result = ai.collaborate(task, agents)
            print(f"\n✅ Результат:\n{result}")
        
        elif choice == '4':
            print("👋 До свидания!")
            break
        
        input("\nНажмите Enter для продолжения...")
