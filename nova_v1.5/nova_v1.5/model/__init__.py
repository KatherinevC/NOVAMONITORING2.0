"""
Paquete model: una clase Python por cada tabla de novadb que usa la aplicación.
Importarlas aquí hace que SQLAlchemy las conozca todas al arrancar.
"""
from model.usuario import TipoUsuario, Usuario
from model.permiso import ModuloSistema, PermisoRol, permisos_del_rol
# Consultas y operaciones (monitoreo.py, operaciones.py, cuentas.py) se importan directamente
# desde las rutas: from model.cuentas import ..., así cada archivo queda con su responsabilidad.
