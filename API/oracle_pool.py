# oracle_pool.py
import oracledb
from django.conf import settings

_pool = None  #? Singleton de pool

def get_pool():
    """Crea el pool si no existe y lo devuelve."""
    global _pool
    if _pool is None:
        db = settings.DATABASES['oracle']
        dsn = f"{db['HOST']}:{db['PORT']}/{db['NAME']}"
        _pool = oracledb.create_pool(
            user=db['USER'],
            password=db['PASSWORD'],
            dsn=dsn,
            min=1,            #? mínimo de conexiones
            max=5,            #? máximo de conexiones activas
            increment=1,      #? crecimiento del pool
            timeout=300,      #? segundos para reciclar conexiones inactivas
            homogeneous=True  #? mismo usuario/credenciales
        )
    return _pool

def acquire_connection():
    """Obtiene una conexión del pool lista para usarse."""
    pool = get_pool()
    conn = pool.acquire()
    return conn
