#!/usr/bin/env python3
import os
import sys

def main():
    print("\n" + "="*60)
    print("🤖 МНОГОАГЕНТНАЯ AI СИСТЕМА")
    print("="*60)
    print("1. Project Manager (следит за папками на Desktop)")
    print("2. Мультиязычный чат (русский, казахский, грузинский, английский)")
    print("3. Выход")
    print("="*60)
    
    choice = input("\n👉 Выбор: ").strip()
    
    if choice == '1':
        from project_manager import ProjectManager
        ProjectManager().run()
    elif choice == '2':
        from multilingual_system import MultiLangSystem
        MultiLangSystem().chat()
    elif choice == '3':
        print("👋 До свидания!")
        sys.exit(0)
    else:
        print("❌ Неверный выбор")
        main()

if __name__ == "__main__":
    main()
