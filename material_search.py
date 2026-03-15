#!/usr/bin/env python3
import os
import json
import time
import requests
from datetime import datetime
import ollama
import threading

class MaterialSearcher:
    def __init__(self, model="llama3.2"):
        self.model = model
        self.results_dir = os.path.expanduser("~/AIM/search_results")
        os.makedirs(self.results_dir, exist_ok=True)
        self.search_history = []
    
    def generate_search_queries(self, project_name, project_files):
        prompt = f"""Проект: {project_name}
Файлы: {project_files[:20]}

Сгенерируй 5 поисковых запросов для поиска материалов по теме этого проекта.
Каждый запрос на отдельной строке, без номеров."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            queries = response['message']['content'].strip().split('\n')
            return [q.strip() for q in queries if q.strip()]
        except Exception as e:
            print(f"❌ Ошибка генерации запросов: {e}")
            return [project_name]
    
    def search_github(self, query, num_results=5):
        results = []
        try:
            url = f"https://api.github.com/search/repositories?q={query}&sort=stars"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                for item in data.get('items', [])[:num_results]:
                    results.append({
                        'title': item['name'],
                        'link': item['html_url'],
                        'snippet': item['description'],
                        'stars': item['stargazers_count'],
                        'source': 'github'
                    })
        except Exception as e:
            print(f"⚠️ Ошибка GitHub: {e}")
        return results
    
    def search_pypi(self, query, num_results=5):
        results = []
        try:
            url = f"https://pypi.org/pypi/{query}/json"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                results.append({
                    'title': data['info']['name'],
                    'link': f"https://pypi.org/project/{data['info']['name']}",
                    'snippet': data['info']['summary'],
                    'version': data['info']['version'],
                    'source': 'pypi'
                })
        except:
            pass
        return results
    
    def search_all(self, query):
        all_results = []
        all_results.extend(self.search_github(query))
        all_results.extend(self.search_pypi(query))
        return all_results
    
    def analyze_results(self, results, project_name):
        if not results:
            return "Ничего не найдено"
        
        summary = []
        for r in results[:10]:
            summary.append(f"- {r['title']} ({r['source']})")
        
        prompt = f"""Проанализируй найденные материалы для проекта '{project_name}'.

Найденные материалы:
{chr(10).join(summary)}

Что полезного можно взять для проекта?
Дай краткие рекомендации."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            return response['message']['content']
        except Exception as e:
            return f"Ошибка анализа: {e}"
    
    def search_for_project(self, project_name, project_files):
        print(f"\n🔍 ПОИСК МАТЕРИАЛОВ ДЛЯ: {project_name}")
        print("="*50)
        
        queries = self.generate_search_queries(project_name, project_files)
        print(f"\n📝 Запросы:")
        for q in queries:
            print(f"  • {q}")
        
        all_results = []
        for query in queries:
            results = self.search_all(query)
            all_results.extend(results)
        
        unique_results = []
        seen = set()
        for r in all_results:
            if r['link'] not in seen:
                seen.add(r['link'])
                unique_results.append(r)
        
        print(f"\n📊 Найдено: {len(unique_results)} результатов")
        
        if unique_results:
            analysis = self.analyze_results(unique_results, project_name)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            result_file = os.path.join(self.results_dir, f"{project_name}_{timestamp}.json")
            
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'project': project_name,
                    'timestamp': timestamp,
                    'queries': queries,
                    'results': unique_results[:20],
                    'analysis': analysis
                }, f, indent=2, ensure_ascii=False)
            
            print(f"\n✅ Результаты сохранены: {result_file}")
            print("\n📋 АНАЛИЗ:")
            print("-"*40)
            print(analysis)
        
        self.search_history.append({
            'project': project_name,
            'timestamp': datetime.now().isoformat(),
            'results_count': len(unique_results)
        })
        
        return unique_results

class DailySearcher:
    def __init__(self, searcher):
        self.searcher = searcher
        self.running = False
        self.thread = None
        self.last_search = {}
    
    def start_daily_search(self, projects, hour=9):
        self.running = True
        self.thread = threading.Thread(target=self._daily_loop, args=(projects, hour), daemon=True)
        self.thread.start()
        print(f"⏰ Ежедневный поиск запущен (в {hour}:00)")
    
    def stop_daily_search(self):
        self.running = False
        print("⏰ Ежедневный поиск остановлен")
    
    def _daily_loop(self, projects, hour):
        while self.running:
            now = datetime.now()
            if now.hour == hour:
                for name, data in projects.items():
                    last = self.last_search.get(name)
                    if last:
                        last_date = datetime.fromisoformat(last)
                        if last_date.date() == now.date():
                            continue
                    print(f"\n📅 Поиск для: {name}")
                    self.searcher.search_for_project(name, data['files'])
                    self.last_search[name] = now.isoformat()
            time.sleep(3600)

if __name__ == "__main__":
    searcher = MaterialSearcher()
    test_files = ['main.py', 'utils.py', 'README.md']
    searcher.search_for_project("Test Project", test_files)
