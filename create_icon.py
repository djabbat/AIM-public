from PIL import Image, ImageDraw
import os

img = Image.new('RGBA', (128, 128), color=(255,255,255,0))
draw = ImageDraw.Draw(img)
draw.ellipse([10,10,118,118], fill=(74,144,226,50), outline=(74,144,226), width=3)
draw.text((45,50), "AI", fill=(74,144,226))
img.save('/home/oem/AIM/icon.png')
