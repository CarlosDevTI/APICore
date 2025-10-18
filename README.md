# Proyecto APICore

Este es un proyecto de API desarrollado con Django y Django REST Framework.

## Descripción

APICore proporciona una serie de endpoints para [**<-- AÑADE AQUÍ UNA BREVE DESCRIPCIÓN DE LO QUE HACE TU API**]. 
El proyecto está configurado para ser desplegado utilizando Docker y se integra con diversas fuentes de datos y servicios de IA.

## Características

*   API RESTful construida con Django REST Framework.
*   Soporte para bases de datos MySQL y Oracle.
*   Integración con servicios de IA (Google Generative AI, OpenAI).
*   Capacidad para procesamiento de datos y generación de reportes.
*   Configuración lista para Docker.

## Requisitos

*   Python 3.x
*   Docker y Docker Compose (Recomendado)
*   Dependencias listadas en `requirements.txt`

## Instalación y Ejecución

### Con Docker (Recomendado)

1.  Clona este repositorio.
2.  Asegúrate de tener un archivo `.env` con las variables de entorno necesarias (puedes usar `APICore/settings.py` como referencia).
3.  Construye y levanta los contenedores:
    ```bash
    docker-compose up --build
    ```
4.  La API estará disponible en `http://localhost:8000` (o el puerto que hayas configurado).

### De forma local

1.  Clona este repositorio.
2.  Crea y activa un entorno virtual:
    ```bash
    python -m venv venv
    source venv/Scripts/activate  # En Windows
    # . venv/bin/activate  # En macOS/Linux
    ```
3.  Instala las dependencias:
    ```bash
    pip install -r requirements.txt
    ```
4.  Realiza las migraciones de la base de datos:
    ```bash
    python manage.py migrate
    ```
5.  Inicia el servidor de desarrollo:
    ```bash
    python manage.py runserver
    ```

## Endpoints de la API

*   `/api/...` - [**<-- DESCRIBE TUS ENDPOINTS AQUÍ**]
*   `/admin/` - Interfaz de administración de Django.

