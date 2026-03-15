from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import os

def create_beautiful_icon():
    """Создает красивую иконку с эффектами"""
    
    # Размер иконки
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 1. Фоновый круг с градиентом
    for i in range(size):
        alpha = int(100 * (1 - i/size))  # Прозрачность уменьшается к центру
        color = (74, 144, 226, alpha)  # Синий с прозрачностью
        draw.ellipse([i/2, i/2, size-i/2, size-i/2], fill=color, outline=None)
    
    # 2. Основной круг
    draw.ellipse([20, 20, size-20, size-20], fill=None, outline=(74, 144, 226), width=4)
    
    # 3. Маленькие кружки (агенты) вокруг
    agents = 6
    for i in range(agents):
        angle = (360 / agents) * i
        import math
        x = size/2 + 70 * math.cos(math.radians(angle))
        y = size/2 + 70 * math.sin(math.radians(angle))
        
        # Цвета для разных агентов
        colors = [
            (255, 215, 0),   # Золотой
            (50, 205, 50),    # Лаймовый
            (255, 99, 71),    # Томатный
            (135, 206, 235),  # Небесно-голубой
            (255, 182, 193),  # Розовый
            (221, 160, 221)   # Сливовый
        ]
        
        # Рисуем круг с тенью
        for offset in range(3, 0, -1):
            draw.ellipse(
                [x-15-offset, y-15-offset, x+15+offset, y+15+offset], 
                fill=(0, 0, 0, 20), 
                outline=None
            )
        
        draw.ellipse([x-15, y-15, x+15, y+15], fill=colors[i], outline=(255,255,255), width=2)
    
    # 4. Центральная буква AI с эффектом
    try:
        # Пробуем загрузить красивый шрифт
        font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 100)
    except:
        # Если нет - используем дефолтный
        font = ImageFont.load_default()
    
    # Тень для текста
    draw.text((size/2-45+3, size/2-30+3), "AI", fill=(0,0,0,100), font=font, anchor="mm")
    # Основной текст
    draw.text((size/2-45, size/2-30), "AI", fill=(255,255,255), font=font, anchor="mm")
    
    # 5. Блики
    for i in range(3):
        x = 40 + i*80
        y = 40
        draw.ellipse([x, y, x+30, y+30], fill=(255,255,255,30), outline=None)
    
    # 6. Обводка
    draw.ellipse([5, 5, size-5, size-5], outline=(255,255,255,100), width=2)
    
    # Применяем размытие для мягкости
    img = img.filter(ImageFilter.GaussianBlur(radius=1))
    
    # Сохраняем
    icon_path = os.path.expanduser("~/AIM/ai_icon.png")
    img.save(icon_path, "PNG", quality=95)
    print(f"✅ Красивая иконка создана: {icon_path}")
    
    # Создаем также маленькую версию для меню
    small = img.resize((64, 64), Image.Resampling.LANCZOS)
    small.save(os.path.expanduser("~/AIM/ai_icon_small.png"), "PNG", quality=95)

def create_animated_icon():
    """Создает анимированную версию иконки (опционально)"""
    try:
        frames = []
        for i in range(0, 360, 30):
            size = 256
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Вращающийся круг
            import math
            x = size/2 + 40 * math.cos(math.radians(i))
            y = size/2 + 40 * math.sin(math.radians(i))
            
            draw.ellipse([x-20, y-20, x+20, y+20], fill=(74, 144, 226, 200))
            draw.ellipse([20, 20, size-20, size-20], outline=(74, 144, 226), width=3)
            draw.text((size/2-45, size/2-30), "AI", fill=(255,255,255), anchor="mm")
            
            frames.append(img)
        
        # Сохраняем как GIF
        if frames:
            gif_path = os.path.expanduser("~/AIM/ai_icon_animated.gif")
            frames[0].save(
                gif_path,
                save_all=True,
                append_images=frames[1:],
                duration=100,
                loop=0,
                optimize=True
            )
            print(f"✅ Анимированная иконка создана: {gif_path}")
    except:
        pass

if __name__ == "__main__":
    create_beautiful_icon()
    create_animated_icon()
