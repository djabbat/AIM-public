import ollama
from datetime import datetime

class MultiLangSystem:
    def __init__(self):
        self.model = "llama3.2"
        self.languages = {
            'ru': '🇷🇺 Русский',
            'en': '🇬🇧 Английский',
            'kk': '🇰🇿 Казахский',
            'ka': '🇬🇪 Грузинский'
        }
        print("\n🌐 МУЛЬТИЯЗЫЧНАЯ AI СИСТЕМА")
        print("="*40)
        for lang in self.languages.values():
            print(f"  {lang}")
        print("="*40)
    
    def chat(self):
        while True:
            print("\n" + "-"*40)
            query = input("Вы (на любом языке): ").strip()
            
            if query.lower() in ['/exit', 'выход', 'шығу', 'გასვლა']:
                break
            
            response = ollama.chat(model=self.model, messages=[
                {'role': 'system', 'content': 'Отвечай на том же языке, на котором задан вопрос'},
                {'role': 'user', 'content': query}
            ])
            
            print(f"\n🤖 AI: {response['message']['content']}")

if __name__ == "__main__":
    MultiLangSystem().chat()
