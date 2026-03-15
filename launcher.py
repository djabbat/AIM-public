#!/usr/bin/env python3
import os
import sys

def dialogue_mode_menu():
    """Submenu: choose dialogue mode with the system."""
    while True:
        print("\n" + "="*60)
        print("💬 ВЫБОР РЕЖИМА ДИАЛОГА")
        print("="*60)
        print("1. Анализ историй болезней пациентов (д-р Ткемаладзе)")
        print("2. Мультиязычный чат (RU/EN/KA/KZ)")
        print("3. Общий AI-ассистент (вопросы и ответы)")
        print("4. Назад")
        print("="*60)

        choice = input("\n👉 Режим: ").strip()

        if choice == '1':
            os.system("python3 patient_analysis.py")
        elif choice == '2':
            os.system("python3 multilingual_system.py")
        elif choice == '3':
            os.system("python3 ai_system.py")
        elif choice == '4':
            break
        else:
            print("❌ Неверный выбор")

        input("\nНажмите Enter для продолжения...")

def main():
    while True:
        print("\n" + "="*60)
        print("🤖 AI СИСТЕМА - ГЛАВНОЕ МЕНЮ")
        print("="*60)
        print("1. Выбор режима диалога с системой")
        print("2. Анализатор проекта (по пути)")
        print("3. Мультиязычный чат")
        print("4. TODO анализатор")
        print("5. Выход")
        print("="*60)

        choice = input("\n👉 Выбор: ").strip()

        if choice == '1':
            dialogue_mode_menu()
        elif choice == '2':
            path = input("Введите путь к проекту: ").strip()
            if os.path.exists(path):
                os.system(f"python3 todo_analyzer.py '{path}'")
            else:
                print("❌ Путь не существует")
        elif choice == '3':
            os.system("python3 multilingual_system.py")
        elif choice == '4':
            path = input("Введите путь к проекту: ").strip()
            if os.path.exists(path):
                os.system(f"python3 todo_analyzer.py '{path}'")
            else:
                print("❌ Путь не существует")
        elif choice == '5':
            print("👋 До свидания!")
            break
        else:
            print("❌ Неверный выбор")

        input("\nНажмите Enter для продолжения...")

if __name__ == "__main__":
    main()
