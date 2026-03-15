#!/usr/bin/env python3
import os
import json
from datetime import datetime
import ollama

class FeedbackSystem:
    """Система сбора и анализа обратной связи"""
    
    def __init__(self, model="llama3.2"):
        self.model = model
        self.feedback_dir = os.path.expanduser("~/AIM/feedback")
        os.makedirs(self.feedback_dir, exist_ok=True)
        
        # База обратной связи
        self.feedback = self.load_feedback()
        self.suggestions = self.load_suggestions()
        self.ratings = self.load_ratings()
        self.improvements = self.load_improvements()
        
        # Статистика
        self.stats = {
            'total_feedback': 0,
            'avg_rating': 0,
            'implemented': 0,
            'pending': 0
        }
        self.update_stats()
    
    def load_feedback(self):
        """Загружает обратную связь"""
        fb_file = os.path.join(self.feedback_dir, 'feedback.json')
        if os.path.exists(fb_file):
            with open(fb_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def save_feedback(self):
        """Сохраняет обратную связь"""
        fb_file = os.path.join(self.feedback_dir, 'feedback.json')
        with open(fb_file, 'w', encoding='utf-8') as f:
            json.dump(self.feedback[-100:], f, indent=2)
    
    def load_suggestions(self):
        """Загружает предложения"""
        sug_file = os.path.join(self.feedback_dir, 'suggestions.json')
        if os.path.exists(sug_file):
            with open(sug_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def save_suggestions(self):
        """Сохраняет предложения"""
        sug_file = os.path.join(self.feedback_dir, 'suggestions.json')
        with open(sug_file, 'w', encoding='utf-8') as f:
            json.dump(self.suggestions[-50:], f, indent=2)
    
    def load_ratings(self):
        """Загружает оценки"""
        rat_file = os.path.join(self.feedback_dir, 'ratings.json')
        if os.path.exists(rat_file):
            with open(rat_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def save_ratings(self):
        """Сохраняет оценки"""
        rat_file = os.path.join(self.feedback_dir, 'ratings.json')
        with open(rat_file, 'w', encoding='utf-8') as f:
            json.dump(self.ratings[-100:], f, indent=2)
    
    def load_improvements(self):
        """Загружает улучшения"""
        imp_file = os.path.join(self.feedback_dir, 'improvements.json')
        if os.path.exists(imp_file):
            with open(imp_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'implemented': [], 'planned': []}
    
    def save_improvements(self):
        """Сохраняет улучшения"""
        imp_file = os.path.join(self.feedback_dir, 'improvements.json')
        with open(imp_file, 'w', encoding='utf-8') as f:
            json.dump(self.improvements, f, indent=2)
    
    def update_stats(self):
        """Обновляет статистику"""
        self.stats['total_feedback'] = len(self.feedback)
        if self.ratings:
            self.stats['avg_rating'] = sum(self.ratings) / len(self.ratings)
        self.stats['implemented'] = len(self.improvements['implemented'])
        self.stats['pending'] = len(self.improvements['planned'])
    
    def add_feedback(self, user, message, context=None):
        """Добавляет обратную связь"""
        feedback_item = {
            'id': len(self.feedback) + 1,
            'user': user,
            'message': message,
            'context': context,
            'timestamp': datetime.now().isoformat(),
            'status': 'new',
            'priority': 'medium'
        }
        self.feedback.append(feedback_item)
        self.save_feedback()
        self.update_stats()
        
        # Анализируем обратную связь
        self.analyze_feedback(feedback_item)
        return feedback_item['id']
    
    def add_rating(self, user, rating, comment=None):
        """Добавляет оценку"""
        rating_item = {
            'user': user,
            'rating': rating,
            'comment': comment,
            'timestamp': datetime.now().isoformat()
        }
        self.ratings.append(rating_item)
        self.save_ratings()
        self.update_stats()
        
        # Анализируем низкие оценки
        if rating < 3:
            self.analyze_low_rating(rating_item)
    
    def add_suggestion(self, user, suggestion, category='feature'):
        """Добавляет предложение"""
        suggestion_item = {
            'id': len(self.suggestions) + 1,
            'user': user,
            'suggestion': suggestion,
            'category': category,
            'timestamp': datetime.now().isoformat(),
            'status': 'pending',
            'votes': 0
        }
        self.suggestions.append(suggestion_item)
        self.save_suggestions()
        
        # Анализируем предложение
        self.analyze_suggestion(suggestion_item)
        return suggestion_item['id']
    
    def vote_suggestion(self, suggestion_id):
        """Голосует за предложение"""
        for s in self.suggestions:
            if s['id'] == suggestion_id:
                s['votes'] = s.get('votes', 0) + 1
                self.save_suggestions()
                return True
        return False
    
    def analyze_feedback(self, feedback):
        """Анализирует обратную связь с помощью AI"""
        
        prompt = f"""Проанализируй обратную связь:

Сообщение: {feedback['message']}
Контекст: {feedback['context']}

Определи:
1. Тип反馈 (проблема/пожелание/вопрос)
2. Срочность (high/medium/low)
3. Возможное решение
4. Приоритет для разработки"""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            analysis = response['message']['content']
            
            # Сохраняем анализ
            feedback['analysis'] = analysis
            if 'high' in analysis.lower():
                feedback['priority'] = 'high'
            
            self.save_feedback()
            
        except:
            pass
    
    def analyze_low_rating(self, rating):
        """Анализирует низкую оценку"""
        
        prompt = f"""Пользователь поставил оценку {rating['rating']}/5.
Комментарий: {rating['comment']}

Почему оценка низкая?
Что нужно улучшить?
Предложи конкретные действия."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            analysis = response['message']['content']
            
            # Создаем задачу на улучшение
            self.improvements['planned'].append({
                'source': 'low_rating',
                'analysis': analysis,
                'rating': rating,
                'timestamp': datetime.now().isoformat()
            })
            self.save_improvements()
            
        except:
            pass
    
    def analyze_suggestion(self, suggestion):
        """Анализирует предложение"""
        
        prompt = f"""Проанализируй предложение пользователя:

{suggestion['suggestion']}

Оцени:
1. Полезность (1-10)
2. Сложность реализации (1-10)
3. Приоритет
4. Стоит ли реализовывать?"""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            
            analysis = response['message']['content']
            suggestion['analysis'] = analysis
            self.save_suggestions()
            
        except:
            pass
    
    def get_feedback_report(self):
        """Отчет по обратной связи"""
        
        report = []
        report.append("\n📊 ОТЧЕТ ПО ОБРАТНОЙ СВЯЗИ")
        report.append("="*50)
        report.append(f"Всего отзывов: {self.stats['total_feedback']}")
        report.append(f"Средняя оценка: {self.stats['avg_rating']:.1f}/5")
        report.append(f"Реализовано улучшений: {self.stats['implemented']}")
        report.append(f"В плане: {self.stats['pending']}")
        
        if self.feedback:
            report.append("\n📝 ПОСЛЕДНИЕ ОТЗЫВЫ:")
            for fb in self.feedback[-5:]:
                report.append(f"  • {fb['timestamp'][:10]}: {fb['message'][:100]}")
        
        if self.suggestions:
            report.append("\n💡 ПОПУЛЯРНЫЕ ПРЕДЛОЖЕНИЯ:")
            top_suggestions = sorted(self.suggestions, key=lambda x: x.get('votes', 0), reverse=True)[:3]
            for s in top_suggestions:
                report.append(f"  • [{s.get('votes', 0)}⭐] {s['suggestion'][:100]}")
        
        return '\n'.join(report)
    
    def get_improvement_plan(self):
        """План улучшений на основе обратной связи"""
        
        if not self.improvements['planned']:
            return "Нет запланированных улучшений"
        
        prompt = f"""На основе обратной связи составь план улучшений:

Последние отзывы: {[f['message'] for f in self.feedback[-3:]]}
Предложения: {[s['suggestion'] for s in self.suggestions[-3:]]}

Составь план из 5 пунктов с приоритетами."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            return response['message']['content']
        except:
            return "Не удалось составить план"
    
    def implement_improvement(self, improvement_id):
        """Отмечает улучшение как реализованное"""
        if 0 <= improvement_id < len(self.improvements['planned']):
            imp = self.improvements['planned'].pop(improvement_id)
            self.improvements['implemented'].append({
                **imp,
                'implemented_at': datetime.now().isoformat()
            })
            self.save_improvements()
            self.update_stats()
            return True
        return False
    
    def get_user_satisfaction(self):
        """Уровень удовлетворенности пользователей"""
        
        if not self.ratings:
            return "Нет данных"
        
        recent = self.ratings[-10:]
        avg = sum(r['rating'] for r in recent) / len(recent)
        
        if avg >= 4.5:
            return "🌟 Отлично"
        elif avg >= 4.0:
            return "😊 Хорошо"
        elif avg >= 3.0:
            return "😐 Удовлетворительно"
        else:
            return "🔧 Требует улучшений"

class UserFeedbackCollector:
    """Сбор обратной связи от пользователя"""
    
    def __init__(self, feedback_system):
        self.feedback = feedback_system
    
    def collect_after_action(self, action, result, user="user"):
        """Собирает обратную связь после действия"""
        
        print(f"\n📝 Оцените результат (1-5):")
        rating = input("Ваша оценка: ").strip()
        
        try:
            rating = int(rating)
            if 1 <= rating <= 5:
                comment = input("Комментарий (enter для пропуска): ").strip()
                self.feedback.add_rating(user, rating, comment)
                
                if rating < 4:
                    improvement = input("Что можно улучшить? ").strip()
                    if improvement:
                        self.feedback.add_suggestion(user, improvement, 'improvement')
        except:
            pass
    
    def collect_suggestion(self, user="user"):
        """Собирает предложения"""
        
        print("\n💡 Есть идея по улучшению?")
        suggestion = input("Ваше предложение: ").strip()
        
        if suggestion:
            category = input("Категория (feature/improvement/bug): ").strip() or 'feature'
            self.feedback.add_suggestion(user, suggestion, category)
            print("✅ Спасибо за предложение!")
    
    def quick_rating(self, action):
        """Быстрая оценка"""
        
        print(f"\n👍 Как вам {action}?")
        print("1. 😐 Плохо")
        print("2. 👌 Нормально")
        print("3. 🌟 Отлично")
        
        choice = input("👉 ").strip()
        rating_map = {'1': 2, '2': 4, '3': 5}
        if choice in rating_map:
            self.feedback.add_rating('user', rating_map[choice], f"Оценка {action}")

# Тестирование
if __name__ == "__main__":
    fs = FeedbackSystem()
    
    # Тест добавления обратной связи
    fs.add_feedback("user1", "Отличная система, но хотелось бы больше примеров", "analysis")
    fs.add_rating("user1", 4, "Хорошо работает")
    fs.add_suggestion("user1", "Добавить поддержку TypeScript", "feature")
    
    print(fs.get_feedback_report())
    print(f"\nУдовлетворенность: {fs.get_user_satisfaction()}")
