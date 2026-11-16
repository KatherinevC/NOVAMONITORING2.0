"""Operaciones de negocio para máquinas, alertas, mantenimiento e historial.

IMPORTANTE: las consultas usan parámetros (:nombre), nunca concatenan entradas del usuario.
Cada cambio relevante se guarda en historial para dejar trazabilidad.
"""
from sqlalchemy import text
from conexion import db


def listar_maquinas():
    """Lista máquinas con su área y cantidad de sensores asociados."""
    # LEFT JOIN: una máquina sin sensores también aparece (con 0). COUNT(DISTINCT ...) evita contar doble.
    q = text("""
        SELECT m.id_maquina, m.codigo, m.nombre_maquina, m.tipo_maquina,
               m.estado, m.ubicacion, a.nombre_area,
               COUNT(DISTINCT s.id_sensor) AS total_sensores
        FROM maquinas m
        JOIN areas a ON a.id_area = m.id_area
        LEFT JOIN sensores s ON s.id_maquina = m.id_maquina
        GROUP BY m.id_maquina, m.codigo, m.nombre_maquina, m.tipo_maquina,
                 m.estado, m.ubicacion, a.nombre_area
        ORDER BY a.nombre_area, m.nombre_maquina
    """)
    return db.session.execute(q).mappings().all()


def listar_alertas():
    """Lista alertas nuevas y atendidas, con el sensor, máquina y responsable."""
    # ORDER BY atendida ASC: las pendientes (0) salen primero; dentro de cada grupo, las más recientes.
    # LEFT JOIN usuarios: una alerta pendiente todavía no tiene responsable.
    q = text("""
        SELECT al.id_alerta, al.tipo, al.valor, al.fecha_hora, al.atendida,
               al.atendida_en, al.id_sensor, al.atendida_por,
               s.codigo AS sensor_codigo, COALESCE(s.nombre_variable, ts.nom_sensor) AS variable,
               ts.unidad_medida, m.codigo AS maquina_codigo, m.nombre_maquina,
               u.nombre_user AS responsable
        FROM alertas al
        JOIN sensores s ON s.id_sensor = al.id_sensor
        JOIN tipos_sensor ts ON ts.id_tipo_sensor = s.id_tipo_sensor
        JOIN maquinas m ON m.id_maquina = s.id_maquina
        LEFT JOIN usuarios u ON u.id_user = al.atendida_por
        ORDER BY al.atendida ASC, al.fecha_hora DESC
    """)
    return db.session.execute(q).mappings().all()


def atender_alerta(id_alerta, id_user):
    """Marca una alerta como atendida y genera su evento en historial."""
    # Todo lo que sigue es UNA transacción: o se guardan la atención de la alerta Y el evento en
    # historial, o no se guarda nada. Si algo falla, SQLAlchemy deshace los cambios solo.
    with db.session.begin():
        # FOR UPDATE bloquea la fila para que dos personas no atiendan la misma alerta a la vez.
        alerta = db.session.execute(text("""
            SELECT al.id_alerta, al.id_sensor, al.tipo, al.valor, s.id_maquina
            FROM alertas al JOIN sensores s ON s.id_sensor = al.id_sensor
            WHERE al.id_alerta = :id AND al.atendida = 0
            FOR UPDATE
        """), {"id": id_alerta}).mappings().first()
        if not alerta:
            return False, 'La alerta no existe o ya fue atendida.'
        # Se guarda QUIÉN la atendió (id del usuario de la sesión) y CUÁNDO.
        db.session.execute(text("""
            UPDATE alertas SET atendida = 1, atendida_por = :usuario,
                   atendida_en = CURRENT_TIMESTAMP
            WHERE id_alerta = :id
        """), {"usuario": id_user, "id": id_alerta})
        # Constancia en la bitácora (tabla historial) para tener trazabilidad.
        db.session.execute(text("""
            INSERT INTO historial
              (tipo_evento, descripcion, fecha_hora, estado, id_alerta,
               id_maquina, id_sensor, id_user)
            VALUES ('alerta', :descripcion, CURRENT_TIMESTAMP, 'completado',
                    :alerta, :maquina, :sensor, :usuario)
        """), {"descripcion": f"Alerta {alerta['tipo']} atendida; valor registrado: {alerta['valor']}",
               "alerta": alerta['id_alerta'], "maquina": alerta['id_maquina'],
               "sensor": alerta['id_sensor'], "usuario": id_user})
    return True, 'Alerta marcada como atendida y registrada en el historial.'


def listar_mantenimiento_catalogos():
    """Datos que alimentan las listas desplegables del formulario de mantenimiento."""
    maquinas = db.session.execute(text("""
        SELECT id_maquina, codigo, nombre_maquina FROM maquinas ORDER BY codigo
    """)).mappings().all()
    sensores = db.session.execute(text("""
        SELECT s.id_sensor, s.codigo, COALESCE(s.nombre_variable, ts.nom_sensor) AS variable,
               m.codigo AS maquina_codigo
        FROM sensores s JOIN tipos_sensor ts ON ts.id_tipo_sensor=s.id_tipo_sensor
        JOIN maquinas m ON m.id_maquina=s.id_maquina
        WHERE s.activo=1 ORDER BY m.codigo, s.codigo
    """)).mappings().all()
    return maquinas, sensores


def registrar_mantenimiento(form, id_user):
    """Guarda mantenimiento y, opcionalmente, asocia un sensor/dispositivo a revisar."""
    maquina = form.get('id_maquina', '').strip()
    tipo = form.get('tipo', '').strip()
    descripcion = form.get('descripcion', '').strip()
    estado = form.get('estado', 'completado').strip()
    sensor = form.get('id_sensor', '').strip()
    if not maquina.isdigit() or tipo not in ('preventivo', 'correctivo', 'predictivo'):
        return False, 'Selecciona una máquina y un tipo de mantenimiento válido.'
    if len(descripcion) < 5:
        return False, 'La descripción debe explicar la actividad realizada (mínimo 5 caracteres).'
    if estado not in ('registrado', 'en_proceso', 'completado', 'cancelado'):
        return False, 'El estado seleccionado no es válido.'
    sensor_id = int(sensor) if sensor.isdigit() else None
    # Validaciones del lado del servidor: el HTML puede ser manipulado, por eso se repiten aquí.
    # Desde aquí es una sola transacción: mantenimiento + vínculo con el sensor + historial.
    with db.session.begin():
        m = db.session.execute(text("SELECT id_maquina FROM maquinas WHERE id_maquina=:id"),
                                {"id": int(maquina)}).first()
        if not m:
            return False, 'La máquina seleccionada no existe.'
        if sensor_id:
            sensor_row = db.session.execute(text("SELECT id_sensor, id_maquina, id_dispositivo FROM sensores WHERE id_sensor=:id"),
                                            {"id": sensor_id}).mappings().first()
            if not sensor_row or sensor_row['id_maquina'] != int(maquina):
                return False, 'El sensor debe pertenecer a la máquina seleccionada.'
        result = db.session.execute(text("""
            INSERT INTO mantenimientos (id_maquina, id_user, tipo, descripcion, fecha, estado)
            VALUES (:maquina, :usuario, :tipo, :descripcion, CURRENT_TIMESTAMP, :estado)
        """), {"maquina": int(maquina), "usuario": id_user, "tipo": tipo, "descripcion": descripcion, "estado": estado})
        id_manteni = result.lastrowid   # id que MySQL asignó al mantenimiento recién creado
        # La tabla existente mantenimiento_sensores se relaciona con dispositivos_sensor.
        # Solo se crea ese vínculo si el sensor tiene id_dispositivo.
        if sensor_id:
            if sensor_row['id_dispositivo']:
                db.session.execute(text("""
                    INSERT INTO mantenimiento_sensores (id_manteni, id_dispositivo, observacion)
                    VALUES (:mant, :disp, :obs)
                """), {"mant": id_manteni, "disp": sensor_row['id_dispositivo'], "obs": descripcion[:255]})
        db.session.execute(text("""
            INSERT INTO historial (tipo_evento, descripcion, fecha_hora, estado,
                                  id_manteni, id_maquina, id_sensor, id_user)
            VALUES ('mantenimiento', :descripcion, CURRENT_TIMESTAMP, :estado,
                    :mant, :maquina, :sensor, :usuario)
        """), {"descripcion": descripcion, "estado": estado, "mant": id_manteni,
               "maquina": int(maquina), "sensor": sensor_id, "usuario": id_user})
    return True, 'Mantenimiento registrado y agregado al historial.'


def listar_historial():
    """Historial unificado: muestra mantenimiento, alerta, máquina/sensor y operario."""
    # Todos los JOIN son LEFT porque cada evento solo trae algunos de esos datos (un evento de
    # "sistema" no tiene máquina ni sensor). LIMIT 500 evita traer una tabla enorme a la pantalla.
    q = text("""
        SELECT h.id_historial, h.tipo_evento, h.descripcion, h.fecha_hora, h.estado,
               h.id_manteni, h.id_alerta, h.id_maquina, h.id_sensor,
               m.codigo AS maquina_codigo, m.nombre_maquina,
               s.codigo AS sensor_codigo, COALESCE(s.nombre_variable, ts.nom_sensor) AS variable,
               u.nombre_user AS operario, al.tipo AS tipo_alerta
        FROM historial h
        LEFT JOIN maquinas m ON m.id_maquina=h.id_maquina
        LEFT JOIN sensores s ON s.id_sensor=h.id_sensor
        LEFT JOIN tipos_sensor ts ON ts.id_tipo_sensor=s.id_tipo_sensor
        LEFT JOIN usuarios u ON u.id_user=h.id_user
        LEFT JOIN alertas al ON al.id_alerta=h.id_alerta
        ORDER BY h.fecha_hora DESC, h.id_historial DESC
        LIMIT 500
    """)
    return db.session.execute(q).mappings().all()
