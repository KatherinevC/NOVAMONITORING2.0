"""
crear_usuarios.py — crea los 3 usuarios de prueba de NOVA (uno por rol).

Ejecutar UNA vez, después de importar los scripts SQL 01 a 06:
    python crear_usuarios.py                      (contraseña de prueba: nova123)
    python crear_usuarios.py --password OtraClave

Si el usuario ya existe, solo le cambia la contraseña. Las contraseñas se guardan
con hash; nunca en texto plano. Cámbialas antes de usar NOVA con datos reales.
"""
import argparse

from conexion import app, db
from model import TipoUsuario, Usuario

# (rol de la tabla tipos_usuario, nombre a mostrar, correo para iniciar sesión)
USUARIOS_PRUEBA = [
    ('administrador', 'Administrador NOVA', 'admin@nova.local'),
    ('operativo',     'Operador NOVA',      'operativo@nova.local'),
    ('gerencial',     'Gerente NOVA',       'gerencial@nova.local'),
]


def main():
    parser = argparse.ArgumentParser(description='Crea los usuarios de prueba de NOVA')
    parser.add_argument('--password', default='nova123', help='contraseña para los 3 usuarios')
    args = parser.parse_args()

    with app.app_context():
        for rol, nombre, email in USUARIOS_PRUEBA:
            tipo = TipoUsuario.query.filter_by(nombre_tipo_user=rol).first()
            if tipo is None:
                print(f"No existe el rol '{rol}'. Importa primero 01_hoja2_roles_permisos.sql")
                return

            usuario = Usuario.query.filter_by(email=email).first()
            if usuario is None:
                usuario = Usuario(id_tipo_user=tipo.id_tipo_user, nombre_user=nombre, email=email, activo=True)
                db.session.add(usuario)
                accion = 'creado'
            else:
                accion = 'actualizado'
            usuario.establecer_password(args.password)   # guarda el HASH, no la contraseña
            print(f'{accion}: {email}  (rol {rol})')

        db.session.commit()
        print('Listo. Inicia sesión con cualquiera de esos correos y la contraseña indicada.')


if __name__ == '__main__':
    main()
