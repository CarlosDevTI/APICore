#? Usar Python 3.11 slim para reducir tamaño
FROM python:3.11-slim

#? Variables de entorno para Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

#? Instalar dependencias del sistema para Oracle
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

#? Crear directorio de trabajo
WORKDIR /app

#? Copiar requirements y instalar dependencias Python
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

#? Copiar el proyecto
COPY . .

#? Crear directorio para archivos estáticos
RUN mkdir -p /app/staticfiles

#? Colectar archivos estáticos
RUN python manage.py collectstatic --noinput

#? Exponer puerto
EXPOSE 8010

#? Comando para ejecutar con gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8010", "--workers", "3", "--timeout", "120", "APICore.wsgi:application"]