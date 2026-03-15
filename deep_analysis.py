#!/usr/bin/env python3
import os
import ollama
from datetime import datetime

class DeepAnalyzer:
    def __init__(self, model="llama3.2"):
        self.model = model
    
    def deep_analysis(self, project_name, project_path, files, memory=None):
        print(f"\n🔍 ГЛУБОКИЙ АНАЛИЗ: {project_name}")
        
        prompt = f"""Проведи глубокий анализ проекта '{project_name}'.
Файлы: {files[:15]}
Опиши архитектуру, найди проблемы, предложи улучшения."""
        
        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            analysis = response['message']['content']
            
            analysis_file = os.path.join(project_path, '_deep_analysis.md')
            with open(analysis_file, 'w', encoding='utf-8') as f:
                f.write(f"# ГЛУБОКИЙ АНАЛИЗ: {project_name}\n")
                f.write(f"Дата: {datetime.now()}\n")
                f.write("="*50 + "\n\n")
                f.write(analysis)
            
            print(f"✅ Глубокий анализ сохранен")
            return analysis
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return None
