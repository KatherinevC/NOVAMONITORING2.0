"""
seguridad.py
------------
Todo lo que decide "quién puede entrar y qué puede ver":
  - funciones que consultan los permisos guardados en la sesión
  - decoradores para proteger rutas (login_requerido, modulo_requerido)
  - un decorador para los endpoints que responden JSON (api_requerida)
  - la protección CSRF de TODOS los formularios (ver proteger_formularios)
  - funciones disponibles dentro de las plantillas HTML

Los permisos se leen de la base de datos UNA vez, al iniciar sesión
(ver rutas/rutas.py) y se guardan en la sesión. Si cambias la tabla
permisos_rol, el usuario debe cerrar sesión y volver a entrar.
"""
import hmac
import secrets
from functools import wraps

from flask import abort, jsonify, redirect, request, session, url_for

from conexion import app


def puede_ver(modulo):
    """True si el rol del usuario actual puede VER ese módulo (ej. 'ALERTAS')."""
    return bool(session.get('permisos', {}).get(modulo, {}).get('ver'))


def puede_ejecutar(modulo):
    """True si el rol puede ACTUAR en ese módulo (crear, editar, atender, generar)."""
    return bool(session.get('permisos', {}).get(modulo, {}).get('ejecutar'))


def login_requerido(vista):
    """Decorador: si no hay sesión iniciada, manda al usuario al login."""
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if 'id_user' not in session:
            return redirect(url_for('login'))
        return vista(*args, **kwargs)
    return envoltura


def modulo_requerido(modulo):
    """Decorador: exige sesión iniciada Y permiso de ver el módulo indicado.

    Esto protege la ruta en el servidor. Ocultar el enlace en el menú no basta:
    alguien podría escribir la dirección a mano.
    """
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if 'id_user' not in session:
                return redirect(url_for('login'))
            if not puede_ver(modulo):
                abort(403)  # Prohibido: lo atiende el manejador de rutas/rutas.py
            return vista(*args, **kwargs)
        return envoltura
    return decorador


# ============================================================================
# Protección CSRF (formularios)
# ============================================================================
# CSRF = que otra página web engañe a tu navegador para enviar un formulario a NOVA "en tu
# nombre" (por ejemplo, aprobar una cuenta de administrador). Para evitarlo cada formulario
# POST lleva un campo oculto con un token secreto que solo conoce esta sesión.
def token_csrf():
    """Devuelve el token anti-CSRF de esta sesión (lo crea la primera vez que se pide)."""
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(16)
    return session['csrf']


@app.before_request
def proteger_formularios():
    """Se ejecuta antes de CADA petición: si es un POST, el token debe coincidir.

    El token llega en el campo oculto csrf_token del formulario (o en la cabecera
    X-CSRF-Token si lo envía JavaScript). Si no coincide, se responde 400.
    """
    if request.method != 'POST':
        return None
    enviado = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
    esperado = session.get('csrf', '')
    # Un token vacío nunca vale; la comparación se hace en tiempo constante (más segura)
    if not esperado or not hmac.compare_digest(enviado.encode(), esperado.encode()):
        abort(400)
    return None


def api_requerida(modulo=None, ejecutar=False):
    """Como modulo_requerido, pero para endpoints que responden JSON.

    En vez de redirigir a una página, responde con un código de error y un mensaje:
      401 = no hay sesión, 403 = el rol no tiene permiso.
        modulo   : clave del módulo cuyo permiso se exige (None = basta con tener sesión)
        ejecutar : True exige poder ACTUAR en el módulo, no solo verlo
    """
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if 'id_user' not in session:
                return jsonify(error='Sesión no iniciada'), 401
            if modulo is not None:
                permitido = puede_ejecutar(modulo) if ejecutar else puede_ver(modulo)
                if not permitido:
                    return jsonify(error='Tu perfil no tiene permiso para esto'), 403
            return vista(*args, **kwargs)
        return envoltura
    return decorador


@app.context_processor
def funciones_para_plantillas():
    """Deja puede_ver() y puede_ejecutar() usables en cualquier HTML:
        {% if puede_ver('CRUD') %} ... {% endif %}
    Además csrf_token() entrega el token que debe ir en cada formulario POST:
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    """
    return {'puede_ver': puede_ver, 'puede_ejecutar': puede_ejecutar, 'csrf_token': token_csrf}
