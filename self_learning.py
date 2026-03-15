#!/usr/bin/env python3
import os
import json
import pickle
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import ollama

class LearningSystem:
    """Система самообучения на основе опыта"""
    
    def __init__(self, model="llama3.2"):
        self.model = model
        self.learning_dir = os.path.expanduser("~/AIM/learning")
        os.makedirs(self.learning_dir, exist_ok=True)
        
        # База знаний
        self.knowledge_base = self.load_knowledge()
        self.patterns = self.load_patterns()
        self.success_stories = self.load_successes()
        self.mistakes = self.load_mistakes()
        self.user_preferences = self.load_preferences()
        
        # Статистика обучения
        self.stats = {
            'total_learnings': 0,
            'patterns_found': 0,
            'success_rate': 0,
            'adaptations': 0
        }
    
    def load_knowledge(self):
        """Загружает базу знаний"""
        kb_file = os.path.join(self.learning_dir, 'knowledge.json')
        if os.path.exists(kb_file):
            with open(kb_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'facts': [], 'concepts': [], 'relations': []}
    
    def save_knowledge(self):
        """Сохраняет базу знаний"""
        kb_file = os.path.join(self.learning_dir, 'knowledge.json')
        with open(kb_file, 'w', encoding='utf-8') as f:
            json.dump(self.knowledge_base, f, indent=2)
    
    def load_patterns(self):
        """Загружает паттерны проектов"""
        patterns_file = os.path.join(self.learning_dir, 'patterns.json')
        if os.path.exists(patterns_file):
            with open(patterns_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'project_types': {}, 'code_patterns': [], 'error_patterns': []}
    
    def save_patterns(self):
        """Сохраняет паттерны"""
        patterns_file = os.path.join(self.learning_dir, 'patterns.json')
        with open(patterns_file, 'w', encoding='utf-8') as f:
            json.dump(self.patterns, f, indent=2)
    
    def load_successes(self):
        """Загружает успешные решения"""
        success_file = os.path.join(self.learning_dir, 'successes.json')
        if os.path.exists(success_file):
            with open(success_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def save_successes(self):
        """Сохраняет успешные решения"""
        success_file = os.path.join(self.learning_dir, 'successes.json')
        with open(success_file, 'w', encoding='utf-8') as f:
            json.dump(self.success_stories[-100:], f, indent=2)
    
    def load_mistakes(self):
        """Загружает ошибки"""
        mistakes_file = os.path.join(self.learning_dir, 'mistakes.json')
        if os.path.exists(mistakes_file):
            with open(mistakes_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def save_mistakes(self):
        """Сохраняет ошибки"""
        mistakes_file = os.path.join(self.learning_dir, 'mistakes.json')
        with open(mistakes_file, 'w', encoding='utf-8') as f:
            json.dump(self.mistakes[-100:], f, indent=2)
    
    def load_preferences(self):
        """Загружает предпочтения пользователя"""
        prefs_file = os.path.join(self.learning_dir, 'preferences.json')
        if os.path.exists(prefs_file):
            with open(prefs_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'language': 'ru', 'style': 'detailed', 'favorites': []}
    
    def save_preferences(self):
        """Сохраняет предпочтения"""
        prefs_file = os.path.join(self.learning_dir, 'preferences.json')
        with open(prefs_file, 'w', encoding='utf-8') as f:
            json.dump(self.user_preferences, f, indent=2)
    
    def learn_from_project(self, project_name, project_data, analysis_result):
        """Учится на проекте"""
        
        # Извлекаем паттерны
        project_type = self.detect_project_type(project_data['files'])
        
        # Сохраняем паттерн
        if project_type not in self.patterns['project_types']:
            self.patterns['project_types'][project_type] = []
        
        self.patterns['project_types'][project_type].append({
            'name': project_name,
            'files': project_data['files'][:10],
            'timestamp': datetime.now().isoformat()
        })
        
        # Анализируем результат
        self.analyze_learning_result(project_name, analysis_result)
        
        self.stats['total_learnings'] += 1
        self.stats['patterns_found'] = len(self.patterns['project_types'])
        self.save_patterns()
    
    def detect_project_type(self, files):
        """Определяет тип проекта"""
        py_files = [f for f in files if f.endswith('.py')]
        js_files = [f for f in files if f.endswith('.js')]
        html_files = [f for f in files if f.endswith(('.html', '.htm'))]
        
        if len(py_files) > len(js_files) + len(html_files):
            return 'python'
        elif len(js_files) > 0:
            return 'javascript'
        elif len(html_files) > 0:
            return 'html'
        else:
            return 'other'
    
    def analyze_learning_result(self, project_name, result):
        """Анализирует результат обучения"""
        
        # Оцениваем успешность
        success_indicators = ['✅', 'успешно', 'completed', 'done']
        is_success = any(ind in str(result) for ind in success_indicators)
        
        if is_success:
            self.success_stories.append({
                'project': project_name,
                'result': str(result)[:200],
                'timestamp': datetime.now().isoformat()
            })
        else:
            self.mistakes.append({
                'project': project_name,
                'error': str(result)[:200],
                'timestamp': datetime.now().isoformat()
            })
        
        # Обновляем статистику
        total = len(self.success_stories) + len(self.mistakes)
        if total > 0:
            self.stats['success_rate'] = len(self.success_stories) / total * 100
    
    def learn_from_mistake(self, mistake):
        """Учится на ошибке"""
        
        prompt = f"""Проанализируй эту ошибку:

{mistake}

Как можно было её избежать?
Какой паттерн можно извлечь?
Что сделать, чтобы не повторять?"""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            lesson = response['message']['content']
            
            # Сохраняем урок
            self.patterns['error_patterns'].append({
                'error': mistake[:100],
                'lesson': lesson,
                'timestamp': datetime.now().isoformat()
            })
            
            self.save_patterns()
            return lesson
        except:
            return None
    
    def adapt_to_user(self, feedback):
        """Адаптируется под пользователя"""
        
        # Анализируем обратную связь
        if 'короче' in feedback.lower():
            self.user_preferences['style'] = 'concise'
        elif 'подробнее' in feedback.lower():
            self.user_preferences['style'] = 'detailed'
        
        # Запоминаем предпочтения
        self.save_preferences()
        self.stats['adaptations'] += 1
    
    def get_recommendations(self, project_type):
        """Получает рекомендации на основе прошлого опыта"""
        
        similar_projects = self.patterns['project_types'].get(project_type, [])
        
        if not similar_projects:
            return "Нет похожих проектов в истории"
        
        prompt = f"""На основе {len(similar_projects)} похожих проектов:

{chr(10).join([f"- {p['name']}: {p['files'][:3]}" for p in similar_projects[-3:]])}

Дай рекомендации для нового проекта этого типа."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            return response['message']['content']
        except:
            return "Не удалось получить рекомендации"
    
    def improve_algorithm(self, algorithm_name, performance_data):
        """Улучшает алгоритм на основе данных"""
        
        self.knowledge_base['facts'].append({
            'algorithm': algorithm_name,
            'performance': performance_data,
            'timestamp': datetime.now().isoformat()
        })
        
        # Анализируем производительность
        if performance_data.get('score', 0) < 50:
            # Нужно улучшение
            prompt = f"""Алгоритм {algorithm_name} показывает низкую производительность.
Данные: {performance_data}

Как можно улучшить?"""
            
            try:
                response = ollama.chat(model=self.model, messages=[
                    {'role': 'user', 'content': prompt}
                ])
                return response['message']['content']
            except:
                pass
        
        self.save_knowledge()
        return None
    
    def get_learning_stats(self):
        """Статистика обучения"""
        
        stats = []
        stats.append("\n📚 СТАТИСТИКА ОБУЧЕНИЯ")
        stats.append("="*40)
        stats.append(f"Всего обучений: {self.stats['total_learnings']}")
        stats.append(f"Найдено паттернов: {self.stats['patterns_found']}")
        stats.append(f"Успешность: {self.stats['success_rate']:.1f}%")
        stats.append(f"Адаптаций: {self.stats['adaptations']}")
        stats.append(f"\n📊 БАЗА ЗНАНИЙ:")
        stats.append(f"  Фактов: {len(self.knowledge_base['facts'])}")
        stats.append(f"  Паттернов проектов: {len(self.patterns['project_types'])}")
        stats.append(f"  Паттернов ошибок: {len(self.patterns['error_patterns'])}")
        stats.append(f"  Успешных решений: {len(self.success_stories)}")
        stats.append(f"  Ошибок: {len(self.mistakes)}")
        
        return '\n'.join(stats)
    
    def get_improvement_suggestions(self):
        """Предложения по улучшению системы"""
        
        if len(self.mistakes) < 5:
            return "Недостаточно данных для предложений"
        
        recent_mistakes = self.mistakes[-5:]
        
        prompt = f"""На основе последних ошибок:

{chr(10).join([f"- {m['error']}" for m in recent_mistakes])}

Какие улучшения можно внести в систему?
Дай 3 конкретных предложения."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            return response['message']['content']
        except:
            return "Не удалось сгенерировать предложения"

class MetaLearner:
    """Мета-обучение - учится учиться"""
    
    def __init__(self, learner):
        self.learner = learner
        self.learning_strategies = []
        self.strategy_performance = defaultdict(list)
    
    def evaluate_strategy(self, strategy, result):
        """Оценивает эффективность стратегии"""
        self.strategy_performance[strategy].append({
            'result': result,
            'time': datetime.now().isoformat()
        })
    
    def get_best_strategy(self, context):
        """Выбирает лучшую стратегию для контекста"""
        
        if not self.strategy_performance:
            return None
        
        # Находим стратегию с лучшими результатами
        best_strategy = None
        best_score = 0
        
        for strategy, performances in self.strategy_performance.items():
            recent = performances[-5:]
            if recent:
                avg_score = sum(p['result'] for p in recent) / len(recent)
                if avg_score > best_score:
                    best_score = avg_score
                    best_strategy = strategy
        
        return best_strategy
    
    def learn_new_strategy(self, context):
        """Изучает новую стратегию"""
        
        prompt = f"""Контекст: {context}

Предложи новую стратегию обучения для этого контекста.
Опиши шаги и ожидаемые результаты."""
        
        try:
            response = ollama.chat(model=self.learner.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            new_strategy = response['message']['content']
            self.learning_strategies.append({
                'strategy': new_strategy,
                'context': context,
                'timestamp': datetime.now().isoformat()
            })
            
            return new_strategy
        except:
            return None

# Тестирование
if __name__ == "__main__":
    learner = LearningSystem()
    
    # Тест обучения
    test_project = {
        'files': ['main.py', 'utils.py', 'README.md']
    }
    learner.learn_from_project("Test Project", test_project, "✅ Успешно завершено")
    
    print(learner.get_learning_stats())
    
    # Тест рекомендаций
    rec = learner.get_recommendations('python')
    print(f"\n📝 Рекомендации:\n{rec}")
