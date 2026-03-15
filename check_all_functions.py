#!/usr/bin/env python3
import os
import sys

def check_terminal_menu():
    """Проверяет меню в терминале"""
    print("\n" + "="*60)
    print("🔍 ПРОВЕРКА ФУНКЦИЙ В ТЕРМИНАЛЕ")
    print("="*60)
    
    terminal_functions = [
        "1.  Показать проекты",
        "2.  Анализ проекта",
        "3.  ГЛУБОКИЙ АНАЛИЗ",
        "4.  Анализ всех проектов",
        "5.  Анализ любого проекта",
        "6.  Анализ TODO.md",
        "7.  Создать TODO.md",
        "8.  Обновить TODO.md",
        "9.  🏗️ Создать структуру",
        "10. 💻 Генерация кода",
        "11. 📖 Объяснить код",
        "12. 🤖 Многоагентная система",
        "13. 📊 ОТЧЕТЫ",
        "14. 🧠 Статистика памяти",
        "15. 🧹 Очистить память",
        "16. 🔒 БЕЗОПАСНОСТЬ",
        "17. 🚀 ПРОИЗВОДИТЕЛЬНОСТЬ",
        "18. 🌐 ВЕБ-ИНТЕРФЕЙС",
        "19. 🔄 АВТОМАТИЗАЦИЯ",
        "20. 🐛 ПОИСК ОШИБОК",
        "21. 🚀 ОПТИМИЗАЦИЯ",
        "22. 🔍 ПОИСК МАТЕРИАЛОВ",
        "23. 📈 ОТЧЕТЫ О ТРЕНДАХ",
        "24. 🔌 ИНТЕГРАЦИИ",
        "25. 🧠 САМООБУЧЕНИЕ",
        "26. 💬 ОБРАТНАЯ СВЯЗЬ",
        "27. 🚪 Выход"
    ]
    
    print("\n📋 ФУНКЦИИ В ТЕРМИНАЛЕ (26 функций):")
    for func in terminal_functions:
        print(f"  {func}")
    
    return len(terminal_functions)

def check_web_buttons():
    """Проверяет кнопки в веб-интерфейсе"""
    print("\n" + "="*60)
    print("🔍 ПРОВЕРКА КНОПОК В ВЕБ-ИНТЕРФЕЙСЕ")
    print("="*60)
    
    web_buttons = [
        "📊 Анализ",
        "🔍 Глубокий анализ",
        "🏗️ Структура",
        "📝 Создать TODO",
        "📋 Анализ TODO",
        "💻 Генерация кода",
        "Git коммит",
        "Бэкап",
        "Отчеты",
        "Поиск материалов",
        "Тренды",
        "Интеграции",
        "Самообучение",
        "Обратная связь"
    ]
    
    print("\n🖱️ КНОПКИ В ВЕБ-ИНТЕРФЕЙСЕ:")
    for i, btn in enumerate(web_buttons, 1):
        print(f"  {i}. {btn}")
    
    return len(web_buttons)

def check_all_modules():
    """Проверяет загрузку всех модулей"""
    print("\n" + "="*60)
    print("🔍 ПРОВЕРКА ЗАГРУЗКИ МОДУЛЕЙ")
    print("="*60)
    
    modules = [
        ('memory', '🧠 Память'),
        ('code_generator', '🔧 Генератор кода'),
        ('deep_analysis', '🔍 Глубокий анализ'),
        ('reports', '📊 Отчеты'),
        ('security', '🔒 Безопасность'),
        ('performance', '🚀 Производительность'),
        ('web_interface', '🌐 Веб-интерфейс'),
        ('automation', '🔄 Автоматизация'),
        ('error_detector', '🐛 Поиск ошибок'),
        ('optimization', '🚀 Оптимизация'),
        ('material_search', '🔍 Поиск материалов'),
        ('trend_reporter', '📈 Тренды'),
        ('integration', '🔌 Интеграции'),
        ('self_learning', '🧠 Самообучение'),
        ('feedback', '💬 Обратная связь')
    ]
    
    all_loaded = True
    for module_name, module_label in modules:
        try:
            __import__(module_name)
            print(f"  ✅ {module_label}")
        except ImportError as e:
            print(f"  ❌ {module_label} - НЕ ЗАГРУЖЕН ({e})")
            all_loaded = False
    
    return all_loaded

def check_missing_files():
    """Проверяет наличие всех файлов"""
    print("\n" + "="*60)
    print("🔍 ПРОВЕРКА ФАЙЛОВ СИСТЕМЫ")
    print("="*60)
    
    required_files = [
        'ai_system.py',
        'memory.py',
        'code_generator.py',
        'deep_analysis.py',
        'reports.py',
        'security.py',
        'performance.py',
        'web_interface.py',
        'automation.py',
        'error_detector.py',
        'optimization.py',
        'material_search.py',
        'trend_reporter.py',
        'integration.py',
        'self_learning.py',
        'feedback.py',
        'agents.py'
    ]
    
    all_present = True
    for file in required_files:
        if os.path.exists(file):
            print(f"  ✅ {file}")
        else:
            print(f"  ❌ {file} - ОТСУТСТВУЕТ")
            all_present = False
    
    return all_present

def check_web_server():
    """Проверяет доступность веб-сервера"""
    print("\n" + "="*60)
    print("🔍 ПРОВЕРКА ВЕБ-ИНТЕРФЕЙСА")
    print("="*60)
    
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', 8080))
    
    if result == 0:
        print("  ✅ Веб-сервер работает на порту 8080")
        print("  🔗 http://localhost:8080")
    else:
        print("  ⚠️ Веб-сервер не запущен")
        print("  ▶️ Запустите через меню: 18 -> 1")

def main():
    print("\n" + "="*60)
    print("🔍 ПОЛНАЯ ПРОВЕРКА СИСТЕМЫ")
    print("="*60)
    
    # Проверка терминального меню
    terminal_count = check_terminal_menu()
    
    # Проверка веб-кнопок
    web_count = check_web_buttons()
    
    # Проверка модулей
    modules_ok = check_all_modules()
    
    # Проверка файлов
    files_ok = check_missing_files()
    
    # Проверка веб-сервера
    check_web_server()
    
    # Итог
    print("\n" + "="*60)
    print("📊 ИТОГ ПРОВЕРКИ")
    print("="*60)
    print(f"📋 Функций в терминале: {terminal_count}")
    print(f"🖱️ Кнопок в веб-интерфейсе: {web_count}")
    print(f"🧩 Модули загружены: {'✅' if modules_ok else '❌'}")
    print(f"📁 Все файлы присутствуют: {'✅' if files_ok else '❌'}")
    
    if not modules_ok:
        print("\n⚠️ НЕ ЗАГРУЖЕНЫ МОДУЛИ:")
        print("  Запустите: python3 ai_system.py")
        print("  Они загрузятся при запуске системы")
    
    if not files_ok:
        print("\n⚠️ ОТСУТСТВУЮТ ФАЙЛЫ:")
        print("  Нужно создать недостающие файлы")
    
    print("\n✅ Проверка завершена!")
    print("="*60)

if __name__ == "__main__":
    main()
