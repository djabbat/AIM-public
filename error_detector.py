#!/usr/bin/env python3
import os
import ast
from datetime import datetime
import ollama

class ErrorDetector:
    def __init__(self, model="llama3.2"):
        self.model = model
        self.errors_found = 0
        self.warnings_found = 0
    
    def analyze_file(self, file_path):
        if not os.path.exists(file_path):
            return None
        
        errors = []
        warnings = []
        
        if file_path.endswith('.py'):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                ast.parse(content)
            except SyntaxError as e:
                errors.append({
                    'line': e.lineno,
                    'message': str(e)
                })
            except Exception as e:
                errors.append({
                    'line': 0,
                    'message': str(e)
                })
        
        return {
            'file': file_path,
            'errors': errors,
            'warnings': warnings
        }
    
    def analyze_project(self, project_path):
        results = {
            'project': project_path,
            'files': [],
            'total_errors': 0,
            'total_warnings': 0
        }
        
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ['venv', '__pycache__', '.git']]
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    file_result = self.analyze_file(file_path)
                    if file_result:
                        results['files'].append(file_result)
                        results['total_errors'] += len(file_result['errors'])
        
        return results
    
    def print_results(self, results):
        print(f"\n📊 РЕЗУЛЬТАТЫ АНАЛИЗА: {results['project']}")
        print(f"Всего ошибок: {results['total_errors']}")
        for file_result in results['files']:
            if file_result['errors']:
                print(f"\n{os.path.basename(file_result['file'])}:")
                for e in file_result['errors']:
                    print(f"  • {e['message']}")
