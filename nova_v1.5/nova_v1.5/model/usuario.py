"""
model/usuario.py
----------------
Tablas de novadb relacionadas con las personas que entran al sistema:
  - tipos_usuario : los roles (administrador, operativo, gerencial)
  - usuarios      : las cuentas (correo, hash de la contraseña, rol, estado)
"""
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from conexion import db


def crear_hash(password):
    """Convierte una contraseña en su hash seguro (lo único que se guarda en la base).

    Se usa pbkdf2:sha256 a propósito: su resultado mide ~100 caracteres y cabe en
    password_hash VARCHAR(150). El método por defecto de Werkzeug 3 (scrypt) genera ~160
    y no cabría. Esta función la usan crear_usuarios.py y el registro de usuarios.
    """
    return generate_password_hash(password, method='pbkdf2:sha256')


class TipoUsuario(db.Model):
    """Rol de un usuario. Tabla: tipos_usuario."""
    __tablename__ = 'tipos_usuario'

    id_tipo_user = db.Column(db.Integer, primary_key=True)
    nombre_tipo_user = db.Column(db.String(30), unique=True, nullable=False)
    descripcion_tuser = db.Column(db.String(150))


class Usuario(db.Model):
    """Cuenta de acceso a NOVA. Tabla: usuarios."""
    __tablename__ = 'usuarios'

    id_user = db.Column(db.Integer, primary_key=True)
    id_tipo_user = db.Column(db.Integer, db.ForeignKey('tipos_usuario.id_tipo_user'), nullable=False)
    nombre_user = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)  # NUNCA la contraseña en texto plano
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.now)
    ultimo_acceso = db.Column(db.DateTime)

    # Permite escribir usuario.tipo.nombre_tipo_user para obtener el rol
    tipo = db.relationship('TipoUsuario')

    # --- Contraseñas ---------------------------------------------------------
    def establecer_password(self, password):
        """Guarda el hash de la contraseña.

        Se usa pbkdf2:sha256 a propósito: su resultado mide ~100 caracteres y
        cabe en password_hash VARCHAR(150). El método por defecto de Werkzeug 3
        (scrypt) genera ~160 y no cabría.
        """
        self.password_hash = crear_hash(password)

    def verificar_password(self, password):
        """True si la contraseña escrita coincide con el hash guardado."""
        return check_password_hash(self.password_hash, password)

    # --- Consultas -------------------------------------------------------------
    @staticmethod
    def buscar_activo_por_email(email):
        """Devuelve el usuario ACTIVO con ese correo, o None.

        Un usuario desactivado (activo = 0) se trata igual que uno que no existe.
        """
        return Usuario.query.filter_by(email=email, activo=True).first()

    def registrar_acceso(self):
        """Anota la fecha y hora del último ingreso (columna ultimo_acceso)."""
        self.ultimo_acceso = datetime.now()
        db.session.commit()
