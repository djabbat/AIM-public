#!/usr/bin/env python3
"""
Fine-Tune Whisper для грузинского языка (LoRA / CPU-friendly).

Подготовка данных:
  1. Положи аудиофайлы (.wav .mp3 .m4a .ogg) в data/audio_ka/
  2. Для каждого аудио создай .txt с транскрипцией (то же имя, но .txt)
  3. Запусти: python whisper_finetune_ka.py --prepare

Запуск обучения:
  python whisper_finetune_ka.py --train          # CPU (медленно, но работает)
  python whisper_finetune_ka.py --train --epochs 5

После обучения:
  python whisper_finetune_ka.py --infer --audio "test.wav"  # тест

Требования:
  pip install torch transformers datasets peft accelerate soundfile librosa
"""

import argparse
import json
import os
import sys
import warnings
from pathlib import Path

import torch

warnings.filterwarnings("ignore")

# ─── конфиг ────────────────────────────────────────────────────────────────

BASE_MODEL = "openai/whisper-tiny"   # tiny/base/small/medium/large-v3
DATA_DIR = Path("data/audio_ka")
OUTPUT_DIR = Path("models/whisper-ka-lora")
CACHE_DIR = Path(".cache/huggingface")

# Параметры LoRA
LORA_R = 8
LORA_ALPHA = 16
LORA_DROPOUT = 0.1

TRAIN_BATCH_SIZE = 4       # для CPU — маленький батч
EVAL_BATCH_SIZE = 2
GRADIENT_ACCUMULATION = 4
LEARNING_RATE = 1e-4
MAX_STEPS = 500
WARMUP_STEPS = 50

SAMPLE_RATE = 16000
MAX_AUDIO_LEN = 30  # секунд


def prepare_dataset():
    """Подготовить датасет из аудио + txt файлов."""
    from datasets import Dataset, Audio, Features, Value

    audio_dir = DATA_DIR
    audio_files = sorted(audio_dir.glob("*.wav")) + \
                  sorted(audio_dir.glob("*.mp3")) + \
                  sorted(audio_dir.glob("*.m4a")) + \
                  sorted(audio_dir.glob("*.ogg")) + \
                  sorted(audio_dir.glob("*.flac"))

    if not audio_files:
        print(f"❌ Нет аудиофайлов в {audio_dir}/")
        print(f"   Положи туда .wav/.mp3/.m4a/.ogg с диктофонными записями")
        print(f"   Для каждого файла создай .txt с транскрипцией")
        return False

    data = {"audio": [], "text": []}
    missing = 0

    for af in audio_files:
        txt_path = af.with_suffix(".txt")
        if not txt_path.exists():
            # Пробуем .txt в том же месте
            alt_txt = af.parent / f"{af.stem}.txt"
            if alt_txt.exists():
                txt_path = alt_txt
            else:
                missing += 1
                continue

        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read().strip()

        if text:
            data["audio"].append(str(af.resolve()))
            data["text"].append(text)

    if missing:
        print(f"⚠ {missing} файлов без транскрипции (.txt)")

    if not data["audio"]:
        print("❌ Нет пар аудио+текст. Для каждого аудиофайла создай .txt")
        return False

    dataset = Dataset.from_dict(data)
    dataset = dataset.cast_column("audio", Audio(sampling_rate=SAMPLE_RATE))

    # Разделение
    split = dataset.train_test_split(test_size=0.1, seed=42)
    split["train"].save_to_disk(str(DATA_DIR / "dataset_train"))
    split["test"].save_to_disk(str(DATA_DIR / "dataset_test"))

    print(f"\n✅ Датасет готов:")
    print(f"   Train: {len(split['train'])} примеров")
    print(f"   Test:  {len(split['test'])} примеров")
    print(f"   Данные: {DATA_DIR}/dataset_*")
    return True


def train():
    """Запустить LoRA fine-tune Whisper."""
    from transformers import (
        WhisperForConditionalGeneration,
        WhisperProcessor,
        Seq2SeqTrainingArguments,
        Seq2SeqTrainer,
    )
    from datasets import load_from_disk, Audio, concatenate_datasets
    from peft import LoraConfig, get_peft_model, TaskType
    import evaluate

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\n🖥  Устройство: {device.upper()}")
    if device == "cpu":
        print("   ⚠ CPU обучение — медленно. Рекомендуется GPU.")

    # Проверка данных
    train_path = DATA_DIR / "dataset_train"
    test_path = DATA_DIR / "dataset_test"

    if not train_path.exists():
        print("❌ Датасет не найден. Сначала: python whisper_finetune_ka.py --prepare")
        return

    print(f"\n🔄 Загрузка датасета...")
    train_set = load_from_disk(str(train_path))
    test_set = load_from_disk(str(test_path))

    print(f"   Train: {len(train_set)} | Test: {len(test_set)}")

    # Загрузка модели и процессора
    print(f"\n🔄 Загрузка {BASE_MODEL}...")
    processor = WhisperProcessor.from_pretrained(
        BASE_MODEL, language="georgian", task="transcribe",
        cache_dir=str(CACHE_DIR)
    )
    model = WhisperForConditionalGeneration.from_pretrained(
        BASE_MODEL, cache_dir=str(CACHE_DIR)
    )

    # Заморозка encoder — тренируем только decoder + LoRA
    model.config.forced_decoder_ids = processor.get_decoder_prompt_ids(
        language="georgian", task="transcribe"
    )
    model.config.suppress_tokens = []

    # LoRA конфигурация
    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        target_modules=["q_proj", "v_proj", "k_proj", "out_proj",
                       "fc1", "fc2", "fc3"],
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type=TaskType.SEQ_2_SEQ_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Препроцессинг
    def prepare_dataset(batch):
        audio = batch["audio"]
        # Аугментация: обрезка до MAX_AUDIO_LEN
        if len(audio["array"]) > MAX_AUDIO_LEN * SAMPLE_RATE:
            audio["array"] = audio["array"][:MAX_AUDIO_LEN * SAMPLE_RATE]

        batch["input_features"] = processor.feature_extractor(
            audio["array"], sampling_rate=audio["sampling_rate"]
        ).input_features[0]

        batch["labels"] = processor.tokenizer(batch["text"]).input_ids
        return batch

    print(f"\n🔄 Препроцессинг данных...")
    train_set = train_set.map(prepare_dataset, remove_columns=train_set.column_names)
    test_set = test_set.map(prepare_dataset, remove_columns=test_set.column_names)

    # Метрика WER
    wer_metric = evaluate.load("wer", cache_dir=str(CACHE_DIR))

    def compute_metrics(pred):
        pred_ids = pred.predictions
        label_ids = pred.label_ids
        label_ids[label_ids == -100] = processor.tokenizer.pad_token_id

        pred_str = processor.batch_decode(pred_ids, skip_special_tokens=True)
        label_str = processor.batch_decode(label_ids, skip_special_tokens=True)

        wer = wer_metric.compute(predictions=pred_str, references=label_str)
        return {"wer": wer}

    # Аргументы обучения
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = Seq2SeqTrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=TRAIN_BATCH_SIZE,
        per_device_eval_batch_size=EVAL_BATCH_SIZE,
        gradient_accumulation_steps=GRADIENT_ACCUMULATION,
        learning_rate=LEARNING_RATE,
        warmup_steps=WARMUP_STEPS,
        max_steps=MAX_STEPS,
        gradient_checkpointing=True,
        fp16=False,  # CPU-safe
        evaluation_strategy="steps",
        eval_steps=50,
        save_steps=100,
        logging_steps=10,
        predict_with_generate=True,
        generation_max_length=225,
        report_to=["tensorboard"] if device == "cuda" else None,
        load_best_model_at_end=True,
        metric_for_best_model="wer",
        greater_is_better=False,
        push_to_hub=False,
        dataloader_num_workers=0 if device == "cpu" else 2,
    )

    trainer = Seq2SeqTrainer(
        args=training_args,
        model=model,
        train_dataset=train_set,
        eval_dataset=test_set,
        tokenizer=processor.feature_extractor,
        compute_metrics=compute_metrics,
    )

    print(f"\n{'='*60}")
    print(f"🚀 Запуск обучения (LoRA whisper-tiny, грузинский)")
    print(f"   Эпохи: ~{MAX_STEPS * TRAIN_BATCH_SIZE * GRADIENT_ACCUMULATION // len(train_set)}")
    print(f"   Шаги:  {MAX_STEPS}")
    print(f"   LoRA:  r={LORA_R}, alpha={LORA_ALPHA}")
    print(f"{'='*60}\n")

    trainer.train()

    # Сохраняем
    model.save_pretrained(str(output_dir / "final"))
    processor.save_pretrained(str(output_dir / "final"))

    print(f"\n✅ Модель сохранена: {output_dir}/final")
    print(f"   Размер: {sum(f.stat().st_size for f in (output_dir / 'final').rglob('*') if f.is_file()) / 1e6:.1f} MB")
    return True


def infer():
    """Тест обученной модели на одном аудио."""
    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    from peft import PeftModel
    import soundfile as sf
    import librosa

    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, help="Путь к аудиофайлу")
    parser.add_argument("--model-path", default=str(OUTPUT_DIR / "final"),
                        help="Путь к fine-tuned модели")
    args, _ = parser.parse_known_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"❌ Файл не найден: {audio_path}")
        return

    model_path = Path(args.model_path)
    if not (model_path / "adapter_config.json").exists():
        print(f"❌ Модель не найдена. Сначала: python whisper_finetune_ka.py --train")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"🔄 Загрузка fine-tuned модели...")
    processor = WhisperProcessor.from_pretrained(str(model_path))
    base_model = WhisperForConditionalGeneration.from_pretrained(
        BASE_MODEL, cache_dir=str(CACHE_DIR)
    )
    model = PeftModel.from_pretrained(base_model, str(model_path))
    model = model.merge_and_unload()  # сливаем LoRA веса
    model.to(device)
    model.eval()

    print(f"🔄 Загрузка аудио...")
    audio, sr = librosa.load(str(audio_path), sr=SAMPLE_RATE, mono=True)

    print(f"🧠 Распознавание...")
    input_features = processor.feature_extractor(
        audio, sampling_rate=SAMPLE_RATE, return_tensors="pt"
    ).input_features.to(device)

    with torch.no_grad():
        predicted_ids = model.generate(input_features)

    transcription = processor.batch_decode(
        predicted_ids, skip_special_tokens=True
    )[0]

    print(f"\n📝 Результат:\n  {transcription}")
    return transcription


def interactive_test():
    """Тест микрофона с fine-tuned моделью."""
    try:
        import sounddevice as sd
    except ImportError:
        print("❌ Нужен sounddevice: pip install sounddevice")
        return

    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    from peft import PeftModel

    model_path = OUTPUT_DIR / "final"
    if not (model_path / "adapter_config.json").exists():
        print(f"❌ Модель не найдена: {model_path}")
        print(f"   Сначала: python whisper_finetune_ka.py --train")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"🔄 Загрузка fine-tuned модели...")
    processor = WhisperProcessor.from_pretrained(str(model_path))
    base_model = WhisperForConditionalGeneration.from_pretrained(
        BASE_MODEL, cache_dir=str(CACHE_DIR)
    )
    model = PeftModel.from_pretrained(base_model, str(model_path))
    model = model.merge_and_unload()
    model.to(device)
    model.eval()

    print(f"🎤 Запись 5 секунд... говорите!")
    audio = sd.rec(int(5 * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    audio = audio.flatten()

    print(f"🧠 Распознавание...")
    input_features = processor.feature_extractor(
        audio, sampling_rate=SAMPLE_RATE, return_tensors="pt"
    ).input_features.to(device)

    with torch.no_grad():
        predicted_ids = model.generate(input_features)

    transcription = processor.batch_decode(
        predicted_ids, skip_special_tokens=True
    )[0]

    print(f"\n📝 Распознано:\n  {transcription}")


def main():
    global BASE_MODEL

    parser = argparse.ArgumentParser(description="Fine-Tune Whisper для грузинского языка")
    parser.add_argument("--prepare", action="store_true", help="Подготовить датасет из data/audio_ka/")
    parser.add_argument("--train", action="store_true", help="Запустить обучение")
    parser.add_argument("--infer", action="store_true", help="Тест обученной модели")
    parser.add_argument("--audio", help="Аудиофайл для теста (с --infer)")
    parser.add_argument("--interactive", action="store_true", help="Тест с микрофона")
    parser.add_argument("--model", default=BASE_MODEL,
                        help=f"Базовая модель (умолч. {BASE_MODEL})")

    args, _ = parser.parse_known_args()
    if args.model:
        BASE_MODEL = args.model

    if args.prepare:
        prepare_dataset()
    elif args.train:
        train()
    elif args.infer:
        if args.audio:
            infer()
        else:
            print("❌ Укажи --audio \"file.wav\"")
    elif args.interactive:
        interactive_test()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
