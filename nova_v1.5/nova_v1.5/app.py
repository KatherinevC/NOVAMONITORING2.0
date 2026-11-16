"""
app.py — punto de entrada de NOVA.

como se ejecuta (desde la carpeta nova/):
    python app.py        ->  http://localhost:4500 "evitar errores con otros servicios en ese puerto"

orden de importación (importa):
    conexion  -> crea app y db
    model     -> registra las tablas
    rutas     -> registra las direcciones (importarlo ya las activa)
    graficas  -> los endpoints JSON que alimentan las gráficas
    seguridad -> la protección CSRF y las funciones de permisos (rutas.py ya lo importa)

Requisitos previos (una sola vez): importar novadb.sql y los scripts SQL 01 a 08.
"""
from sqlalchemy import text

from conexion import app, db
import model            # noqa: F401  (solo para que SQLAlchemy conozca los modelos)
from rutas import rutas  # noqa: F401  (solo para registrar las rutas)
from rutas import graficas  # noqa: F401  (endpoints JSON de las gráficas del dashboard)

# Prueba rápida de conexión al arrancar: imprime en consola si novadb responde.
# Si MySQL está apagado, NOVA igual arranca; el login mostrará "error de conexión con el servidor".
with app.app_context():
    try:
        resultado = db.session.execute(text('SELECT 1'))
        print('CONEXION OK;', resultado.scalar())
    except Exception as e:
        print('error de conexion', e)

if __name__ == '__main__':
    # debug=True recarga el servidor al guardar cambios. Quítalo en producción.
    app.run(debug=True, port=4500)
