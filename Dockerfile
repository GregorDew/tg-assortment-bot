# Базовий образ Python 3.12 slim
FROM python:3.12-slim

# Встановлюємо робочу директорію в контейнері
WORKDIR /app

# Забороняємо створення .pyc файлів та вмикаємо буферизацію виводу
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Встановлюємо залежності системи (якщо знадобляться для компіляції)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей та встановлюємо їх
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копіюємо вихідний код
COPY . .

# Команда запуску бота
CMD ["python", "main.py"]
