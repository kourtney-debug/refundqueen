from flask import Flask, render_template, request
import cv2
import numpy as np
from PIL import Image
import pytesseract
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import os

app = Flask(__name__)

def process_receipt(file_stream):
    # Read the uploaded file
    file_bytes = np.frombuffer(file_stream.read(), np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if img is None:
        return "Could not read image", []
    
    # Nuclear preprocessing
    img = cv2.resize(img, None, fx=1.5, fy=1.5)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    sharpened = cv2D(thresh, -1, kernel)
    pil_img = Image.fromarray(sharpened)
    
    # OCR
    text = pytesseract.image_to_string(pil_img)
    
    # Parse items
    items = []
    for line in text.split('\n'):
        line = line.strip()
        if not line: continue
        match = re.search(r'(.+?)\s+\$?([\d.,]+)$', line)
        if match:
            name = match.group(1).strip()
            try:
                price = float(match.group(2).replace(',', ''))
                items.append({"name": name, "paid": price})
            except:
                continue
    
    # Check Amazon prices
    refunds = []
    total = 0
    for item in items:
        try:
            url = f"https://www.amazon.com/s?k={quote(item['name'][:60
