"""
conexion.py
-----------
Aquí vive SOLO la configuración base de NOVA:
  1) la aplicación Flask (app)
  2) la conexión a la base de datos novadb (db)

No se escriben rutas ni consultas en este archivo. Así los demás módulos
(modelos, rutas, seguridad) pueden importarlo sin crear importaciones circulares.
"""
import os
from datetime import timedelta

from flask import Flask
from flask_sqlalchemy import SQLAlchemy  # puente entre Flask y MySQL/MariaDB
from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError

app = Flask(__name__)

# --- Conexión a la base de datos (XAMPP) ------------------------------------
# Formato: mysql+pymysql://usuario:clave@servidor/base_de_datos
# Requiere:  pip install flask-sqlalchemy pymysql
# Si tu usuario root de XAMPP tiene contraseña, define la variable de entorno
# NOVA_DB_URI en vez de editar este archivo, por ejemplo:
#   mysql+pymysql://root:miclave@localhost/novadb?charset=utf8mb4
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'NOVA_DB_URI', 'mysql+pymysql://root@localhost/novadb?charset=utf8mb4')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # ahorra memoria, no se usa

# --- Sesión de usuario --------------------------------------------------------
# Flask firma la cookie de sesión con esta clave. Si alguien la conoce puede
# falsificar sesiones, así que en producción debe venir de una variable de
# entorno (NOVA_SECRET_KEY) y nunca subirse al repositorio.
app.config['SECRET_KEY'] = os.environ.get(
    'NOVA_SECRET_KEY', 'clave-solo-para-desarrollo-cambiala')
app.config['SESSION_COOKIE_HTTPONLY'] = True    # el JavaScript del navegador no puede leer la cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # la cookie no viaja en peticiones desde otros sitios
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)  # duración de un turno

db = SQLAlchemy(app)

# --- ¿Hay conexión con el servidor de base de datos? ------------------------------
# Cuando MySQL está apagado (por ejemplo XAMPP detenido), la contraseña de la base es
# incorrecta o la base no existe, SQLAlchemy lanza uno de estos dos errores. Las rutas los
# atrapan para mostrar un mensaje claro en vez de una pantalla de error técnica.
ERRORES_CONEXION = (OperationalError, InterfaceError)


def base_de_datos_disponible():
    """True si novadb responde; False si no hay conexión con el servidor de base de datos.

    Se usa en el login y en el registro para avisar ANTES de que el usuario escriba sus datos.
    """
    try:
        db.session.execute(text('SELECT 1'))
        return True
    except ERRORES_CONEXION:
        try:
            db.session.rollback()   # deja la sesión limpia para el siguiente intento
        except Exception:
            pass
        return False
