#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timedelta
import ollama
import time

class TrendReporter:
    """Отчеты о новых технологиях и трендах"""
    
    def __init__(self, model="llama3.2"):
        self.model = model
        self.reports_dir = os.path.expanduser("~/AIM/trend_reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        self.trend_history = []
        
    def get_github_trends(self, language=None):
        """Получает тренды с GitHub"""
        trends = []
        try:
            # GitHub trending API (неофициальный)
            url = "https://api.github.com/search/repositories"
            params = {
                'q': 'stars:>100',
                'sort': 'stars',
                'order': 'desc',
                'per_page': 10
            }
            if language:
                params['q'] += f'+language:{language}'
            
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                for repo in data.get('items', [])[:10]:
                    trends.append({
                        'name': repo['name'],
                        'full_name': repo['full_name'],
                        'description': repo['description'],
                        'url': repo['html_url'],
                        'stars': repo['stargazers_count'],
                        'language': repo['language'],
                        'created_at': repo['created_at'],
                        'source': 'github'
                    })
        except Exception as e:
            print(f"⚠️ Ошибка получения GitHub трендов: {e}")
        return trends
    
    def get_pypi_trends(self):
        """Получает популярные пакеты PyPI"""
        trends = []
        try:
            # Используем статистику скачиваний
            url = "https://pypistats.org/api/packages/top"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                for pkg in data.get('data', [])[:10]:
                    trends.append({
                        'name': pkg['package'],
                        'downloads': pkg.get('downloads', 0),
                        'source': 'pypi'
                    })
        except:
            # Fallback на статические данные
            popular = ['requests', 'numpy', 'pandas', 'matplotlib', 'flask', 'django', 'fastapi', 'pytest', 'scipy', 'tensorflow']
            for pkg in popular:
                trends.append({
                    'name': pkg,
                    'source': 'pypi',
                    'note': 'popular'
                })
        return trends
    
    def get_tech_news(self):
        """Получает новости технологий"""
        news = []
        sources = [
            "https://hn.algolia.com/api/v1/search?tags=front_page",
            "https://www.reddit.com/r/technology/hot.json?limit=5"
        ]
        
        for url in sources:
            try:
                response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
                if response.status_code == 200:
                    data = response.json()
                    if 'hits' in data:  # Hacker News
                        for item in data['hits'][:5]:
                            news.append({
                                'title': item['title'],
                                'url': item['url'],
                                'points': item.get('points', 0),
                                'source': 'hackernews'
                            })
                    elif 'data' in data:  # Reddit
                        for item in data['data']['children'][:5]:
                            news.append({
                                'title': item['data']['title'],
                                'url': item['data']['url'],
                                'score': item['data']['score'],
                                'source': 'reddit'
                            })
            except:
                pass
        return news
    
    def analyze_project_trends(self, project_name, project_files):
        """Анализирует тренды для конкретного проекта"""
        
        # Определяем язык проекта
        language = None
        for f in project_files:
            if f.endswith('.py'):
                language = 'python'
                break
            elif f.endswith('.js'):
                language = 'javascript'
                break
            elif f.endswith('.java'):
                language = 'java'
                break
        
        # Получаем тренды
        github_trends = self.get_github_trends(language)
        pypi_trends = self.get_pypi_trends()
        tech_news = self.get_tech_news()
        
        # Формируем отчет
        report = []
        report.append(f"# 📈 ОТЧЕТ О ТРЕНДАХ ДЛЯ: {project_name}")
        report.append(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("="*60)
        
        if github_trends:
            report.append("\n## 🔥 GitHub Тренды")
            for t in github_trends[:5]:
                report.append(f"\n### [{t['name']}]({t['url']})")
                report.append(f"  ⭐ {t['stars']} звезд")
                if t.get('description'):
                    report.append(f"  📝 {t['description']}")
                if t.get('language'):
                    report.append(f"  🖥️ {t['language']}")
        
        if pypi_trends:
            report.append("\n## 📦 Популярные PyPI пакеты")
            for t in pypi_trends[:5]:
                report.append(f"  • {t['name']}")
        
        if tech_news:
            report.append("\n## 📰 Новости технологий")
            for n in tech_news[:5]:
                report.append(f"  • [{n['title']}]({n['url']})")
        
        # AI анализ трендов
        prompt = f"""Проект: {project_name}
Язык: {language or 'неизвестен'}

GitHub тренды: {[t['name'] for t in github_trends[:3]]}
Популярные пакеты: {[t['name'] for t in pypi_trends[:3]]}

Дай рекомендации:
1. Какие технологии стоит использовать?
2. Какие тренды актуальны для проекта?
3. Что нового появилось в экосистеме?
4. Советы по развитию проекта"""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            analysis = response['message']['content']
            
            report.append("\n## 🤖 AI АНАЛИЗ ТРЕНДОВ")
            report.append("-"*40)
            report.append(analysis)
        except Exception as e:
            report.append(f"\n❌ Ошибка AI анализа: {e}")
        
        return '\n'.join(report)
    
    def generate_weekly_trend_report(self):
        """Еженедельный отчет о трендах"""
        
        # Собираем данные
        github = self.get_github_trends()
        pypi = self.get_pypi_trends()
        news = self.get_tech_news()
        
        report = []
        report.append("# 📊 ЕЖЕНЕДЕЛЬНЫЙ ОТЧЕТ О ТЕХНОЛОГИЯХ")
        report.append(f"Неделя: {datetime.now().strftime('%Y-%m-%d')}")
        report.append("="*60)
        
        report.append("\n## 🔥 ТОП-10 GitHub репозиториев")
        for i, r in enumerate(github[:10], 1):
            report.append(f"{i}. [{r['name']}]({r['url']}) - ⭐ {r['stars']}")
            if r.get('description'):
                report.append(f"   {r['description']}")
        
        report.append("\n## 📦 ТОП-10 PyPI пакетов")
        for i, p in enumerate(pypi[:10], 1):
            report.append(f"{i}. {p['name']}")
        
        report.append("\n## 📰 ТОП новостей")
        for n in news[:10]:
            report.append(f"• [{n['title']}]({n['url']})")
        
        # AI анализ трендов
        prompt = f"""Проанализируй тренды этой недели:

GitHub: {[r['name'] for r in github[:5]]}
PyPI: {[p['name'] for p in pypi[:5]]}

Какие основные тенденции?
Что будет популярно в ближайшее время?
Какие технологии на спаде?
Дай прогноз на следующую неделю."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            analysis = response['message']['content']
            report.append("\n## 🔮 AI ПРОГНОЗ")
            report.append("-"*40)
            report.append(analysis)
        except:
            pass
        
        # Сохраняем отчет
        timestamp = datetime.now().strftime('%Y%m%d')
        report_file = os.path.join(self.reports_dir, f"weekly_trends_{timestamp}.md")
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))
        
        return report_file, '\n'.join(report)
    
    def get_technology_stack_recommendation(self, project_type):
        """Рекомендует стек технологий для типа проекта"""
        
        stacks = {
            'python': {
                'web': ['FastAPI', 'Django', 'Flask'],
                'data': ['pandas', 'numpy', 'matplotlib', 'scikit-learn'],
                'ml': ['tensorflow', 'pytorch', 'transformers'],
                'automation': ['selenium', 'playwright', 'requests']
            },
            'javascript': {
                'web': ['react', 'vue', 'angular', 'next.js'],
                'backend': ['node.js', 'express', 'nestjs'],
                'mobile': ['react-native', 'expo']
            }
        }
        
        prompt = f"""Тип проекта: {project_type}

Рекомендуй современный технологический стек.
Укажи основные библиотеки и фреймворки.
Объясни почему именно их стоит использовать."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            return response['message']['content']
        except:
            return "Не удалось получить рекомендации"
    
    def save_trend_report(self, project_name, report):
        """Сохраняет отчет в файл"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{project_name}_trends_{timestamp}.md"
        filepath = os.path.join(self.reports_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(report)
        
        return filepath

# Тестирование
if __name__ == "__main__":
    reporter = TrendReporter()
    
    # Тест еженедельного отчета
    file, report = reporter.generate_weekly_trend_report()
    print(report[:500])
    print(f"\n✅ Отчет сохранен: {file}")
