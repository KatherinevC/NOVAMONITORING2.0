"""
rutas/graficas.py
-----------------
Los endpoints JSON que alimentan las gráficas del dashboard (static/js/graficas.js).
Todos exigen sesión y permiso de ver el módulo MONITOREO (tabla permisos_rol), y solo LEEN datos.

    GET /api/graficas/catalogo                    áreas -> máquinas -> sensores (para los selectores)
    GET /api/graficas/sensor/<id>?minutos=15      serie de un sensor, umbrales y estadísticas
    GET /api/graficas/maquina/<id>?minutos=15     series de todos los sensores de una máquina
    GET /api/graficas/resumen                     estado actual de los sensores y alertas por área
"""
from flask import jsonify, request

from conexion import ERRORES_CONEXION, app, db
from model import monitoreo
from seguridad import api_requerida

MENSAJE_SIN_BD = ('Error en la conexión con el servidor de base de datos. '
                  'Verifica que MySQL (XAMPP) esté encendido y vuelve a intentarlo.')


def _minutos():
    """Lee ?minutos= y solo acepta las ventanas permitidas (5, 15 o 60); si no, usa 15."""
    minutos = request.args.get('minutos', default=15, type=int)
    return minutos if minutos in monitoreo.VENTANAS_MINUTOS else 15


def _responder(consulta, *args):
    """Ejecuta una consulta de model/monitoreo.py y la convierte en respuesta JSON.
    Si no hay conexión con la base de datos responde 503; si el dato no existe, 404."""
    try:
        datos = consulta(*args)
    except ERRORES_CONEXION:
        db.session.rollback()
        return jsonify(error=MENSAJE_SIN_BD), 503
    if datos is None:
        return jsonify(error='No existe'), 404
    return jsonify(datos)


@app.route('/api/graficas/catalogo')
@api_requerida('MONITOREO')
def api_graficas_catalogo():
    return _responder(monitoreo.catalogo_graficas)


@app.route('/api/graficas/sensor/<int:id_sensor>')
@api_requerida('MONITOREO')
def api_graficas_sensor(id_sensor):
    return _responder(monitoreo.serie_sensor, id_sensor, _minutos())


@app.route('/api/graficas/maquina/<int:id_maquina>')
@api_requerida('MONITOREO')
def api_graficas_maquina(id_maquina):
    return _responder(monitoreo.series_maquina, id_maquina, _minutos())


@app.route('/api/graficas/resumen')
@api_requerida('MONITOREO')
def api_graficas_resumen():
    return _responder(monitoreo.resumen_graficas)
