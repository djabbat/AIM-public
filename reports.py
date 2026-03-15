#!/usr/bin/env python3
import os
import json
from datetime import datetime, timedelta
from collections import Counter

class ReportGenerator:
    """Генератор отчетов по проектам"""
    
    def __init__(self, projects_path="~/AIM/Patients", memory=None):
        self.projects_path = os.path.expanduser(projects_path)
        self.memory = memory
    
    def generate_daily_report(self):
        """Ежедневный отчет по всем проектам"""
        
        report = []
        report.append("# 📊 ЕЖЕДНЕВНЫЙ ОТЧЕТ AI СИСТЕМЫ")
        report.append(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("="*60)
        
        # Статистика проектов
        if self.memory and hasattr(self.memory, 'get_statistics'):
            stats = self.memory.get_statistics()
            report.append(f"\n## 📁 ПРОЕКТЫ")
            report.append(f"Всего проектов: {stats.get('total_projects', 0)}")
            report.append(f"Всего анализов: {stats.get('total_analyses', 0)}")
            
            if stats.get('projects_by_type'):
                report.append(f"\n### Типы проектов:")
                for ptype, count in stats['projects_by_type'].items():
                    report.append(f"- {ptype}: {count}")
        
        # Недавние изменения
        if self.memory:
            changed = self.memory.get_changed_projects(24)
            if changed:
                report.append(f"\n## 🔄 ИЗМЕНЕНЫ ЗА 24Ч")
                for proj in changed[:10]:
                    report.append(f"- {proj}")
        
        # Сохраняем отчет
        report_path = os.path.expanduser(f"~/AIM/reports/daily_{datetime.now().strftime('%Y%m%d')}.md")
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))
        
        return report_path
    
    def generate_weekly_report(self):
        """Еженедельный отчет"""
        
        week_ago = datetime.now() - timedelta(days=7)
        
        report = []
        report.append("# 📊 ЕЖЕНЕДЕЛЬНЫЙ ОТЧЕТ AI СИСТЕМЫ")
        report.append(f"Неделя: {week_ago.strftime('%Y-%m-%d')} - {datetime.now().strftime('%Y-%m-%d')}")
        report.append("="*60)
        
        # Собираем статистику за неделю
        new_projects = 0
        total_analyses = 0
        
        if self.memory and hasattr(self.memory, 'memory'):
            memory = self.memory.memory
            projects = memory.get('projects', {})
            
            for name, data in projects.items():
                first_seen = data.get('first_seen')
                if first_seen:
                    first_date = datetime.fromisoformat(first_seen)
                    if first_date > week_ago:
                        new_projects += 1
                
                analyses = data.get('analyses', [])
                week_analyses = [a for a in analyses 
                               if datetime.fromisoformat(a['date']) > week_ago]
                total_analyses += len(week_analyses)
            
            report.append(f"\n## 📈 СТАТИСТИКА ЗА НЕДЕЛЮ")
            report.append(f"Новых проектов: {new_projects}")
            report.append(f"Проведено анализов: {total_analyses}")
        
        # Топ проектов по активности
        if self.memory:
            report.append(f"\n## 🔥 АКТИВНЫЕ ПРОЕКТЫ")
            changed = self.memory.get_changed_projects(168)  # 7 дней
            for proj in changed[:10]:
                report.append(f"- {proj}")
        
        report_path = os.path.expanduser(f"~/AIM/reports/weekly_{datetime.now().strftime('%Y%W')}.md")
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))
        
        return report_path
    
    def generate_project_report(self, project_name, project_data):
        """Отчет по конкретному проекту"""
        
        report = []
        report.append(f"# 📋 ОТЧЕТ ПО ПРОЕКТУ: {project_name}")
        report.append(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("="*60)
        
        # Основная информация
        report.append(f"\n## 📁 ИНФОРМАЦИЯ")
        report.append(f"Путь: {project_data.get('path', 'Неизвестно')}")
        report.append(f"Файлов: {len(project_data.get('files', []))}")
        
        # История анализов
        analyses = project_data.get('analyses', [])
        if analyses:
            report.append(f"\n## 📝 ИСТОРИЯ АНАЛИЗОВ")
            for i, analysis in enumerate(analyses[-5:], 1):
                date = datetime.fromisoformat(analysis['date']).strftime('%Y-%m-%d %H:%M')
                report.append(f"\n### Анализ {i} от {date}")
                report.append(analysis['content'][:300] + "...")
        
        # Статистика изменений
        changes = project_data.get('changes', [])
        if changes:
            report.append(f"\n## 🔄 ИСТОРИЯ ИЗМЕНЕНИЙ")
            for change in changes[-10:]:
                date = datetime.fromisoformat(change['date']).strftime('%H:%M %d.%m')
                report.append(f"- {date}: {change.get('type', 'Изменение')}")
        
        # Сохраняем отчет
        report_path = os.path.join(project_data['path'], '_project_report.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))
        
        return report_path
    
    def generate_statistics_report(self):
        """Подробный статистический отчет"""
        
        report = []
        report.append("# 📊 СТАТИСТИЧЕСКИЙ ОТЧЕТ AI СИСТЕМЫ")
        report.append(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("="*60)
        
        if not self.memory or not hasattr(self.memory, 'memory'):
            report.append("\n❌ Нет данных для статистики")
            return None
        
        memory = self.memory.memory
        projects = memory.get('projects', {})
        
        # Общая статистика
        report.append(f"\n## 📈 ОБЩАЯ СТАТИСТИКА")
        report.append(f"Всего проектов: {len(projects)}")
        
        total_analyses = sum(len(p.get('analyses', [])) for p in projects.values())
        report.append(f"Всего анализов: {total_analyses}")
        
        total_changes = sum(len(p.get('changes', [])) for p in projects.values())
        report.append(f"Всего изменений: {total_changes}")
        
        # Статистика по времени
        now = datetime.now()
        report.append(f"\n## ⏰ ПО ВРЕМЕНИ")
        
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        
        active_day = 0
        active_week = 0
        active_month = 0
        
        for name, data in projects.items():
            last_seen = data.get('last_seen')
            if last_seen:
                last = datetime.fromisoformat(last_seen)
                if last > day_ago:
                    active_day += 1
                if last > week_ago:
                    active_week += 1
                if last > month_ago:
                    active_month += 1
        
        report.append(f"Активны за 24ч: {active_day}")
        report.append(f"Активны за неделю: {active_week}")
        report.append(f"Активны за месяц: {active_month}")
        
        # Типы проектов
        report.append(f"\n## 🏷️ ТИПЫ ПРОЕКТОВ")
        types = []
        for name, data in projects.items():
            files = data.get('files', [])
            if any(f.endswith('.py') for f in files):
                types.append('Python')
            elif any(f.endswith(('.html', '.css', '.js')) for f in files):
                types.append('Web')
            else:
                types.append('Other')
        
        type_counts = Counter(types)
        for ptype, count in type_counts.most_common():
            report.append(f"- {ptype}: {count}")
        
        # Топ проектов
        report.append(f"\n## ⭐ ТОП ПРОЕКТОВ")
        project_scores = []
        for name, data in projects.items():
            score = len(data.get('analyses', [])) * 2 + len(data.get('changes', []))
            project_scores.append((name, score))
        
        for name, score in sorted(project_scores, key=lambda x: x[1], reverse=True)[:10]:
            report.append(f"- {name}: {score} очков активности")
        
        # Сохраняем отчет
        report_path = os.path.expanduser(f"~/AIM/reports/statistics_{datetime.now().strftime('%Y%m%d')}.md")
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))
        
        return report_path
    
    def list_reports(self):
        """Показывает все доступные отчеты"""
        reports_dir = os.path.expanduser("~/AIM/reports")
        
        if not os.path.exists(reports_dir):
            print("📭 Нет сохраненных отчетов")
            return []
        
        reports = []
        for file in os.listdir(reports_dir):
            if file.endswith('.md'):
                filepath = os.path.join(reports_dir, file)
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                size = os.path.getsize(filepath)
                reports.append({
                    'name': file,
                    'date': mtime,
                    'size': size,
                    'path': filepath
                })
        
        return sorted(reports, key=lambda x: x['date'], reverse=True)

# Тестирование
if __name__ == "__main__":
    print("📊 ТЕСТ ГЕНЕРАЦИИ ОТЧЕТОВ")
    print("="*40)
    
    # Создаем тестовый отчет
    reporter = ReportGenerator()
    
    daily = reporter.generate_daily_report()
    print(f"✅ Ежедневный отчет: {daily}")
    
    weekly = reporter.generate_weekly_report()
    print(f"✅ Еженедельный отчет: {weekly}")
    
    stats = reporter.generate_statistics_report()
    if stats:
        print(f"✅ Статистический отчет: {stats}")
    
    print("\n📋 Доступные отчеты:")
    for r in reporter.list_reports()[:5]:
        print(f"  • {r['name']} ({r['date'].strftime('%Y-%m-%d')})")
