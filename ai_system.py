#!/usr/bin/env python3
import os
import sys
import time
import threading
from datetime import datetime

VENV_PATH = os.path.expanduser("~/AIM/venv/lib/python3.*/site-packages")
import glob
site_packages = glob.glob(VENV_PATH)
if site_packages:
    sys.path.append(site_packages[0])

try:
    import ollama
except ImportError:
    print("❌ Ollama не установлен. Запустите: source ~/AIM/venv/bin/activate && pip install ollama")
    sys.exit(1)

class AISystem:
    def __init__(self):
        self.root = os.path.expanduser("~/AIM")
        self.desktop = os.path.expanduser("~/AIM/Patients")
        self.projects = {}
        self.running = True
        self.model = "llama3.2"
        
        try:
            from memory import ProjectMemory
            self.memory = ProjectMemory()
            print("🧠 Память инициализирована")
        except Exception as e:
            print(f"⚠️ Ошибка памяти: {e}")
            self.memory = None
        
        try:
            from code_generator import ProjectStructure, CodeGenerator
            self.structure = ProjectStructure(self.model)
            self.code_gen = CodeGenerator(self.model)
            print("🔧 Генератор кода инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка генератора: {e}")
            self.structure = None
            self.code_gen = None
        
        try:
            from deep_analysis import DeepAnalyzer
            self.deep_analyzer = DeepAnalyzer(self.model)
            print("🔍 Глубокий анализатор инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка глубокого анализа: {e}")
            self.deep_analyzer = None
        
        try:
            from reports import ReportGenerator
            self.reporter = ReportGenerator(self.desktop, self.memory)
            print("📊 Генератор отчетов инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка генератора отчетов: {e}")
            self.reporter = None
        
        try:
            from security import SecurityManager
            self.security = SecurityManager()
            self.security.load_config()
            print("🔒 Менеджер безопасности инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка безопасности: {e}")
            self.security = None
        
        try:
            from performance import PerformanceOptimizer
            self.performance = PerformanceOptimizer()
            print("🚀 Оптимизатор производительности инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка производительности: {e}")
            self.performance = None
        
        try:
            from web_interface import WebUI
            self.web = WebUI(self)
            print("🌐 Веб-интерфейс инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка веб-интерфейса: {e}")
            self.web = None
        
        try:
            from automation import GitAutomation, BackupAutomation, AutoReporter, Scheduler
            self.git = GitAutomation(self.desktop)
            self.backup = BackupAutomation()
            self.auto_reporter = AutoReporter(self.reporter) if self.reporter else None
            self.scheduler = Scheduler(self.git, self.backup, self.auto_reporter)
            print("🔄 Автоматизация инициализирована")
        except Exception as e:
            print(f"⚠️ Ошибка автоматизации: {e}")
            self.git = None
            self.backup = None
            self.scheduler = None
        
        try:
            from error_detector import ErrorDetector
            self.error_detector = ErrorDetector(self.model)
            print("🐛 Детектор ошибок инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка детектора ошибок: {e}")
            self.error_detector = None
        
        try:
            from optimization import Optimizer
            self.optimizer = Optimizer()
            self.optimizer.monitor.start_monitoring()
            print("🚀 Оптимизатор инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка оптимизатора: {e}")
            self.optimizer = None
        
        try:
            from material_search import MaterialSearcher, DailySearcher
            self.searcher = MaterialSearcher(self.model)
            self.daily_searcher = DailySearcher(self.searcher)
            print("🔍 Поиск материалов инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка поиска материалов: {e}")
            self.searcher = None
            self.daily_searcher = None
        
        try:
            from trend_reporter import TrendReporter
            self.trend_reporter = TrendReporter(self.model)
            print("📈 Отчет о трендах инициализирован")
        except Exception as e:
            print(f"⚠️ Ошибка отчетов о трендах: {e}")
            self.trend_reporter = None
        
        try:
            from integration import IntegrationManager
            self.integration = IntegrationManager()
            print("🔌 Интеграции инициализированы")
        except Exception as e:
            print(f"⚠️ Ошибка интеграций: {e}")
            self.integration = None
        
        try:
            from self_learning import LearningSystem, MetaLearner
            self.learner = LearningSystem(self.model)
            self.meta_learner = MetaLearner(self.learner)
            print("🧠 Система самообучения инициализирована")
        except Exception as e:
            print(f"⚠️ Ошибка самообучения: {e}")
            self.learner = None
            self.meta_learner = None
        
        try:
            from feedback import FeedbackSystem, UserFeedbackCollector
            self.feedback = FeedbackSystem(self.model)
            self.feedback_collector = UserFeedbackCollector(self.feedback)
            print("💬 Система обратной связи инициализирована")
        except Exception as e:
            print(f"⚠️ Ошибка обратной связи: {e}")
            self.feedback = None
            self.feedback_collector = None
        
        print("\n" + "="*60)
        print("🤖 МНОГОАГЕНТНАЯ AI СИСТЕМА")
        print("="*60)
        print(f"📁 Система: {self.root}")
        print(f"📁 Проекты: {self.desktop}")
        print("="*60)
        
        self.check_ollama()
        self.scan_projects()
        self.watch_desktop()
    
    def check_ollama(self):
        try:
            ollama.list()
            print("✅ Ollama работает")
        except:
            print("⚠️ Ollama не запущен. Запустите: ollama serve")
    
    def scan_projects(self):
        print("\n🔍 Поиск проектов...")
        for item in os.listdir(self.desktop):
            path = os.path.join(self.desktop, item)
            if os.path.isdir(path) and not item.startswith('.'):
                if self.security:
                    files = self.security.filter_project_files(path)['valid']
                else:
                    files = self.get_files(path)
                self.projects[item] = {
                    'path': path,
                    'files': files
                }
                print(f"  ✅ {item}")
                if self.memory:
                    self.memory.add_project(item, path, files)
    
    def get_files(self, path):
        files = []
        try:
            for root, dirs, filenames in os.walk(path):
                return [f for f in filenames if not f.startswith('.')][:20]
        except:
            return []
        return []
    
    def watch_desktop(self):
        def monitor():
            while self.running:
                interval = self.performance.config['scan_interval'] if self.performance else 5
                time.sleep(interval)
                try:
                    if self.performance:
                        new_projects = self.performance.scan_projects_optimized(
                            self.desktop, self.projects, self.security
                        )
                        for name, path, files in new_projects:
                            print(f"\n✨ Новый проект: {name}")
                            self.projects[name] = {
                                'path': path,
                                'files': files
                            }
                            if self.memory:
                                self.memory.add_project(name, path, files)
                            self.analyze_project(name)
                    else:
                        current = set(os.listdir(self.desktop))
                        existing = set(self.projects.keys())
                        for item in current:
                            path = os.path.join(self.desktop, item)
                            if os.path.isdir(path) and not item.startswith('.') and item not in existing:
                                print(f"\n✨ Новый проект: {item}")
                                if self.security:
                                    files = self.security.filter_project_files(path)['valid']
                                else:
                                    files = self.get_files(path)
                                self.projects[item] = {
                                    'path': path,
                                    'files': files
                                }
                                if self.memory:
                                    self.memory.add_project(item, path, files)
                                self.analyze_project(item)
                except:
                    pass
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    
    def list_projects(self):
        print("\n📋 ПРОЕКТЫ:")
        if not self.projects:
            print("  Нет проектов")
            return
        for name, info in self.projects.items():
            print(f"  📁 {name} ({len(info['files'])} файлов)")
    
    def analyze_project(self, name):
        project = self.projects.get(name)
        if not project:
            return
        print(f"\n🤖 Анализ проекта: {name}")
        prompt = f"""Проект: {name}
Файлы: {project['files'][:10]}
Что это за проект? Как его развивать?"""
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            analysis = response['message']['content']
            with open(os.path.join(project['path'], '_ai_analysis.txt'), 'w', encoding='utf-8') as f:
                f.write(f"AI АНАЛИЗ\n")
                f.write("="*40 + "\n")
                f.write(analysis)
            if self.memory:
                self.memory.add_analysis(name, analysis)
            print(f"  ✅ Анализ сохранен")
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")
    
    def analyze_any_project(self):
        path = input("\nВведите путь к проекту: ").strip()
        if os.path.exists(path):
            print(f"\n🔍 Анализ проекта: {path}")
            os.system(f"python3 todo_analyzer.py '{path}' 2>/dev/null || python3 ~/AIM/todo_analyzer.py '{path}'")
        else:
            print("❌ Путь не существует")
    
    def analyze_todo(self):
        print("\n📋 АНАЛИЗ TODO.MD")
        print("="*40)
        self.list_projects()
        name = input("\nИмя проекта: ").strip()
        if name not in self.projects:
            print("❌ Проект не найден")
            return
        project_path = self.projects[name]['path']
        todo_path = os.path.join(project_path, 'TODO.md')
        if not os.path.exists(todo_path):
            print(f"\n⚠️ TODO.md не найден")
            return
        with open(todo_path, 'r', encoding='utf-8') as f:
            todo_content = f.read()
        print(f"\n📄 Текущий TODO.md:")
        print("-"*40)
        print(todo_content[:500])
        prompt = f"""Проект: {name}
TODO.md:
{todo_content[:2000]}
Файлы: {self.projects[name]['files'][:10]}
Проанализируй TODO.md и предложи что делать дальше."""
        try:
            print("\n🤖 AI анализирует...")
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            analysis = response['message']['content']
            analysis_file = os.path.join(project_path, '_todo_analysis.md')
            with open(analysis_file, 'w', encoding='utf-8') as f:
                f.write(f"# Анализ TODO.md\n")
                f.write(analysis)
            print(f"\n✅ Анализ сохранен")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def create_todo(self, project_path, project_name):
        prompt = f"""Проект: {project_name}
Создай TODO.md со списком задач."""
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            todo = response['message']['content']
            todo_path = os.path.join(project_path, 'TODO.md')
            with open(todo_path, 'w', encoding='utf-8') as f:
                f.write(f"# TODO: {project_name}\n\n")
                f.write(todo)
            print(f"\n✅ TODO.md создан")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def update_todo(self):
        print("\n📝 ОБНОВЛЕНИЕ TODO.MD")
        self.list_projects()
        name = input("\nИмя проекта: ").strip()
        if name not in self.projects:
            print("❌ Проект не найден")
            return
        project_path = self.projects[name]['path']
        todo_path = os.path.join(project_path, 'TODO.md')
        if not os.path.exists(todo_path):
            print("❌ TODO.md не найден")
            return
        with open(todo_path, 'r', encoding='utf-8') as f:
            todo_content = f.read()
        prompt = f"""Проект: {name}
TODO.md:
{todo_content[:2000]}
Файлы: {self.projects[name]['files'][:10]}
Какие задачи уже выполнены? Обнови TODO.md."""
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            updated = response['message']['content']
            with open(todo_path, 'w', encoding='utf-8') as f:
                f.write(updated)
            print(f"\n✅ TODO.md обновлен")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def auto_structure(self, name):
        if not self.structure:
            print("❌ Генератор структуры не доступен")
            return
        project = self.projects.get(name)
        if not project:
            print("❌ Проект не найден")
            return
        print(f"\n🏗️ СОЗДАНИЕ СТРУКТУРЫ ДЛЯ: {name}")
        proj_type = self.structure.detect_project_type(project['files'])
        print(f"📋 Тип проекта: {proj_type}")
        template = self.structure.get_structure_templates(proj_type)
        created = []
        for item in template:
            full_path = os.path.join(project['path'], item)
            if '.' in os.path.basename(item):
                if not os.path.exists(full_path):
                    with open(full_path, 'w', encoding='utf-8') as f:
                        if item == 'README.md':
                            f.write(f"# {name}\n\nАвтоматически создано AI системой\n")
                        elif item == 'requirements.txt':
                            f.write("# Зависимости проекта\n")
                        elif item.endswith('.py'):
                            f.write(f"# {item}\n\n")
                    created.append(f"📄 {item}")
            else:
                if not os.path.exists(full_path):
                    os.makedirs(full_path, exist_ok=True)
                    created.append(f"📁 {item}")
        if created:
            print(f"\n✅ Создано:")
            for item in created[:10]:
                print(f"  {item}")
        project['files'] = self.get_files(project['path'])
    
    def generate_project_code(self, name):
        if not self.code_gen:
            print("❌ Генератор кода не доступен")
            return
        project = self.projects.get(name)
        if not project:
            print("❌ Проект не найден")
            return
        print(f"\n💻 ГЕНЕРАЦИЯ КОДА ДЛЯ: {name}")
        print("1. Сгенерировать main.py")
        print("2. Сгенерировать функцию")
        print("3. Сгенерировать класс")
        print("4. Сгенерировать тесты")
        print("5. Улучшить существующий код")
        choice = input("\n👉 Выбор: ").strip()
        if choice == '1':
            task = input("Что должна делать программа? ").strip()
            code = self.code_gen.generate_code(task)
            filepath = self.code_gen.save_code(project['path'], 'src/main.py', code)
            print(f"\n✅ Код сохранен: {filepath}")
        elif choice == '2':
            desc = input("Описание функции: ").strip()
            code = self.code_gen.generate_function(desc)
            print(f"\n📝 Сгенерированная функция:\n{code}")
            save = input("\nСохранить в файл? (y/n): ").strip().lower()
            if save == 'y':
                filename = input("Имя файла (например utils.py): ").strip()
                filepath = self.code_gen.save_code(project['path'], filename, code)
                print(f"✅ Сохранено: {filepath}")
        elif choice == '3':
            desc = input("Описание класса: ").strip()
            code = self.code_gen.generate_class(desc)
            print(f"\n📝 Сгенерированный класс:\n{code}")
            save = input("\nСохранить в файл? (y/n): ").strip().lower()
            if save == 'y':
                filename = input("Имя файла: ").strip()
                filepath = self.code_gen.save_code(project['path'], filename, code)
                print(f"✅ Сохранено: {filepath}")
        elif choice == '4':
            code_file = input("Путь к файлу с кодом: ").strip()
            if os.path.exists(code_file):
                with open(code_file, 'r', encoding='utf-8') as f:
                    code = f.read()
                tests = self.code_gen.generate_test(code)
                test_file = code_file.replace('.py', '_test.py')
                with open(test_file, 'w', encoding='utf-8') as f:
                    f.write(tests)
                print(f"✅ Тесты сохранены: {test_file}")
            else:
                print("❌ Файл не найден")
        elif choice == '5':
            code_file = input("Путь к файлу с кодом: ").strip()
            if os.path.exists(code_file):
                with open(code_file, 'r', encoding='utf-8') as f:
                    code = f.read()
                instructions = input("Что улучшить? (enter для общего улучшения): ").strip()
                improved = self.code_gen.improve_code(code, instructions)
                improved_file = code_file.replace('.py', '_improved.py')
                with open(improved_file, 'w', encoding='utf-8') as f:
                    f.write(improved)
                print(f"✅ Улучшенный код сохранен: {improved_file}")
            else:
                print("❌ Файл не найден")
    
    def explain_code_file(self, name):
        if not self.code_gen:
            print("❌ Генератор кода не доступен")
            return
        project = self.projects.get(name)
        if not project:
            print("❌ Проект не найден")
            return
        print(f"\n📚 Файлы в проекте {name}:")
        py_files = [f for f in project['files'] if f.endswith('.py')]
        for i, f in enumerate(py_files[:10], 1):
            print(f"  {i}. {f}")
        if not py_files:
            print("❌ Нет Python файлов")
            return
        choice = input("\nВыберите файл (номер): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(py_files):
                filepath = os.path.join(project['path'], py_files[idx])
                with open(filepath, 'r', encoding='utf-8') as f:
                    code = f.read()
                print("\n🤖 AI объясняет код...")
                explanation = self.code_gen.explain_code(code[:2000])
                print(f"\n📝 Объяснение:\n{explanation}")
                exp_file = filepath.replace('.py', '_explanation.txt')
                with open(exp_file, 'w', encoding='utf-8') as f:
                    f.write(explanation)
                print(f"\n✅ Объяснение сохранено: {exp_file}")
        except:
            print("❌ Неверный выбор")
    
    def deep_analyze_project(self, name):
        if not self.deep_analyzer:
            print("❌ Глубокий анализатор не доступен")
            return
        project = self.projects.get(name)
        if not project:
            print("❌ Проект не найден")
            return
        result = self.deep_analyzer.deep_analysis(
            name, 
            project['path'], 
            project['files'],
            self.memory
        )
        if result and self.memory:
            self.memory.add_analysis(name, str(result))
    
    def generate_reports(self):
        if not self.reporter:
            print("❌ Генератор отчетов не доступен")
            return
        print("\n📊 ГЕНЕРАЦИЯ ОТЧЕТОВ")
        print("="*40)
        print("1. Ежедневный отчет")
        print("2. Еженедельный отчет")
        print("3. Отчет по проекту")
        print("4. Статистический отчет")
        print("5. Показать все отчеты")
        print("6. Назад")
        choice = input("\n👉 Выбор: ").strip()
        if choice == '1':
            path = self.reporter.generate_daily_report()
            print(f"✅ Отчет сохранен: {path}")
        elif choice == '2':
            path = self.reporter.generate_weekly_report()
            print(f"✅ Отчет сохранен: {path}")
        elif choice == '3':
            self.list_projects()
            name = input("Имя проекта: ").strip()
            if name in self.projects:
                path = self.reporter.generate_project_report(name, {
                    'path': self.projects[name]['path'],
                    'files': self.projects[name]['files'],
                    'analyses': self.memory.memory['projects'].get(name, {}).get('analyses', []) if self.memory else [],
                    'changes': self.memory.memory['projects'].get(name, {}).get('changes', []) if self.memory else []
                })
                print(f"✅ Отчет сохранен: {path}")
            else:
                print("❌ Проект не найден")
        elif choice == '4':
            path = self.reporter.generate_statistics_report()
            if path:
                print(f"✅ Отчет сохранен: {path}")
        elif choice == '5':
            reports = self.reporter.list_reports()
            if reports:
                print("\n📋 ДОСТУПНЫЕ ОТЧЕТЫ:")
                for r in reports[:10]:
                    print(f"  • {r['name']} ({r['date'].strftime('%Y-%m-%d %H:%M')})")
            else:
                print("📭 Нет отчетов")
    
    def security_menu(self):
        if not self.security:
            print("❌ Менеджер безопасности не доступен")
            return
        while True:
            print("\n" + "="*40)
            print("🔒 МЕНЮ БЕЗОПАСНОСТИ")
            print("="*40)
            print("1. Показать игнорируемые паттерны")
            print("2. Добавить паттерн")
            print("3. Удалить паттерн")
            print("4. Проверить проект")
            print("5. Изменить лимиты")
            print("6. Сохранить конфигурацию")
            print("7. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                self.security.print_ignore_list()
            elif choice == '2':
                pattern = input("Введите паттерн (например *.tmp): ").strip()
                self.security.add_ignore_pattern(pattern)
                self.security.save_config()
            elif choice == '3':
                pattern = input("Введите паттерн для удаления: ").strip()
                self.security.remove_ignore_pattern(pattern)
                self.security.save_config()
            elif choice == '4':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    stats = self.security.get_project_stats(self.projects[name]['path'])
                    print(f"\n📊 Статистика проекта {name}:")
                    print(f"  Всего файлов: {stats['total']}")
                    print(f"  Для анализа: {stats['analyzed']}")
                    print(f"  Игнорируется: {stats['ignored']}")
                    print(f"  Слишком большие: {stats['large']}")
                    if stats['ignored_list']:
                        print(f"\n  Игнорируемые:")
                        for f in stats['ignored_list'][:5]:
                            print(f"    • {f}")
                else:
                    print("❌ Проект не найден")
            elif choice == '5':
                print(f"\nТекущие лимиты:")
                print(f"  Макс. размер файла: {self.security.max_file_size/1024/1024:.1f} MB")
                print(f"  Макс. файлов: {self.security.max_files_per_project}")
                size = input("Новый макс. размер файла в MB (enter для пропуска): ").strip()
                if size:
                    self.security.max_file_size = float(size) * 1024 * 1024
                count = input("Новый макс. количество файлов: ").strip()
                if count:
                    self.security.max_files_per_project = int(count)
                self.security.save_config()
                print("✅ Лимиты обновлены")
            elif choice == '6':
                self.security.save_config()
                print("✅ Конфигурация сохранена")
            elif choice == '7':
                break
    
    def performance_menu(self):
        if not self.performance:
            print("❌ Оптимизатор не доступен")
            return
        while True:
            print("\n" + "="*40)
            print("🚀 МЕНЮ ПРОИЗВОДИТЕЛЬНОСТИ")
            print("="*40)
            print("1. Показать отчет")
            print("2. Автооптимизация")
            print("3. Настроить параметры")
            print("4. Очистить кэш")
            print("5. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                print(self.performance.get_performance_report())
            elif choice == '2':
                config = self.performance.optimize_config(len(self.projects))
                print(f"\n✅ Конфигурация оптимизирована:")
                print(f"  Workers: {config['max_workers']}")
                print(f"  Batch size: {config['batch_size']}")
            elif choice == '3':
                print(f"\nТекущие настройки:")
                for key, value in self.performance.config.items():
                    print(f"  {key}: {value}")
                workers = input("\nМакс потоков (enter для пропуска): ").strip()
                if workers:
                    self.performance.config['max_workers'] = int(workers)
                interval = input("Интервал сканирования (сек): ").strip()
                if interval:
                    self.performance.config['scan_interval'] = int(interval)
                parallel = input("Параллельный анализ (y/n): ").strip().lower()
                if parallel == 'y':
                    self.performance.config['parallel_analysis'] = True
                elif parallel == 'n':
                    self.performance.config['parallel_analysis'] = False
                cache = input("Включить кэш (y/n): ").strip().lower()
                if cache == 'y':
                    self.performance.config['cache_enabled'] = True
                elif cache == 'n':
                    self.performance.config['cache_enabled'] = False
                print("✅ Настройки обновлены")
            elif choice == '4':
                cleared = self.performance.clear_cache()
                print(f"✅ Кэш очищен: {cleared} элементов")
            elif choice == '5':
                break
    
    def web_menu(self):
        if not self.web:
            print("❌ Веб-интерфейс не доступен")
            return
        while True:
            print("\n" + "="*40)
            print("🌐 ВЕБ-ИНТЕРФЕЙС")
            print("="*40)
            print("1. Запустить сервер")
            print("2. Остановить сервер")
            print("3. Статус")
            print("4. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                if self.web.running:
                    print("⚠️ Сервер уже запущен")
                else:
                    self.web.start()
                    print(f"✅ Сервер запущен на http://localhost:{self.web.port}")
            elif choice == '2':
                if self.web.running:
                    self.web.stop()
                    print("✅ Сервер остановлен")
                else:
                    print("⚠️ Сервер не запущен")
            elif choice == '3':
                if self.web.running:
                    print(f"✅ Сервер работает на http://localhost:{self.web.port}")
                else:
                    print("❌ Сервер не запущен")
            elif choice == '4':
                break
    
    def automation_menu(self):
        if not self.git:
            print("❌ Автоматизация не доступна")
            return
        while True:
            print("\n" + "="*40)
            print("🔄 МЕНЮ АВТОМАТИЗАЦИИ")
            print("="*40)
            print("1. Git коммит для проекта")
            print("2. Git коммит для всех проектов")
            print("3. Инициализировать Git репозиторий")
            print("4. Создать бэкап проекта")
            print("5. Создать бэкап всех проектов")
            print("6. Список бэкапов")
            print("7. Запустить планировщик")
            print("8. Остановить планировщик")
            print("9. Добавить задачу в планировщик")
            print("10. Список задач")
            print("11. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    msg = input("Сообщение коммита (enter для авто): ").strip()
                    success, result = self.git.commit(self.projects[name]['path'], msg or None)
                    if success:
                        print(f"✅ {result}")
                    else:
                        print(f"❌ {result}")
                else:
                    print("❌ Проект не найден")
            elif choice == '2':
                results = self.git.auto_commit_all(self.projects)
                for r in results:
                    print(r)
            elif choice == '3':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    success, result = self.git.init_git(self.projects[name]['path'])
                    if success:
                        print(f"✅ {result}")
                    else:
                        print(f"❌ {result}")
                else:
                    print("❌ Проект не найден")
            elif choice == '4':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    result = self.backup.backup_project(self.projects[name]['path'], name)
                    if result['success']:
                        print(f"✅ Бэкап создан: {result['file']} ({result['size']})")
                    else:
                        print(f"❌ {result['error']}")
                else:
                    print("❌ Проект не найден")
            elif choice == '5':
                results = self.backup.backup_all(self.projects)
                for r in results:
                    print(r)
            elif choice == '6':
                backups = self.backup.list_backups()
                if backups:
                    print("\n📋 БЭКАПЫ:")
                    for b in backups[:10]:
                        print(f"  • {b['name']} ({b['date'].strftime('%Y-%m-%d %H:%M')}) - {b['size']}")
                else:
                    print("📭 Нет бэкапов")
            elif choice == '7':
                if self.scheduler:
                    self.scheduler.start()
                    print("✅ Планировщик запущен")
            elif choice == '8':
                if self.scheduler:
                    self.scheduler.stop()
                    print("✅ Планировщик остановлен")
            elif choice == '9':
                if not self.scheduler:
                    print("❌ Планировщик не доступен")
                    continue
                print("\nТипы задач:")
                print("1. Ежедневный коммит")
                print("2. Ежедневный бэкап")
                print("3. Еженедельный отчет")
                task = input("Выбор: ").strip()
                if task == '1':
                    hour = int(input("Час (0-23): ").strip())
                    minute = int(input("Минута (0-59): ").strip())
                    self.scheduler.add_daily_commit(self.projects, hour, minute)
                elif task == '2':
                    hour = int(input("Час (0-23): ").strip())
                    minute = int(input("Минута (0-59): ").strip())
                    self.scheduler.add_daily_backup(self.projects, hour, minute)
                elif task == '3':
                    day = input("День недели (monday-sunday): ").strip()
                    hour = int(input("Час (0-23): ").strip())
                    minute = int(input("Минута (0-59): ").strip())
                    self.scheduler.add_weekly_report(day, hour, minute)
            elif choice == '10':
                if self.scheduler:
                    print(self.scheduler.list_jobs())
            elif choice == '11':
                break
    
    def error_detection_menu(self):
        if not self.error_detector:
            print("❌ Детектор ошибок не доступен")
            return
        while True:
            print("\n" + "="*40)
            print("🐛 ПОИСК ОШИБОК В КОДЕ")
            print("="*40)
            print("1. Проверить конкретный файл")
            print("2. Проверить проект")
            print("3. Проверить все проекты")
            print("4. Показать статистику")
            print("5. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                path = input("Путь к файлу: ").strip()
                if os.path.exists(path):
                    print(f"\n🔍 Анализ файла: {path}")
                    result = self.error_detector.analyze_file(path)
                    if result:
                        print(f"\n📊 Результаты:")
                        print(f"  Ошибок: {len(result['errors'])}")
                        print(f"  Предупреждений: {len(result['warnings'])}")
                        if result['errors']:
                            print("\n❌ Ошибки:")
                            for e in result['errors'][:5]:
                                print(f"  • Стр.{e.get('line',0)}: {e['message']}")
                else:
                    print("❌ Файл не найден")
            elif choice == '2':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    print(f"\n🔍 Анализ проекта: {name}")
                    results = self.error_detector.analyze_project(self.projects[name]['path'])
                    self.error_detector.print_results(results)
                else:
                    print("❌ Проект не найден")
            elif choice == '3':
                print("\n🔍 Анализ всех проектов...")
                for name, data in self.projects.items():
                    print(f"\n📁 Проект: {name}")
                    self.error_detector.analyze_project(data['path'])
            elif choice == '4':
                print(f"\n📊 Статистика детектора:")
                print(f"  Найдено ошибок: {self.error_detector.errors_found}")
                print(f"  Найдено предупреждений: {self.error_detector.warnings_found}")
            elif choice == '5':
                break
    
    def optimization_menu(self):
        if not self.optimizer:
            print("❌ Оптимизатор не доступен")
            return
        while True:
            print("\n" + "="*40)
            print("🚀 МЕНЮ ОПТИМИЗАЦИИ")
            print("="*40)
            print("1. Показать отчет об оптимизации")
            print("2. Применить оптимизации")
            print("3. Очистить память")
            print("4. Очистить кэш")
            print("5. Статистика запросов")
            print("6. Мониторинг производительности")
            print("7. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                print(self.optimizer.get_optimization_report())
            elif choice == '2':
                self.optimizer.apply_optimizations()
            elif choice == '3':
                result = self.optimizer.memory.auto_cleanup(force=True)
                if result:
                    print(f"✅ Память очищена: {result['before']['rss']:.1f}MB → {result['after']['rss']:.1f}MB")
                else:
                    print("✅ Очистка не требуется")
            elif choice == '4':
                size = self.optimizer.cache.clear()
                print(f"✅ Кэш очищен: {size} элементов")
            elif choice == '5':
                stats = self.optimizer.query.get_stats()
                if stats:
                    print("\n📊 СТАТИСТИКА ЗАПРОСОВ:")
                    for key, value in stats.items():
                        print(f"  {key}: {value}")
                else:
                    print("📭 Нет данных")
            elif choice == '6':
                issues = self.optimizer.monitor.check_performance()
                if issues:
                    print("\n⚠️ ПРОБЛЕМЫ ПРОИЗВОДИТЕЛЬНОСТИ:")
                    for issue in issues:
                        print(f"  • {issue}")
                else:
                    print("✅ Проблем не обнаружено")
                slow = self.optimizer.monitor.get_slow_operations()
                if slow:
                    print("\n🐢 МЕДЛЕННЫЕ ОПЕРАЦИИ:")
                    for op in slow[:5]:
                        print(f"  • {op['operation']}: {op['duration']:.2f}с")
            elif choice == '7':
                break
    
    def search_menu(self):
        if not self.searcher:
            print("❌ Поиск материалов не доступен")
            return
        while True:
            print("\n" + "="*40)
            print("🔍 ПОИСК МАТЕРИАЛОВ")
            print("="*40)
            print("1. Найти материалы для проекта")
            print("2. Найти материалы для всех проектов")
            print("3. Запустить ежедневный поиск")
            print("4. Остановить ежедневный поиск")
            print("5. История поисков")
            print("6. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    self.searcher.search_for_project(name, self.projects[name]['files'])
                else:
                    print("❌ Проект не найден")
            elif choice == '2':
                print("\n🔍 Поиск для всех проектов...")
                for name, data in self.projects.items():
                    self.searcher.search_for_project(name, data['files'])
                    time.sleep(2)
            elif choice == '3':
                if self.daily_searcher:
                    hour = int(input("Час для ежедневного поиска (0-23): ").strip())
                    self.daily_searcher.start_daily_search(self.projects, hour)
            elif choice == '4':
                if self.daily_searcher:
                    self.daily_searcher.stop_daily_search()
            elif choice == '5':
                history = self.searcher.search_history
                if history:
                    print("\n📋 ИСТОРИЯ ПОИСКОВ:")
                    for h in history[-10:]:
                        print(f"  • {h['project']}: {h['results_count']} результатов ({h['timestamp'][:10]})")
                else:
                    print("📭 История пуста")
            elif choice == '6':
                break
    
    def trend_menu(self):
        if not self.trend_reporter:
            print("❌ Отчет о трендах не доступен")
            return
        while True:
            print("\n" + "="*40)
            print("📈 ОТЧЕТЫ О ТРЕНДАХ")
            print("="*40)
            print("1. Анализ трендов для проекта")
            print("2. Еженедельный отчет о технологиях")
            print("3. Рекомендации по технологическому стеку")
            print("4. Показать GitHub тренды")
            print("5. Показать популярные PyPI пакеты")
            print("6. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    print(f"\n📊 Анализ трендов для {name}...")
                    report = self.trend_reporter.analyze_project_trends(name, self.projects[name]['files'])
                    print("\n" + report)
                    save = input("\n💾 Сохранить отчет? (y/n): ").strip().lower()
                    if save == 'y':
                        filepath = self.trend_reporter.save_trend_report(name, report)
                        print(f"✅ Отчет сохранен: {filepath}")
                else:
                    print("❌ Проект не найден")
            elif choice == '2':
                print("\n📊 Генерация еженедельного отчета...")
                filepath, report = self.trend_reporter.generate_weekly_trend_report()
                print("\n" + report[:1000] + "...\n")
                print(f"✅ Полный отчет сохранен: {filepath}")
            elif choice == '3':
                proj_type = input("Тип проекта (python/web/data/ml/etc): ").strip()
                rec = self.trend_reporter.get_technology_stack_recommendation(proj_type)
                print(f"\n📋 РЕКОМЕНДАЦИИ:\n{rec}")
            elif choice == '4':
                trends = self.trend_reporter.get_github_trends()
                print("\n🔥 GITHUB ТРЕНДЫ:")
                for i, t in enumerate(trends[:10], 1):
                    print(f"{i}. {t['full_name']} - ⭐ {t['stars']}")
                    if t.get('description'):
                        print(f"   {t['description'][:100]}")
            elif choice == '5':
                trends = self.trend_reporter.get_pypi_trends()
                print("\n📦 POPULAR PYPI PACKAGES:")
                for i, t in enumerate(trends[:10], 1):
                    print(f"{i}. {t['name']}")
            elif choice == '6':
                break
    
    def integration_menu(self):
        if not self.integration:
            print("❌ Интеграции не доступны")
            return
        while True:
            print("\n" + "="*40)
            print("🔌 ИНТЕГРАЦИИ")
            print("="*40)
            print("1. Настроить интеграции для проекта")
            print("2. Создать GitHub репозиторий")
            print("3. Создать Dockerfile")
            print("4. Открыть в VS Code")
            print("5. Отправить уведомление в Slack")
            print("6. Создать задачу в Jira/Trello")
            print("7. Статус интеграций")
            print("8. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    results = self.integration.setup_project_integrations(
                        self.projects[name]['path'], name
                    )
                    print("\n📋 Результаты:")
                    for r in results:
                        print(f"  {r}")
                else:
                    print("❌ Проект не найден")
            elif choice == '2':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    if self.integration.github.token:
                        url = self.integration.github.create_repo(
                            name, f"AI project {name}"
                        )
                        if url:
                            print(f"✅ Репозиторий создан: {url}")
                        else:
                            print("❌ Ошибка создания репозитория")
                    else:
                        print("❌ GitHub токен не настроен")
                else:
                    print("❌ Проект не найден")
            elif choice == '3':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    proj_type = input("Тип проекта (python/node/default): ").strip()
                    dockerfile = self.integration.docker.create_dockerfile(
                        self.projects[name]['path'], proj_type
                    )
                    print(f"✅ Dockerfile создан: {dockerfile}")
                else:
                    print("❌ Проект не найден")
            elif choice == '4':
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    if self.integration.vscode.open_in_vscode(self.projects[name]['path']):
                        print(f"✅ VS Code открыт")
                    else:
                        print("❌ Не удалось открыть VS Code")
                else:
                    print("❌ Проект не найден")
            elif choice == '5':
                message = input("Сообщение для Slack: ").strip()
                if self.integration.slack.send_message(message):
                    print("✅ Сообщение отправлено")
                else:
                    print("❌ Ошибка отправки")
            elif choice == '6':
                print("\nВыберите систему:")
                print("1. Jira")
                print("2. Trello")
                task_choice = input("👉 ").strip()
                summary = input("Краткое описание задачи: ").strip()
                description = input("Подробное описание: ").strip()
                if task_choice == '1' and self.integration.jira.auth:
                    project = input("Jira проект: ").strip()
                    issue = self.integration.jira.create_issue(project, summary, description)
                    if issue:
                        print(f"✅ Задача создана: {issue}")
                    else:
                        print("❌ Ошибка создания")
                elif task_choice == '2' and self.integration.trello.auth:
                    boards = self.integration.trello.get_boards()
                    if boards:
                        print("\nДоступные доски:")
                        for b in boards[:5]:
                            print(f"  {b['id']}: {b['name']}")
                        list_id = input("ID списка: ").strip()
                        url = self.integration.trello.create_card(list_id, summary, description)
                        if url:
                            print(f"✅ Карточка создана: {url}")
                        else:
                            print("❌ Ошибка создания")
            elif choice == '7':
                print("\n📊 СТАТУС ИНТЕГРАЦИЙ:")
                print(f"  GitHub: {'✅' if self.integration.github.token else '❌'}")
                print(f"  GitLab: {'✅' if self.integration.gitlab.token else '❌'}")
                print(f"  Jira: {'✅' if self.integration.jira.auth else '❌'}")
                print(f"  Trello: {'✅' if self.integration.trello.auth else '❌'}")
                print(f"  Slack: {'✅' if self.integration.slack.webhook_url else '❌'}")
                print(f"  VS Code: {'✅' if self.integration.vscode.vscode_path else '❌'}")
                print(f"  Docker: {'✅' if self.integration.docker.docker_available else '❌'}")
            elif choice == '8':
                break
    
    def learning_menu(self):
        if not self.learner:
            print("❌ Система самообучения не доступна")
            return
        while True:
            print("\n" + "="*40)
            print("🧠 САМООБУЧЕНИЕ")
            print("="*40)
            print("1. Показать статистику обучения")
            print("2. Получить рекомендации")
            print("3. Анализ ошибок")
            print("4. Улучшения системы")
            print("5. Адаптировать под пользователя")
            print("6. Обучить на проектах")
            print("7. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                print(self.learner.get_learning_stats())
            elif choice == '2':
                proj_type = input("Тип проекта (python/javascript/html): ").strip()
                rec = self.learner.get_recommendations(proj_type)
                print(f"\n📝 РЕКОМЕНДАЦИИ:\n{rec}")
            elif choice == '3':
                if self.learner.mistakes:
                    print("\n❌ ПОСЛЕДНИЕ ОШИБКИ:")
                    for i, m in enumerate(self.learner.mistakes[-5:], 1):
                        print(f"{i}. {m['project']}: {m['error'][:100]}")
                    idx = input("\nВыберите номер для анализа (enter - пропустить): ").strip()
                    if idx:
                        try:
                            mistake = self.learner.mistakes[-int(idx)]
                            lesson = self.learner.learn_from_mistake(mistake['error'])
                            print(f"\n📚 УРОК:\n{lesson}")
                        except:
                            print("❌ Неверный номер")
                else:
                    print("✅ Ошибок нет")
            elif choice == '4':
                suggestions = self.learner.get_improvement_suggestions()
                print(f"\n💡 ПРЕДЛОЖЕНИЯ ПО УЛУЧШЕНИЮ:\n{suggestions}")
            elif choice == '5':
                feedback = input("Ваш отзыв о работе системы: ").strip()
                self.learner.adapt_to_user(feedback)
                print("✅ Система адаптирована под ваши предпочтения")
            elif choice == '6':
                print("\n🔄 Обучение на проектах...")
                for name, data in self.projects.items():
                    print(f"  Обработка: {name}")
                    self.learner.learn_from_project(name, data, "✅ Успешно")
                print("✅ Обучение завершено")
            elif choice == '7':
                break
    
    def feedback_menu(self):
        if not self.feedback:
            print("❌ Система обратной связи не доступна")
            return
        while True:
            print("\n" + "="*40)
            print("💬 ОБРАТНАЯ СВЯЗЬ")
            print("="*40)
            print("1. Оставить отзыв")
            print("2. Оценить работу")
            print("3. Внести предложение")
            print("4. Посмотреть отчет")
            print("5. План улучшений")
            print("6. Уровень удовлетворенности")
            print("7. Голосовать за предложения")
            print("8. Назад")
            print("="*40)
            choice = input("\n👉 Выбор: ").strip()
            if choice == '1':
                message = input("Ваш отзыв: ").strip()
                context = input("Контекст (enter для пропуска): ").strip()
                fb_id = self.feedback.add_feedback('user', message, context)
                print(f"✅ Спасибо за отзыв! ID: {fb_id}")
            elif choice == '2':
                rating = input("Оценка (1-5): ").strip()
                try:
                    rating = int(rating)
                    if 1 <= rating <= 5:
                        comment = input("Комментарий (enter для пропуска): ").strip()
                        self.feedback.add_rating('user', rating, comment)
                        print("✅ Спасибо за оценку!")
                except:
                    print("❌ Неверная оценка")
            elif choice == '3':
                suggestion = input("Ваше предложение: ").strip()
                category = input("Категория (feature/improvement/bug): ").strip() or 'feature'
                sug_id = self.feedback.add_suggestion('user', suggestion, category)
                print(f"✅ Спасибо за предложение! ID: {sug_id}")
            elif choice == '4':
                print(self.feedback.get_feedback_report())
            elif choice == '5':
                plan = self.feedback.get_improvement_plan()
                print(f"\n📋 ПЛАН УЛУЧШЕНИЙ:\n{plan}")
                if self.feedback.improvements['planned']:
                    print("\n📌 Запланированные улучшения:")
                    for i, imp in enumerate(self.feedback.improvements['planned']):
                        print(f"{i}. {imp.get('analysis', '')[:100]}...")
                    idx = input("\nОтметить как реализованное (номер): ").strip()
                    try:
                        if self.feedback.implement_improvement(int(idx)):
                            print("✅ Улучшение отмечено как реализованное")
                    except:
                        pass
            elif choice == '6':
                satisfaction = self.feedback.get_user_satisfaction()
                print(f"\n📊 Уровень удовлетворенности: {satisfaction}")
            elif choice == '7':
                if self.feedback.suggestions:
                    print("\n💡 ПРЕДЛОЖЕНИЯ:")
                    for s in self.feedback.suggestions[-10:]:
                        print(f"ID:{s['id']} [{s.get('votes',0)}⭐] {s['suggestion'][:100]}")
                    sug_id = input("\nID предложения для голосования: ").strip()
                    try:
                        if self.feedback.vote_suggestion(int(sug_id)):
                            print("✅ Голос учтен")
                    except:
                        print("❌ Неверный ID")
                else:
                    print("📭 Нет предложений")
            elif choice == '8':
                break
    
    def run_multi_agent(self):
        try:
            from agents import Orchestrator
            ai = Orchestrator()
            while True:
                print("\n" + "="*50)
                print("🤖 МНОГОАГЕНТНАЯ СИСТЕМА")
                print("="*50)
                print("1. Выполнить задачу")
                print("2. Статистика агентов")
                print("3. Коллаборация агентов")
                print("4. Назад")
                print("="*50)
                choice = input("\n👉 Выбор: ").strip()
                if choice == '1':
                    task = input("Задача: ").strip()
                    result = ai.delegate(task)
                    print(f"\n✅ Результат:\n{result}")
                elif choice == '2':
                    ai.stats()
                elif choice == '3':
                    task = input("Задача: ").strip()
                    agents = input("Агенты (через запятую): ").strip().split(',')
                    result = ai.collaborate(task, [a.strip() for a in agents])
                    print(f"\n✅ Результат:\n{result}")
                elif choice == '4':
                    break
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    def show_memory_stats(self):
        if not self.memory:
            print("❌ Память не инициализирована")
            return
        stats = self.memory.get_statistics()
        print("\n📊 СТАТИСТИКА ПАМЯТИ")
        print("="*40)
        print(f"📁 Проектов: {stats['total_projects']}")
        print(f"📝 Анализов: {stats['total_analyses']}")
        if stats.get('last_scan'):
            print(f"🕐 Последнее сканирование: {stats['last_scan']}")
    
    def clear_old_memory(self):
        if not self.memory:
            print("❌ Память не инициализирована")
            return
        deleted = self.memory.clear_old_memory(30)
        print(f"🧹 Удалено проектов: {deleted}")
    
    def run(self):
        while self.running:
            print("\n" + "="*40)
            print("ГЛАВНОЕ МЕНЮ:")
            print("1.  Показать проекты")
            print("2.  Анализ проекта")
            print("3.  ГЛУБОКИЙ АНАЛИЗ")
            print("4.  Анализ всех проектов")
            print("5.  Анализ любого проекта")
            print("6.  Анализ TODO.md")
            print("7.  Создать TODO.md")
            print("8.  Обновить TODO.md")
            print("9.  🏗️ Создать структуру")
            print("10. 💻 Генерация кода")
            print("11. 📖 Объяснить код")
            print("12. 🤖 Многоагентная система")
            print("13. 📊 ОТЧЕТЫ")
            print("14. 🧠 Статистика памяти")
            print("15. 🧹 Очистить память")
            print("16. 🔒 БЕЗОПАСНОСТЬ")
            print("17. 🚀 ПРОИЗВОДИТЕЛЬНОСТЬ")
            print("18. 🌐 ВЕБ-ИНТЕРФЕЙС")
            print("19. 🔄 АВТОМАТИЗАЦИЯ")
            print("20. 🐛 ПОИСК ОШИБОК")
            print("21. 🚀 ОПТИМИЗАЦИЯ")
            print("22. 🔍 ПОИСК МАТЕРИАЛОВ")
            print("23. 📈 ОТЧЕТЫ О ТРЕНДАХ")
            print("24. 🔌 ИНТЕГРАЦИИ")
            print("25. 🧠 САМООБУЧЕНИЕ")
            print("26. 💬 ОБРАТНАЯ СВЯЗЬ")
            print("27. 🚪 Выход")
            print("="*40)
            
            choice = input("\n👉 Выбор: ").strip()
            
            if choice == "1":
                self.list_projects()
            elif choice == "2":
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    result = self.analyze_project(name)
                    if self.learner:
                        self.learner.learn_from_project(name, self.projects[name], result)
                else:
                    print("❌ Проект не найден")
            elif choice == "3":
                self.list_projects()
                name = input("Имя проекта для глубокого анализа: ").strip()
                if name in self.projects:
                    self.deep_analyze_project(name)
                else:
                    print("❌ Проект не найден")
            elif choice == "4":
                for name in self.projects:
                    self.analyze_project(name)
                    time.sleep(2)
            elif choice == "5":
                self.analyze_any_project()
            elif choice == "6":
                self.analyze_todo()
            elif choice == "7":
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    self.create_todo(self.projects[name]["path"], name)
                else:
                    print("❌ Проект не найден")
            elif choice == "8":
                self.update_todo()
            elif choice == "9":
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    self.auto_structure(name)
                else:
                    print("❌ Проект не найден")
            elif choice == "10":
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    self.generate_project_code(name)
                else:
                    print("❌ Проект не найден")
            elif choice == "11":
                self.list_projects()
                name = input("Имя проекта: ").strip()
                if name in self.projects:
                    self.explain_code_file(name)
                else:
                    print("❌ Проект не найден")
            elif choice == "12":
                self.run_multi_agent()
            elif choice == "13":
                self.generate_reports()
            elif choice == "14":
                self.show_memory_stats()
            elif choice == "15":
                self.clear_old_memory()
            elif choice == "16":
                self.security_menu()
            elif choice == "17":
                self.performance_menu()
            elif choice == "18":
                self.web_menu()
            elif choice == "19":
                self.automation_menu()
            elif choice == "20":
                self.error_detection_menu()
            elif choice == "21":
                self.optimization_menu()
            elif choice == "22":
                self.search_menu()
            elif choice == "23":
                self.trend_menu()
            elif choice == "24":
                self.integration_menu()
            elif choice == "25":
                self.learning_menu()
            elif choice == "26":
                self.feedback_menu()
            elif choice == "27":
                self.running = False
                if self.memory:
                    self.memory.save()
                if self.security:
                    self.security.save_config()
                if self.scheduler:
                    self.scheduler.stop()
                if self.daily_searcher:
                    self.daily_searcher.stop_daily_search()
                if self.web and self.web.running:
                    self.web.stop()
                if self.optimizer:
                    self.optimizer.monitor.stop_monitoring()
                if self.learner:
                    self.learner.save_knowledge()
                    self.learner.save_patterns()
                    self.learner.save_successes()
                    self.learner.save_mistakes()
                if self.feedback:
                    self.feedback.save_feedback()
                    self.feedback.save_suggestions()
                    self.feedback.save_ratings()
                    self.feedback.save_improvements()
                print("👋 До свидания!")
                break
            else:
                print("❌ Неверный выбор")

if __name__ == "__main__":
    system = AISystem()
    system.run()
