# AIM v7.0

Гибридный медицинский ассистент. 4 LLM-провайдера · 9 языков · SQLite.

## Провайдеры

| Провайдер | Задача | Ключ |
|-----------|--------|------|
| Groq | Быстрые ответы (<1 сек) | `GROQ_API_KEY` |
| DeepSeek | Рассуждения, диагностика | `DEEPSEEK_API_KEY` |
| KIMI | Длинный контекст, PDF | `KIMI_API_KEY` |
| Qwen | AR / ZH / KA / KZ / DA | `QWEN_API_KEY` |

## Запуск

```bash
./start.sh
```

## Ключи (`~/.aim_env`)

```
DEEPSEEK_API_KEY=...
KIMI_API_KEY=...
QWEN_API_KEY=...
GROQ_API_KEY=...
```

## Языки

`ru · en · fr · es · ar · zh · ka · kz · da`
