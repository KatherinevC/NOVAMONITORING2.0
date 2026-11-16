"""
rutas/rutas.py
--------------
Las direcciones (URL) de NOVA y lo que hace cada una.
Aquí NO va la configuración (conexion.py), ni las consultas a tablas (model/),
ni las reglas de permisos (seguridad.py): solo se coordinan.

Mapa del archivo:
    1. Datos que reciben todas las plantillas (menú, alertas pendientes, error de conexión)
    2. Acceso al sistema: login, registro, logout, olvido de contraseña
    3. Dashboard, su API y el simulador de lecturas
    4. Módulos: máquinas, monitoreo, alertas, historial, mantenimiento, administrar
    5. Manejo de errores (400, 403 y "sin conexión con la base de datos")
"""
from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import ProgrammingError
from werkzeug.security import check_password_hash, generate_password_hash

from conexion import ERRORES_CONEXION, app, base_de_datos_disponible, db
from model import permisos_del_rol
from model.cuentas import (buscar_usuario, estado_solicitud, listar_solicitudes, listar_usuarios,
                           marcar_acceso, registrar_usuario, resolver_solicitud, roles_disponibles,
                           validar_registro)
from model.monitoreo import (contar_alertas_pendientes, obtener_areas, obtener_historial_lecturas,
                             obtener_sensores_monitoreo, registrar_lectura, resumen_planta,
                             ultimas_lecturas)
from model.operaciones import (listar_maquinas, listar_alertas, atender_alerta,
                               listar_mantenimiento_catalogos, registrar_mantenimiento,
                               listar_historial)
from seguridad import api_requerida, login_requerido, modulo_requerido, puede_ejecutar, puede_ver
from simulador import servicio as simulador

# Hash "de relleno". Si el correo no existe igual calculamos un hash, para que
# la respuesta tarde lo mismo y nadie pueda descubrir qué correos están registrados.
_HASH_FALSO = generate_password_hash('relleno', method='pbkdf2:sha256')

MENSAJE_LOGIN_FALLIDO = 'Correo o contraseña incorrectos.'
MENSAJE_PENDIENTE = ('Tu solicitud de administrador todavía está pendiente. '
                     'Un administrador debe aprobarla antes de que puedas entrar.')
MENSAJE_RECHAZADA = 'Tu solicitud de administrador fue rechazada. Comunícate con un administrador.'
# El aviso tiene dos partes para no repetir la frase en pantalla: el título lo escribe la plantilla
# y AYUDA_SIN_BD es la explicación. MENSAJE_SIN_BD (las dos juntas) se usa en las respuestas JSON.
TITULO_SIN_BD = 'Error en la conexión con el servidor de base de datos'
AYUDA_SIN_BD = 'Verifica que MySQL (XAMPP) esté encendido y vuelve a intentarlo.'
MENSAJE_SIN_BD = f'{TITULO_SIN_BD}. {AYUDA_SIN_BD}'


# ============================ 1. Datos para todas las plantillas =============
@app.context_processor
def datos_para_el_menu():
    """Agrega a CADA plantilla con sesión: cuántas alertas hay pendientes (globito del menú) y
    si se perdió la conexión con la base de datos (para mostrar el aviso rojo arriba)."""
    if 'id_user' not in session:
        return {}
    try:
        return {'alertas_pendientes': contar_alertas_pendientes(), 'bd_sin_conexion': False}
    except Exception as error:           # este bloque NUNCA debe romper la página
        db.session.rollback()
        return {'alertas_pendientes': None, 'bd_sin_conexion': isinstance(error, ERRORES_CONEXION)}


# ============================ 2. Acceso al sistema ===========================
@app.route('/')
def inicio():
    """Página raíz: con sesión va al dashboard, sin sesión al login."""
    if 'id_user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """GET muestra el formulario. POST valida las credenciales contra la tabla usuarios."""
    if 'id_user' in session:                      # ya entró: no tiene sentido ver el login
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')   # la contraseña no se recorta: los espacios cuentan

        try:
            usuario = buscar_usuario(email) if email else None

            if usuario is not None:
                credenciales_ok = check_password_hash(usuario['password_hash'], password)
            else:
                check_password_hash(_HASH_FALSO, password)  # gasta el mismo tiempo (ver _HASH_FALSO)
                credenciales_ok = False

            if credenciales_ok and usuario['activo']:
                _iniciar_sesion(usuario)
                return redirect(url_for('dashboard'))

            # Cuenta inactiva con la contraseña CORRECTA: solo entonces se explica el motivo
            # (así no se revela a desconocidos qué correos existen).
            if credenciales_ok:
                estado = estado_solicitud(usuario['id_user'])
                if estado == 'pendiente':
                    return render_template('login.html', error=MENSAJE_PENDIENTE), 403
                if estado == 'rechazada':
                    return render_template('login.html', error=MENSAJE_RECHAZADA), 403

        except ERRORES_CONEXION:
            # MySQL apagado, clave de base incorrecta, base inexistente...
            db.session.rollback()
            app.logger.exception('Sin conexión con la base de datos durante el login')
            return render_template('login.html', error_conexion=AYUDA_SIN_BD), 503

        # Mismo mensaje si falla el correo, la contraseña o la cuenta está inactiva sin solicitud.
        return render_template('login.html', error=MENSAJE_LOGIN_FALLIDO), 401

    # GET: antes de mostrar el formulario se comprueba que la base de datos responda.
    sin_conexion = None if base_de_datos_disponible() else AYUDA_SIN_BD
    return render_template('login.html', error_conexion=sin_conexion), (503 if sin_conexion else 200)


def _iniciar_sesion(usuario):
    """Guarda en la sesión quién es el usuario, su rol y sus permisos."""
    session.clear()            # descarta cualquier sesión anterior (evita fijación de sesión)
    session.permanent = True   # aplica la duración definida en conexion.py
    session['id_user'] = usuario['id_user']
    session['nombre'] = usuario['nombre_user']
    session['email'] = usuario['email']
    session['rol'] = usuario['rol']                                 # administrador / operativo / gerencial
    session['permisos'] = permisos_del_rol(usuario['id_tipo_user'])  # sale de la tabla permisos_rol
    marcar_acceso(usuario['id_user'])                                # actualiza ultimo_acceso


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    """Registro de usuarios nuevos.

    operativo / gerencial -> la cuenta queda activa y puede entrar de inmediato.
    administrador         -> queda pendiente: otro administrador debe aprobarla (módulo Administrar).
    """
    if 'id_user' in session:
        return redirect(url_for('dashboard'))

    try:
        roles = roles_disponibles()
    except ERRORES_CONEXION:
        db.session.rollback()
        app.logger.exception('Sin conexión con la base de datos en el registro')
        return render_template('registro.html', roles=[], datos={}, errores={},
                               error_conexion=AYUDA_SIN_BD), 503

    if request.method == 'POST':
        datos = {'nombre': request.form.get('nombre', '').strip(),
                 'email': request.form.get('email', '').strip().lower(),
                 'rol': request.form.get('rol', '')}
        password = request.form.get('password', '')
        confirmar = request.form.get('confirmar', '')

        errores = validar_registro(datos['nombre'], datos['email'], password, confirmar,
                                   datos['rol'], [r['nombre'] for r in roles])
        if not errores:
            try:
                ok, mensaje, _pendiente = registrar_usuario(datos['nombre'], datos['email'], password, datos['rol'])
            except ERRORES_CONEXION:
                db.session.rollback()
                app.logger.exception('Sin conexión con la base de datos al registrar')
                return render_template('registro.html', roles=roles, datos=datos, errores={},
                                       error_conexion=AYUDA_SIN_BD), 503
            except ProgrammingError:
                # La tabla solicitudes_registro no existe: falta ejecutar la migración 08.
                db.session.rollback()
                app.logger.exception('Falta la migración 08_solicitudes_registro.sql')
                return render_template('registro.html', roles=roles, datos=datos, errores={},
                                       error='Falta preparar la base de datos para solicitudes de administrador '
                                             '(ejecuta 08_solicitudes_registro.sql).'), 500
            if ok:
                flash(mensaje, 'success')
                return redirect(url_for('login'))
            errores = {'email': mensaje}          # el único error posible aquí es "correo ya registrado"
        # La contraseña NUNCA se devuelve al formulario; los demás datos sí, para no escribirlos de nuevo.
        return render_template('registro.html', roles=roles, datos=datos, errores=errores), 400

    return render_template('registro.html', roles=roles, datos={'rol': 'operativo'}, errores={})


@app.route('/logout')
def logout():
    """Cierra la sesión y vuelve al login."""
    session.clear()
    return redirect(url_for('login'))


@app.route('/olvido-contrasena')
def olvido_contrasena():
    """PENDIENTE: la recuperación usará la tabla recuperacion_password.
    Por ahora solo evita que el enlace del login rompa la página."""
    return render_template('mensaje.html', etiqueta='RECUPERAR ACCESO',
                           titulo='Recuperar contraseña',
                           texto='Esta función aún está en construcción. '
                                 'Por ahora pide a un administrador que restablezca tu contraseña.',
                           enlace=url_for('login'), texto_enlace='Volver al inicio de sesión')


# ============================ 3. Dashboard, API y simulador ==================
@app.route('/dashboard')
@login_requerido
def dashboard():
    """Pantalla principal. El menú muestra solo lo que el rol puede ver (ver layout.html)."""
    resumen, ultimas = None, []
    try:
        resumen = resumen_planta()
        ultimas = ultimas_lecturas(8) if puede_ver('MONITOREO') else []
    except Exception:
        db.session.rollback()
        app.logger.exception('Error consultando el resumen del dashboard')
        # Si la causa es la conexión, layout.html ya muestra el aviso rojo de "sin conexión".
    return render_template('dashboard.html', resumen=resumen, ultimas=ultimas,
                           estado_simulador=simulador.estado() if puede_ejecutar('CRUD') else None)


@app.route('/api/dashboard')
@api_requerida()
def api_dashboard():
    """JSON que dashboard.js consulta cada pocos segundos para refrescar tarjetas y lecturas."""
    try:
        puede_monitorear = bool(session.get('permisos', {}).get('MONITOREO', {}).get('ver'))
        return jsonify(resumen=resumen_planta(), ultimas=ultimas_lecturas(8) if puede_monitorear else [])
    except ERRORES_CONEXION:
        db.session.rollback()
        return jsonify(error=MENSAJE_SIN_BD), 503


# --- Simulador de lecturas (simulador/generar_lecturas.py) --------------------------------
# Solo el administrador (módulo CRUD con permiso de ejecutar) puede encenderlo: escribe en la tabla lecturas.
@app.route('/simulador/estado')
@api_requerida('CRUD', ejecutar=True)
def simulador_estado():
    """Estado del simulador en JSON (rondas, lecturas guardadas, errores...)."""
    return jsonify(simulador.estado())


@app.route('/simulador/iniciar', methods=['POST'])
@modulo_requerido('CRUD')
def simulador_iniciar():
    if not puede_ejecutar('CRUD'):
        abort(403)
    ok, mensaje = simulador.iniciar(request.form.get('intervalo', 5), request.form.get('historial_horas', 0))
    flash(mensaje, 'success' if ok else 'warning')
    return redirect(url_for('dashboard') + '#panelSimulador')


@app.route('/simulador/detener', methods=['POST'])
@modulo_requerido('CRUD')
def simulador_detener():
    if not puede_ejecutar('CRUD'):
        abort(403)
    ok, mensaje = simulador.detener()
    flash(mensaje, 'success' if ok else 'warning')
    return redirect(url_for('dashboard') + '#panelSimulador')


@app.route('/simulador/limpiar', methods=['POST'])
@modulo_requerido('CRUD')
def simulador_limpiar():
    """Borra TODAS las lecturas y alertas (para empezar una prueba desde cero)."""
    if not puede_ejecutar('CRUD'):
        abort(403)
    try:
        ok, mensaje = simulador.limpiar_datos()
        flash(mensaje, 'success' if ok else 'warning')
    except Exception:
        db.session.rollback()
        app.logger.exception('Error borrando lecturas')
        flash('No se pudieron borrar los datos. Revisa la consola de Flask.', 'danger')
    return redirect(url_for('dashboard') + '#panelSimulador')


# ============================ 4. Módulos =====================================
# Cada módulo exige el permiso de su clave (tabla modulos_sistema).
@app.route('/maquinas')
@modulo_requerido('MAQUINAS')
def maquinas():
    # Consulta las máquinas existentes y su asociación con áreas y sensores.
    try:
        return render_template('maquinas.html', maquinas=listar_maquinas())
    except Exception:
        db.session.rollback()
        app.logger.exception('Error consultando el módulo de máquinas')
        flash('No se pudo consultar máquinas. Revisa la consola de Flask y la base de datos.', 'danger')
        return render_template('maquinas.html', maquinas=[]), 500


@app.route('/monitoreo', methods=['GET', 'POST'])
@modulo_requerido('MONITOREO')
def monitoreo():
    """Muestra sensores y lecturas; permite registrar una lectura manual si el rol puede ejecutar."""
    if request.method == 'POST':
        # Verificar permiso en el servidor; ocultar el formulario en HTML no es suficiente.
        if not puede_ejecutar('MONITOREO'):
            abort(403)

        exito, mensaje = registrar_lectura(
            request.form.get('id_sensor', ''),
            request.form.get('valor', '')
        )
        flash(mensaje, 'success' if exito else 'danger')
        return redirect(url_for('monitoreo'))

    # El filtro por área es opcional. Si el parámetro no es entero, se ignora.
    area_texto = request.args.get('area', '').strip()
    try:
        area_seleccionada = int(area_texto) if area_texto else None
        if area_seleccionada is not None and area_seleccionada <= 0:
            area_seleccionada = None
    except ValueError:
        area_seleccionada = None

    try:
        areas = obtener_areas()
        sensores = obtener_sensores_monitoreo(id_area=area_seleccionada)
        # El selector de captura incluye todos los sensores activos, no solo el área filtrada.
        sensores_disponibles = obtener_sensores_monitoreo(solo_activos=True)
        historial = obtener_historial_lecturas(limite=100)
    except Exception:
        # Una consulta fallida puede dejar la transacción SQLAlchemy en estado abortado.
        db.session.rollback()
        app.logger.exception('Error al consultar el módulo de monitoreo')
        flash('No fue posible consultar los datos de monitoreo. Verifica la conexión con novadb.', 'danger')
        areas, sensores, sensores_disponibles, historial = [], [], [], []

    return render_template(
        'monitoreo.html',
        areas=areas,
        sensores=sensores,
        sensores_disponibles=sensores_disponibles,
        historial=historial,
        area_seleccionada=area_seleccionada
    )


@app.route('/alertas', methods=['GET', 'POST'])
@modulo_requerido('ALERTAS')
def alertas():
    # Solo un usuario con permiso de ejecución puede marcar alertas como atendidas.
    if request.method == 'POST':
        if not puede_ejecutar('ALERTAS'):
            abort(403)
        id_alerta = request.form.get('id_alerta', '').strip()
        if not id_alerta.isdigit():
            flash('Identificador de alerta inválido.', 'danger')
        else:
            try:
                ok, mensaje = atender_alerta(int(id_alerta), session['id_user'])
                flash(mensaje, 'success' if ok else 'warning')
            except Exception:
                app.logger.exception('Error atendiendo alerta')
                flash('No se pudo atender la alerta. Revisa la consola de Flask.', 'danger')
        return redirect(url_for('alertas'))
    try:
        return render_template('alertas.html', alertas=listar_alertas())
    except Exception:
        db.session.rollback()
        app.logger.exception('Error consultando alertas')
        flash('No se pudieron consultar las alertas. Verifica la base de datos.', 'danger')
        return render_template('alertas.html', alertas=[]), 500


@app.route('/historial')
@modulo_requerido('HISTORICOS')
def historial():
    # El historial es de consulta: no se permite editar eventos pasados desde esta pantalla.
    try:
        return render_template('historial.html', eventos=listar_historial())
    except Exception:
        db.session.rollback()
        app.logger.exception('Error consultando historial')
        flash('No se pudo consultar el historial. Ejecuta primero la migración SQL.', 'danger')
        return render_template('historial.html', eventos=[]), 500


@app.route('/mantenimiento', methods=['GET', 'POST'])
@modulo_requerido('MANTENIMIENTO')
def mantenimiento():
    # El permiso de ejecución se valida también en el servidor, no solo en el HTML.
    if request.method == 'POST':
        if not puede_ejecutar('MANTENIMIENTO'):
            abort(403)
        try:
            ok, mensaje = registrar_mantenimiento(request.form, session['id_user'])
            flash(mensaje, 'success' if ok else 'warning')
        except Exception:
            app.logger.exception('Error registrando mantenimiento')
            flash('No se pudo guardar el mantenimiento. Revisa la consola de Flask.', 'danger')
        return redirect(url_for('mantenimiento'))
    try:
        maquinas_lista, sensores_lista = listar_mantenimiento_catalogos()
        return render_template('mantenimiento.html', maquinas=maquinas_lista,
                               sensores=sensores_lista, puede_registrar=puede_ejecutar('MANTENIMIENTO'))
    except Exception:
        db.session.rollback()
        app.logger.exception('Error cargando el módulo de mantenimiento')
        flash('No se pudo cargar mantenimiento. Verifica la conexión y la migración SQL.', 'danger')
        return render_template('mantenimiento.html', maquinas=[], sensores=[],
                               puede_registrar=puede_ejecutar('MANTENIMIENTO')), 500


@app.route('/administrar')
@modulo_requerido('CRUD')          # solo el rol administrador tiene este permiso
def administrar():
    """Administración de cuentas: solicitudes de administrador pendientes y usuarios registrados."""
    pendientes, resueltas, usuarios, falta_migracion = [], [], [], False
    try:
        usuarios = listar_usuarios()
        try:
            pendientes = listar_solicitudes(pendientes=True)
            resueltas = listar_solicitudes(pendientes=False, limite=20)
        except ProgrammingError:       # todavía no existe la tabla solicitudes_registro
            db.session.rollback()
            falta_migracion = True
    except Exception:
        db.session.rollback()
        app.logger.exception('Error consultando la administración de cuentas')
        flash('No se pudo consultar la información de usuarios. Verifica la base de datos.', 'danger')
    return render_template('administrar.html', pendientes=pendientes, resueltas=resueltas,
                           usuarios=usuarios, falta_migracion=falta_migracion,
                           puede_decidir=puede_ejecutar('CRUD'))


@app.route('/administrar/solicitudes/<int:id_solicitud>/<accion>', methods=['POST'])
@modulo_requerido('CRUD')
def decidir_solicitud(id_solicitud, accion):
    """Aprueba o rechaza una solicitud de cuenta (accion = 'aprobar' o 'rechazar')."""
    if not puede_ejecutar('CRUD'):
        abort(403)
    if accion not in ('aprobar', 'rechazar'):
        abort(404)
    try:
        ok, mensaje = resolver_solicitud(id_solicitud, accion == 'aprobar', session['id_user'])
        flash(mensaje, 'success' if ok else 'warning')
    except Exception:
        db.session.rollback()
        app.logger.exception('Error resolviendo la solicitud de cuenta')
        flash('No se pudo resolver la solicitud. Revisa la consola de Flask.', 'danger')
    return redirect(url_for('administrar'))


# ============================ 5. Errores =====================================
def _pagina_mensaje(etiqueta, titulo, texto, estado, enlace=None, texto_enlace=None):
    """Tarjeta de mensaje (mensaje.html) usada por los manejadores de error."""
    destino = enlace or (url_for('dashboard') if 'id_user' in session else url_for('login'))
    return render_template('mensaje.html', etiqueta=etiqueta, titulo=titulo, texto=texto, enlace=destino,
                           texto_enlace=texto_enlace or ('Volver al inicio' if 'id_user' in session
                                                         else 'Volver al inicio de sesión')), estado


@app.errorhandler(400)
def solicitud_invalida(error):
    """Casi siempre: el token CSRF no coincide (formulario vencido o enviado desde otro sitio)."""
    return _pagina_mensaje('SOLICITUD NO VÁLIDA', 'No se pudo procesar el formulario',
                           'La página venció o el formulario no es válido. Vuelve atrás, recárgala e inténtalo de nuevo.', 400)


@app.errorhandler(403)
def acceso_denegado(error):
    """El usuario tiene sesión pero su rol no puede ver ese módulo."""
    return _pagina_mensaje('ACCESO DENEGADO', 'No tienes permiso', 'Tu perfil no puede ver este módulo.', 403)


def _sin_conexion(error):
    """Cualquier ruta que no atrapó el error de conexión termina aquí."""
    try:
        db.session.rollback()
    except Exception:
        pass
    app.logger.error('Sin conexión con la base de datos: %s', error)
    return _pagina_mensaje('SIN CONEXIÓN', TITULO_SIN_BD, AYUDA_SIN_BD, 503)


for _clase in ERRORES_CONEXION:      # OperationalError e InterfaceError
    app.register_error_handler(_clase, _sin_conexion)
