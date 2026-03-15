#!/usr/bin/env python3
import os
import fnmatch

class SecurityManager:
    """Управление безопасностью и игнорированием файлов"""
    
    def __init__(self):
        # Стандартные паттерны для игнорирования
        self.ignore_patterns = [
            # Системные папки
            '.git',
            '.svn',
            '.hg',
            '.idea',
            '.vscode',
            '.DS_Store',
            
            # Зависимости
            'node_modules',
            'venv',
            'env',
            '.venv',
            'virtualenv',
            '__pycache__',
            '*.pyc',
            '*.pyo',
            '*.pyd',
            '.pytest_cache',
            '.coverage',
            'htmlcov',
            
            # Кэш
            '.cache',
            '.mypy_cache',
            '.ruff_cache',
            '.hypothesis',
            
            # Логи
            '*.log',
            'logs',
            
            # Временные файлы
            '*.tmp',
            '*.temp',
            '*.swp',
            '*.swo',
            '*~',
            
            # Секреты
            '.env',
            '.env.*',
            '*.key',
            '*.pem',
            '*.crt',
            'secrets.*',
            
            # Бинарные файлы
            '*.exe',
            '*.dll',
            '*.so',
            '*.dylib',
            '*.bin',
            
            # Архивы
            '*.zip',
            '*.tar',
            '*.gz',
            '*.rar',
            '*.7z',
            
            # Медиа (большие файлы)
            '*.mp4',
            '*.avi',
            '*.mov',
            '*.mkv',
            '*.mp3',
            '*.wav',
            '*.flac',
            '*.jpg',
            '*.jpeg',
            '*.png',
            '*.gif',
            '*.bmp',
            '*.ico',
            '*.svg',
            
            # Документы (большие)
            '*.pdf',
            '*.epub',
            '*.mobi',
            
            # Базы данных
            '*.db',
            '*.sqlite',
            '*.sqlite3',
            
            # Виртуальные машины
            '*.iso',
            '*.vmdk',
            '*.vdi',
            '*.ova',
            
            # Docker
            '*.img',
            'docker-overlay2',
            
            # Результаты
            'results',
            'output',
            'build',
            'dist',
            '*.egg-info',
        ]
        
        # Максимальный размер файла для анализа (10 MB)
        self.max_file_size = 10 * 1024 * 1024
        
        # Максимальное количество файлов для анализа
        self.max_files_per_project = 100
        
        # Лимиты на анализ
        self.analysis_limits = {
            'max_depth': 10,  # максимальная глубина рекурсии
            'max_time': 60,   # максимальное время анализа (секунд)
            'max_lines_per_file': 5000,  # максимальное строк в файле
        }
    
    def should_ignore(self, path):
        """Проверяет, нужно ли игнорировать файл/папку"""
        basename = os.path.basename(path)
        
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(basename, pattern):
                return True
            
            # Проверяем путь
            if fnmatch.fnmatch(path, f'*/{pattern}/*'):
                return True
            if fnmatch.fnmatch(path, f'*/{pattern}'):
                return True
        
        return False
    
    def add_ignore_pattern(self, pattern):
        """Добавляет новый паттерн для игнорирования"""
        if pattern not in self.ignore_patterns:
            self.ignore_patterns.append(pattern)
            print(f"✅ Добавлен паттерн: {pattern}")
    
    def remove_ignore_pattern(self, pattern):
        """Удаляет паттерн"""
        if pattern in self.ignore_patterns:
            self.ignore_patterns.remove(pattern)
            print(f"✅ Удален паттерн: {pattern}")
    
    def is_file_analyzable(self, filepath):
        """Проверяет, можно ли анализировать файл"""
        # Проверяем размер
        try:
            size = os.path.getsize(filepath)
            if size > self.max_file_size:
                return False, f"Файл слишком большой ({size/1024/1024:.1f} MB)"
        except:
            return False, "Не удалось получить размер"
        
        # Проверяем расширение
        ext = os.path.splitext(filepath)[1].lower()
        text_extensions = ['.txt', '.md', '.py', '.js', '.html', '.css', 
                          '.json', '.xml', '.yaml', '.yml', '.ini', '.cfg',
                          '.conf', '.sh', '.bash', '.zsh', '.fish', '.ps1',
                          '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs',
                          '.php', '.rb', '.pl', '.lua', '.r', '.sql']
        
        if ext and ext not in text_extensions and not ext:
            return False, "Нетекстовый файл"
        
        return True, "OK"
    
    def filter_project_files(self, project_path):
        """Фильтрует файлы проекта, исключая игнорируемые"""
        valid_files = []
        ignored_files = []
        large_files = []
        
        for root, dirs, files in os.walk(project_path):
            # Фильтруем папки на лету
            dirs[:] = [d for d in dirs if not self.should_ignore(os.path.join(root, d))]
            
            for file in files:
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, project_path)
                
                if self.should_ignore(filepath):
                    ignored_files.append(rel_path)
                    continue
                
                analyzable, reason = self.is_file_analyzable(filepath)
                if analyzable:
                    valid_files.append(rel_path)
                else:
                    large_files.append((rel_path, reason))
        
        # Ограничиваем количество
        if len(valid_files) > self.max_files_per_project:
            valid_files = valid_files[:self.max_files_per_project]
        
        return {
            'valid': valid_files,
            'ignored': ignored_files,
            'large': large_files
        }
    
    def get_project_stats(self, project_path):
        """Возвращает статистику по проекту"""
        filtered = self.filter_project_files(project_path)
        
        total_files = len(filtered['valid']) + len(filtered['ignored']) + len(filtered['large'])
        
        stats = {
            'total': total_files,
            'analyzed': len(filtered['valid']),
            'ignored': len(filtered['ignored']),
            'large': len(filtered['large']),
            'ignored_list': filtered['ignored'][:10],
            'large_list': filtered['large'][:5]
        }
        
        return stats
    
    def save_config(self, filepath="~/AIM/security_config.json"):
        """Сохраняет конфигурацию"""
        import json
        
        config = {
            'ignore_patterns': self.ignore_patterns,
            'max_file_size': self.max_file_size,
            'max_files_per_project': self.max_files_per_project,
            'analysis_limits': self.analysis_limits
        }
        
        filepath = os.path.expanduser(filepath)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        
        print(f"✅ Конфигурация сохранена: {filepath}")
    
    def load_config(self, filepath="~/AIM/security_config.json"):
        """Загружает конфигурацию"""
        import json
        
        filepath = os.path.expanduser(filepath)
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            self.ignore_patterns = config.get('ignore_patterns', self.ignore_patterns)
            self.max_file_size = config.get('max_file_size', self.max_file_size)
            self.max_files_per_project = config.get('max_files_per_project', self.max_files_per_project)
            self.analysis_limits = config.get('analysis_limits', self.analysis_limits)
            
            print(f"✅ Конфигурация загружена: {filepath}")
            return True
        return False
    
    def print_ignore_list(self):
        """Показывает список игнорируемых паттернов"""
        print("\n📋 ИГНОРИРУЕМЫЕ ПАТТЕРНЫ:")
        print("="*40)
        
        groups = {
            'Системные': [],
            'Зависимости': [],
            'Кэш': [],
            'Секреты': [],
            'Медиа': [],
            'Другое': []
        }
        
        for pattern in sorted(self.ignore_patterns):
            if any(s in pattern for s in ['.git', '.svn', '.idea']):
                groups['Системные'].append(pattern)
            elif any(s in pattern for s in ['node_modules', 'venv', '__pycache__']):
                groups['Зависимости'].append(pattern)
            elif any(s in pattern for s in ['.cache', '.pytest', '__pycache__']):
                groups['Кэш'].append(pattern)
            elif any(s in pattern for s in ['.env', 'key', 'pem', 'secret']):
                groups['Секреты'].append(pattern)
            elif any(s in pattern for s in ['.jpg', '.png', '.mp4', '.mp3']):
                groups['Медиа'].append(pattern)
            else:
                groups['Другое'].append(pattern)
        
        for group, patterns in groups.items():
            if patterns:
                print(f"\n{group}:")
                for p in patterns[:10]:
                    print(f"  • {p}")

# Тестирование
if __name__ == "__main__":
    sec = SecurityManager()
    sec.print_ignore_list()
    
    # Тест на текущей папке
    print("\n🔍 ТЕСТ ФИЛЬТРАЦИИ")
    print("="*40)
    
    stats = sec.get_project_stats(".")
    print(f"Всего файлов: {stats['total']}")
    print(f"Будут проанализированы: {stats['analyzed']}")
    print(f"Игнорируется: {stats['ignored']}")
    print(f"Слишком большие: {stats['large']}")
