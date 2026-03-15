import ollama
from datetime import datetime

class MultilingualAgent:
    def __init__(self, name, role, model="llama3.2"):
        self.name = name
        self.role = role
        self.model = model
        self.memory = []
        self.languages = {
            'ru': '🇷🇺 русский',
            'en': '🇬🇧 английский',
            'kk': '🇰🇿 казахский',
            'ka': '🇬🇪 грузинский'
        }
        print(f"  ✅ Создан агент: {name}")
    
    def think(self, task):
        print(f"  🤔 {self.name} думает...")
        
        prompt = f"""Ты {self.name} - {self.role}
        
Задача: {task}

Ответь на том же языке, на котором задан вопрос."""
        
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
        
        return answer
