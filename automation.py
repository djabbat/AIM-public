#!/usr/bin/env python3
import os
import subprocess
import shutil
from datetime import datetime
import json
import time
import threading

try:
    import schedule
except ImportError:
    print("⚠️ schedule не установлен. Установите: pip install schedule")
    schedule = None

class GitAutomation:
    """Автоматизация Git коммитов"""
    
    def __init__(self, projects_path):
        self.projects_path = projects_path
        self.git_available = self.check_git()
        
    def check_git(self):
        """Проверяет наличие git"""
        try:
            subprocess.run(['git', '--version'], capture_output=True)
            return True
        except:
            return False
    
    def is_git_repo(self, project_path):
        """Проверяет, является ли папка git репозиторием"""
        return os.path.exists(os.path.join(project_path, '.git'))
    
    def init_git(self, project_path):
        """Инициализирует git репозиторий"""
        if not self.git_available:
            return False, "Git не установлен"
        
        try:
            subprocess.run(['git', 'init'], cwd=project_path, check=True, capture_output=True)
            gitignore = os.path.join(project_path, '.gitignore')
            if not os.path.exists(gitignore):
                with open(gitignore, 'w') as f:
                    f.write("""# Python
__pycache__/
*.py[cod]
*.so
.Python
venv/
env/
ENV/
# IDE
.vscode/
.idea/
*.swp
*.swo
# Logs
*.log
logs/
# OS
.DS_Store
Thumbs.db
# Project specific
_secret_*
*.key
*.pem
""")
            return True, "Git репозиторий создан"
        except Exception as e:
            return False, str(e)
    
    def get_changed_files(self, project_path):
        """Получает список измененных файлов"""
        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'], 
                cwd=project_path, 
                capture_output=True, 
                text=True
            )
            files = []
            for line in result.stdout.split('\n'):
                if line.strip():
                    status = line[:2].strip()
                    file = line[3:].strip()
                    files.append({'status': status, 'file': file})
            return files
        except:
            return []
    
    def commit(self, project_path, message=None):
        """Создает коммит"""
        if not self.is_git_repo(project_path):
            self.init_git(project_path)
        
        try:
            subprocess.run(['git', 'add', '.'], cwd=project_path, check=True, capture_output=True)
            status = subprocess.run(['git', 'status', '--porcelain'], cwd=project_path, capture_output=True, text=True)
            if not status.stdout.strip():
                return False, "Нет изменений для коммита"
            
            if not message:
                message = f"Auto commit {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            result = subprocess.run(
                ['git', 'commit', '-m', message],
                cwd=project_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return True, f"Коммит создан: {message}"
            else:
                return False, result.stderr
        except Exception as e:
            return False, str(e)
    
    def auto_commit_all(self, projects, message=None):
        """Автоматически коммитит все проекты с изменениями"""
        results = []
        for name, data in projects.items():
            path = data['path']
            if os.path.exists(path):
                success, msg = self.commit(path, message)
                if success:
                    results.append(f"✅ {name}: {msg}")
                elif msg != "Нет изменений для коммита":
                    results.append(f"⚠️ {name}: {msg}")
        return results

class BackupAutomation:
    """Автоматизация бэкапов"""
    
    def __init__(self, backup_path="~/AIM/backups"):
        self.backup_path = os.path.expanduser(backup_path)
        os.makedirs(self.backup_path, exist_ok=True)
    
    def backup_project(self, project_path, project_name):
        """Создает бэкап проекта"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{project_name}_{timestamp}.zip"
        backup_file = os.path.join(self.backup_path, backup_name)
        
        try:
            shutil.make_archive(
                backup_file.replace('.zip', ''),
                'zip',
                project_path
            )
            
            size = os.path.getsize(backup_file) / (1024*1024)
            return {
                'success': True,
                'file': backup_file,
                'size': f"{size:.2f} MB",
                'time': timestamp
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def backup_all(self, projects):
        """Бэкапит все проекты"""
        results = []
        for name, data in projects.items():
            result = self.backup_project(data['path'], name)
            if result['success']:
                results.append(f"✅ {name}: {result['file']} ({result['size']})")
            else:
                results.append(f"❌ {name}: {result['error']}")
        return results
    
    def list_backups(self):
        """Список всех бэкапов"""
        backups = []
        for file in os.listdir(self.backup_path):
            if file.endswith('.zip'):
                filepath = os.path.join(self.backup_path, file)
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                size = os.path.getsize(filepath) / (1024*1024)
                backups.append({
                    'name': file,
                    'date': mtime,
                    'size': f"{size:.2f} MB",
                    'path': filepath
                })
        return sorted(backups, key=lambda x: x['date'], reverse=True)
    
    def restore_backup(self, backup_file, target_path):
        """Восстанавливает проект из бэкапа"""
        try:
            shutil.unpack_archive(backup_file, target_path)
            return True, "Бэкап восстановлен"
        except Exception as e:
            return False, str(e)

class AutoReporter:
    """Автоматическая генерация отчетов"""
    
    def __init__(self, reporter):
        self.reporter = reporter
        self.reports_dir = os.path.expanduser("~/AIM/reports")
        os.makedirs(self.reports_dir, exist_ok=True)
    
    def generate_daily(self):
        """Ежедневный отчет"""
        if self.reporter:
            path = self.reporter.generate_daily_report()
            return f"✅ Ежедневный отчет: {path}"
        return "❌ Репортер не доступен"
    
    def generate_weekly(self):
        """Еженедельный отчет"""
        if self.reporter:
            path = self.reporter.generate_weekly_report()
            return f"✅ Еженедельный отчет: {path}"
        return "❌ Репортер не доступен"
    
    def generate_stats(self):
        """Статистический отчет"""
        if self.reporter:
            path = self.reporter.generate_statistics_report()
            return f"✅ Статистический отчет: {path}"
        return "❌ Репортер не доступен"

class Scheduler:
    """Планировщик задач"""
    
    def __init__(self, automation, backup, reporter):
        self.automation = automation
        self.backup = backup
        self.reporter = reporter
        self.jobs = []
        self.running = False
        
        if not schedule:
            print("⚠️ Планировщик не доступен: установите schedule")
    
    def start(self):
        """Запускает планировщик"""
        if not schedule:
            print("❌ Планировщик не доступен")
            return
            
        self.running = True
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        print("⏰ Планировщик запущен")
    
    def _run(self):
        while self.running:
            if schedule:
                schedule.run_pending()
            time.sleep(60)
    
    def stop(self):
        """Останавливает планировщик"""
        self.running = False
        print("⏰ Планировщик остановлен")
    
    def add_daily_commit(self, projects, hour=18, minute=0):
        """Ежедневный коммит в указанное время"""
        if not schedule:
            print("❌ Планировщик не доступен")
            return
            
        job = schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(
            self.automation.auto_commit_all, projects, "Daily auto commit"
        )
        self.jobs.append(('daily_commit', job))
        print(f"✅ Добавлен ежедневный коммит в {hour:02d}:{minute:02d}")
    
    def add_daily_backup(self, projects, hour=2, minute=0):
        """Ежедневный бэкап"""
        if not schedule:
            print("❌ Планировщик не доступен")
            return
            
        job = schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(
            self.backup.backup_all, projects
        )
        self.jobs.append(('daily_backup', job))
        print(f"✅ Добавлен ежедневный бэкап в {hour:02d}:{minute:02d}")
    
    def add_weekly_report(self, day='monday', hour=9, minute=0):
        """Еженедельный отчет"""
        if not schedule:
            print("❌ Планировщик не доступен")
            return
            
        job = getattr(schedule.every(), day).at(f"{hour:02d}:{minute:02d}").do(
            self.reporter.generate_weekly
        )
        self.jobs.append(('weekly_report', job))
        print(f"✅ Добавлен еженедельный отчет по {day}")
    
    def list_jobs(self):
        """Список запланированных задач"""
        if not self.jobs:
            return "📭 Нет запланированных задач"
        
        result = []
        for name, job in self.jobs:
            next_run = job.next_run.strftime('%Y-%m-%d %H:%M') if job and job.next_run else 'неизвестно'
            result.append(f"  • {name}: следующий запуск {next_run}")
        return '\n'.join(result)

if __name__ == "__main__":
    print("🔄 ТЕСТ АВТОМАТИЗАЦИИ")
    print("="*40)
    git = GitAutomation(".")
    print(f"Git доступен: {git.check_git()}")
