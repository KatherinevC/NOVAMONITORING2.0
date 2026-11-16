"""
model/permiso.py
----------------
Matriz de permisos por rol (la Hoja 2 del Excel convertida en tablas):
  - modulos_sistema : las partes del aplicativo (ALERTAS, CRUD, MONITOREO...)
  - permisos_rol    : qué puede hacer cada rol en cada módulo
"""
from conexion import db


class ModuloSistema(db.Model):
    """Un módulo del aplicativo. Tabla: modulos_sistema."""
    __tablename__ = 'modulos_sistema'

    id_modulo = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(30), unique=True, nullable=False)   # 'ALERTAS', 'CRUD'...
    requisitos_rf = db.Column(db.String(30), nullable=False)
    nombre_modulo = db.Column(db.String(100), nullable=False)


class PermisoRol(db.Model):
    """Permiso de un rol sobre un módulo. Tabla: permisos_rol (llave doble)."""
    __tablename__ = 'permisos_rol'

    id_tipo_user = db.Column(db.Integer, db.ForeignKey('tipos_usuario.id_tipo_user'), primary_key=True)
    id_modulo = db.Column(db.Integer, db.ForeignKey('modulos_sistema.id_modulo'), primary_key=True)
    permiso_original = db.Column(db.String(30), nullable=False)  # texto del Excel: 'Atiende / Gestiona'
    puede_ver = db.Column(db.Boolean, nullable=False)            # False = 'Sin acceso'
    puede_ejecutar = db.Column(db.Boolean, nullable=False)       # True = crea / edita / atiende / genera


def permisos_del_rol(id_tipo_user):
    """Devuelve los permisos de un rol como diccionario, listo para guardar en la sesión.

    Ejemplo del resultado:
        {'ALERTAS': {'ver': True, 'ejecutar': False, 'permiso': 'Solo Consulta'},
         'CRUD':    {'ver': False, 'ejecutar': False, 'permiso': 'Sin acceso'}, ...}
    """
    filas = (db.session.query(ModuloSistema.clave, PermisoRol.puede_ver,
                              PermisoRol.puede_ejecutar, PermisoRol.permiso_original)
             .join(PermisoRol, PermisoRol.id_modulo == ModuloSistema.id_modulo)
             .filter(PermisoRol.id_tipo_user == id_tipo_user)
             .all())
    return {clave: {'ver': bool(ver), 'ejecutar': bool(ejecutar), 'permiso': texto}
            for clave, ver, ejecutar, texto in filas}
