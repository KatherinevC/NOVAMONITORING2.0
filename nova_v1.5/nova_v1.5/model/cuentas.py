"""
model/cuentas.py
----------------
Todo lo relacionado con las CUENTAS de usuario: buscarlas para el login, registrarlas y
aprobar las solicitudes de administrador.

Flujo de registro:
  - Rol operativo o gerencial -> la cuenta queda ACTIVA al instante.
  - Rol administrador         -> la cuenta queda INACTIVA y se crea una solicitud
                                 (tabla solicitudes_registro). Un administrador que ya
                                 exista debe aprobarla desde la pantalla "Administrar".
                                 Mientras tanto la persona no puede iniciar sesión.

Las consultas usan parámetros (:nombre) y nunca pegan texto del usuario dentro del SQL.
"""
import re

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from conexion import db
from model.usuario import crear_hash

# --- Reglas del registro (cámbialas aquí y se aplican en todo el sistema) --------------
# Roles que NECESITAN la aprobación de un administrador. Si quieres que operativo o gerencial
# también esperen aprobación, agrégalos: {'administrador', 'operativo', 'gerencial'}
ROLES_CON_APROBACION = {'administrador'}

# Mientras espera aprobación, la cuenta se guarda con este rol (el de menos privilegios) y
# desactivada. El rol pedido solo se aplica cuando un administrador aprueba.
ROL_MIENTRAS_ESPERA = 'operativo'

EMAIL_VALIDO = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


# ============================================================================
# Validación (no toca la base de datos)
# ============================================================================
def validar_registro(nombre, email, password, confirmar, rol, roles_validos):
    """Revisa los datos del formulario. Devuelve un diccionario {campo: mensaje} con los
    errores; si está vacío, todo está bien."""
    errores = {}
    if not 2 <= len(nombre) <= 50:
        errores['nombre'] = 'El nombre debe tener entre 2 y 50 caracteres.'
    if len(email) > 100 or not EMAIL_VALIDO.match(email):
        errores['email'] = 'Escribe un correo válido (máximo 100 caracteres).'
    if len(password) < 8 or len(password) > 128:
        errores['password'] = 'La contraseña debe tener entre 8 y 128 caracteres.'
    elif not (re.search(r'[A-Za-z]', password) and re.search(r'\d', password)):
        errores['password'] = 'La contraseña debe incluir al menos una letra y un número.'
    if password != confirmar:
        errores['confirmar'] = 'Las contraseñas no coinciden.'
    if rol not in roles_validos:
        errores['rol'] = 'Selecciona un rol válido.'
    return errores


# ============================================================================
# Consultas
# ============================================================================
def roles_disponibles():
    """Los roles de la tabla tipos_usuario, marcando cuáles requieren aprobación."""
    filas = db.session.execute(text("""
        SELECT id_tipo_user, nombre_tipo_user, descripcion_tuser
        FROM tipos_usuario ORDER BY id_tipo_user
    """)).mappings().all()
    return [{'id': f['id_tipo_user'], 'nombre': f['nombre_tipo_user'],
             'descripcion': f['descripcion_tuser'] or '',
             'requiere_aprobacion': f['nombre_tipo_user'] in ROLES_CON_APROBACION}
            for f in filas]


def buscar_usuario(email):
    """Busca una cuenta por correo, ACTIVA O NO. Devuelve un diccionario o None.

    El login necesita ver también las cuentas inactivas para poder decirle a quien ya
    escribió su contraseña correcta que su solicitud sigue pendiente.
    """
    fila = db.session.execute(text("""
        SELECT u.id_user, u.id_tipo_user, u.nombre_user, u.email, u.password_hash, u.activo,
               t.nombre_tipo_user AS rol
        FROM usuarios u
        JOIN tipos_usuario t ON t.id_tipo_user = u.id_tipo_user
        WHERE u.email = :email
    """), {'email': email}).mappings().first()
    return dict(fila) if fila else None


def estado_solicitud(id_user):
    """'pendiente', 'aprobada', 'rechazada' o None si no hay solicitud.

    Si todavía no se ejecutó 08_solicitudes_registro.sql la tabla no existe: en ese caso
    se devuelve None en vez de romper el login.
    """
    try:
        fila = db.session.execute(text(
            "SELECT estado FROM solicitudes_registro WHERE id_user = :u"), {'u': id_user}).first()
        return fila[0] if fila else None
    except ProgrammingError:
        db.session.rollback()
        current_app.logger.warning('Falta la tabla solicitudes_registro (ejecuta 08_solicitudes_registro.sql)')
        return None


def marcar_acceso(id_user):
    """Anota la fecha y hora del último ingreso (columna ultimo_acceso)."""
    db.session.execute(text("UPDATE usuarios SET ultimo_acceso = CURRENT_TIMESTAMP WHERE id_user = :u"),
                       {'u': id_user})
    db.session.commit()


def listar_usuarios(limite=200):
    """Usuarios registrados, para la pantalla de administración."""
    return db.session.execute(text("""
        SELECT u.id_user, u.nombre_user, u.email, u.activo, u.creado_en, u.ultimo_acceso,
               t.nombre_tipo_user AS rol
        FROM usuarios u JOIN tipos_usuario t ON t.id_tipo_user = u.id_tipo_user
        ORDER BY u.id_user LIMIT :limite
    """), {'limite': limite}).mappings().all()


def listar_solicitudes(pendientes=True, limite=50):
    """Solicitudes de cuenta con rol privilegiado: las pendientes o las ya resueltas."""
    comparacion = "s.estado = 'pendiente'" if pendientes else "s.estado <> 'pendiente'"
    orden = 's.creada_en DESC' if pendientes else 's.resuelta_en DESC'
    return db.session.execute(text(f"""
        SELECT s.id_solicitud, s.estado, s.creada_en, s.resuelta_en,
               u.id_user, u.nombre_user, u.email,
               t.nombre_tipo_user AS rol_solicitado,
               r.nombre_user AS resuelta_por
        FROM solicitudes_registro s
        JOIN usuarios u       ON u.id_user = s.id_user
        JOIN tipos_usuario t  ON t.id_tipo_user = s.id_tipo_user
        LEFT JOIN usuarios r  ON r.id_user = s.resuelta_por
        WHERE {comparacion}
        ORDER BY {orden}
        LIMIT :limite
    """), {'limite': limite}).mappings().all()   # la comparación y el orden son fijos, no vienen del usuario


# ============================================================================
# Escrituras
# ============================================================================
def registrar_usuario(nombre, email, password, rol):
    """Crea la cuenta. Devuelve (ok, mensaje, queda_pendiente).

    Los errores de conexión con la base de datos NO se atrapan aquí: suben hasta la ruta,
    que muestra "error de conexión con el servidor de base de datos".
    """
    roles = {r['nombre']: r['id'] for r in roles_disponibles()}
    if rol not in roles or ROL_MIENTRAS_ESPERA not in roles:
        return False, 'El rol seleccionado no es válido.', False

    if db.session.execute(text("SELECT 1 FROM usuarios WHERE email = :e"), {'e': email}).first():
        return False, 'Ya existe una cuenta con ese correo.', False

    pendiente = rol in ROLES_CON_APROBACION
    # Mínimo privilegio: si debe esperar, se guarda como 'operativo' e inactiva.
    id_rol_guardado = roles[ROL_MIENTRAS_ESPERA] if pendiente else roles[rol]
    try:
        resultado = db.session.execute(text("""
            INSERT INTO usuarios (id_tipo_user, nombre_user, email, password_hash, activo)
            VALUES (:rol, :nombre, :email, :hash, :activo)
        """), {'rol': id_rol_guardado, 'nombre': nombre, 'email': email,
               'hash': crear_hash(password), 'activo': 0 if pendiente else 1})
        id_user = resultado.lastrowid
        if pendiente:
            db.session.execute(text("""
                INSERT INTO solicitudes_registro (id_user, id_tipo_user) VALUES (:u, :rol)
            """), {'u': id_user, 'rol': roles[rol]})
        db.session.commit()
    except IntegrityError:            # dos personas registraron el mismo correo a la vez
        db.session.rollback()
        return False, 'Ya existe una cuenta con ese correo.', False
    except Exception:
        db.session.rollback()
        raise

    if pendiente:
        _anotar_historial(f'Solicitud de cuenta {rol}: {nombre} ({email}) espera aprobación', 'pendiente', id_user)
        return True, ('Solicitud enviada. Un administrador debe aprobarla antes de que puedas '
                      'iniciar sesión.'), True
    _anotar_historial(f'Cuenta {rol} creada: {nombre} ({email})', 'completado', id_user)
    return True, 'Cuenta creada. Ya puedes iniciar sesión.', False


def resolver_solicitud(id_solicitud, aprobar, id_admin):
    """Aprueba o rechaza una solicitud. Devuelve (ok, mensaje)."""
    sol = db.session.execute(text("""
        SELECT s.id_solicitud, s.id_user, s.id_tipo_user, s.estado,
               u.nombre_user, u.email, t.nombre_tipo_user AS rol
        FROM solicitudes_registro s
        JOIN usuarios u      ON u.id_user = s.id_user
        JOIN tipos_usuario t ON t.id_tipo_user = s.id_tipo_user
        WHERE s.id_solicitud = :id
    """), {'id': id_solicitud}).mappings().first()
    if not sol:
        return False, 'La solicitud no existe.'
    if sol['estado'] != 'pendiente':
        return False, 'Esa solicitud ya fue resuelta.'
    if sol['id_user'] == id_admin:
        return False, 'No puedes resolver tu propia solicitud.'

    try:
        # La condición "AND estado = 'pendiente'" evita que dos administradores la resuelvan a la vez
        actualizadas = db.session.execute(text("""
            UPDATE solicitudes_registro
            SET estado = :estado, resuelta_en = CURRENT_TIMESTAMP, resuelta_por = :admin
            WHERE id_solicitud = :id AND estado = 'pendiente'
        """), {'estado': 'aprobada' if aprobar else 'rechazada', 'admin': id_admin, 'id': id_solicitud}).rowcount
        if actualizadas == 0:
            db.session.rollback()
            return False, 'Esa solicitud ya fue resuelta.'
        if aprobar:   # solo ahora la cuenta se activa y recibe el rol que pidió
            db.session.execute(text("UPDATE usuarios SET activo = 1, id_tipo_user = :rol WHERE id_user = :u"),
                               {'rol': sol['id_tipo_user'], 'u': sol['id_user']})
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    accion = 'aprobada' if aprobar else 'rechazada'
    _anotar_historial(f"Solicitud de cuenta {sol['rol']} de {sol['nombre_user']} ({sol['email']}) {accion}",
                      'completado', id_admin)
    return True, f"Solicitud de {sol['nombre_user']} {accion}."


def _anotar_historial(descripcion, estado, id_user):
    """Deja constancia en la tabla historial (como hacen mantenimientos y alertas).

    Es "mejor esfuerzo": si falla, el registro de la cuenta NO se deshace.
    """
    try:
        db.session.execute(text("""
            INSERT INTO historial (tipo_evento, descripcion, fecha_hora, estado, id_user)
            VALUES ('sistema', :d, CURRENT_TIMESTAMP, :e, :u)
        """), {'d': descripcion, 'e': estado, 'u': id_user})
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.warning('No se pudo escribir en historial', exc_info=True)
