"""
model/monitoreo.py
------------------
Consultas y operaciones del módulo de monitoreo de NOVA.

Responsabilidades:
- Consultar sensores, máquina, área, unidad y última lectura.
- Consultar el historial reciente de lecturas.
- Registrar una lectura manual validando que el sensor exista y esté activo.

Las consultas usan SQL parametrizado para evitar inyección SQL.
No se crean tablas nuevas: se utilizan las tablas existentes de novadb.
"""
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from conexion import db


def obtener_areas():
    """Devuelve las áreas disponibles para el filtro de monitoreo."""
    consulta = text("""
        SELECT id_area, nombre_area
        FROM areas
        ORDER BY nombre_area
    """)
    return db.session.execute(consulta).mappings().all()


def obtener_sensores_monitoreo(id_area=None, solo_activos=True):
    """Lista sensores con su última lectura, aunque todavía no tengan mediciones.

    El estado se calcula para la pantalla a partir de los umbrales:
    - Sin lectura: el sensor aún no tiene mediciones.
    - Bajo mínimo / Sobre máximo: lectura fuera del rango configurado.
    - Normal: lectura dentro del rango o sin umbrales definidos.
    Esto no modifica el estado de la máquina ni reemplaza las alertas SQL.
    """
    condiciones = []
    parametros = {}

    if solo_activos:
        condiciones.append("s.activo = 1")
    if id_area is not None:
        condiciones.append("m.id_area = :id_area")
        parametros["id_area"] = id_area

    where_sql = "WHERE " + " AND ".join(condiciones) if condiciones else ""

    consulta = text(f"""
        SELECT
            s.id_sensor,
            s.codigo AS codigo_sensor,
            COALESCE(s.nombre_variable, ts.nom_sensor) AS variable,
            ts.unidad_medida,
            s.umbral_min,
            s.umbral_max,
            s.activo,
            m.id_maquina,
            m.codigo AS codigo_maquina,
            m.nombre_maquina,
            m.estado AS estado_maquina,
            a.id_area,
            a.nombre_area,
            ultima.valor AS ultima_lectura,
            ultima.fecha_hora AS fecha_ultima_lectura,
            CASE
                WHEN ultima.id_lectura IS NULL THEN 'sin_lectura'
                WHEN s.umbral_min IS NOT NULL AND ultima.valor < s.umbral_min THEN 'bajo_minimo'
                WHEN s.umbral_max IS NOT NULL AND ultima.valor > s.umbral_max THEN 'sobre_maximo'
                ELSE 'normal'
            END AS estado_lectura
        FROM sensores AS s
        INNER JOIN maquinas AS m ON m.id_maquina = s.id_maquina
        INNER JOIN areas AS a ON a.id_area = m.id_area
        INNER JOIN tipos_sensor AS ts ON ts.id_tipo_sensor = s.id_tipo_sensor
        -- Última lectura de cada sensor: se toma la MÁS RECIENTE POR FECHA (no la de id más alto).
        -- Así sigue siendo correcta aunque se carguen lecturas antiguas después de otras nuevas
        -- (como hace el simulador al precargar historial) y aprovecha el índice
        -- idx_sensor_fecha, por lo que no se vuelve lenta cuando la tabla lecturas crece.
        LEFT JOIN lecturas AS ultima
               ON ultima.id_lectura = (
                    SELECT l2.id_lectura
                    FROM lecturas AS l2
                    WHERE l2.id_sensor = s.id_sensor
                    ORDER BY l2.fecha_hora DESC, l2.id_lectura DESC
                    LIMIT 1)
        {where_sql}
        ORDER BY a.nombre_area, m.nombre_maquina, s.codigo
    """)
    return db.session.execute(consulta, parametros).mappings().all()


def obtener_historial_lecturas(id_sensor=None, limite=100):
    """Devuelve lecturas recientes; opcionalmente limita la consulta a un sensor."""
    limite = max(1, min(int(limite), 500))
    parametros = {"limite": limite}
    filtro = ""
    if id_sensor is not None:
        filtro = "WHERE l.id_sensor = :id_sensor"
        parametros["id_sensor"] = id_sensor

    # El límite es entero validado antes de interpolarse en SQL.
    consulta = text(f"""
        SELECT l.id_lectura, l.id_sensor, l.valor, l.fecha_hora,
               s.codigo AS codigo_sensor,
               COALESCE(s.nombre_variable, ts.nom_sensor) AS variable,
               ts.unidad_medida,
               m.codigo AS codigo_maquina,
               m.nombre_maquina,
               a.nombre_area
        FROM lecturas AS l
        INNER JOIN sensores AS s ON s.id_sensor = l.id_sensor
        INNER JOIN tipos_sensor AS ts ON ts.id_tipo_sensor = s.id_tipo_sensor
        INNER JOIN maquinas AS m ON m.id_maquina = s.id_maquina
        INNER JOIN areas AS a ON a.id_area = m.id_area
        {filtro}
        ORDER BY l.fecha_hora DESC, l.id_lectura DESC
        LIMIT {limite}
    """)
    return db.session.execute(consulta, parametros).mappings().all()


def registrar_lectura(id_sensor, valor):
    """Registra una lectura para un sensor activo.

    Devuelve (True, mensaje) si se guardó, o (False, mensaje) si la validación falla.
    El trigger trg_lectura_alerta de MySQL se encarga de crear una alerta cuando
    el valor supera umbral_max o queda por debajo de umbral_min.
    """
    try:
        sensor_id = int(id_sensor)
        valor_decimal = Decimal(str(valor))
    except (TypeError, ValueError, InvalidOperation):
        return False, "Selecciona un sensor válido e introduce un valor numérico."

    if sensor_id <= 0 or not valor_decimal.is_finite():
        return False, "El sensor y el valor deben ser válidos."

    # DECIMAL(12,4): permite 8 dígitos enteros y 4 decimales.
    if abs(valor_decimal) >= Decimal("100000000"):
        return False, "El valor excede el rango permitido por DECIMAL(12,4)."

    consulta_sensor = text("""
        SELECT id_sensor
        FROM sensores
        WHERE id_sensor = :id_sensor AND activo = 1
    """)
    sensor = db.session.execute(consulta_sensor, {"id_sensor": sensor_id}).first()
    if sensor is None:
        return False, "El sensor no existe o está inactivo. No se registró la lectura."

    try:
        insertar = text("""
            INSERT INTO lecturas (id_sensor, valor, fecha_hora)
            VALUES (:id_sensor, :valor, CURRENT_TIMESTAMP(3))
        """)
        db.session.execute(insertar, {
            "id_sensor": sensor_id,
            "valor": valor_decimal,
        })
        # El trigger de la base de datos se ejecuta al insertar la lectura.
        db.session.commit()
        return True, "Lectura registrada correctamente. Se evaluaron los umbrales configurados."
    except Exception:
        db.session.rollback()
        # No exponemos detalles internos de MySQL al usuario final.
        return False, "No fue posible registrar la lectura. Revisa la conexión y la estructura de la base de datos."


# ============================================================================
# Datos del dashboard (tarjetas, menú y verificación del simulador)
# ============================================================================
def _fecha_a_texto(valor):
    """Las fechas se entregan como texto 'AAAA-MM-DD HH:MM:SS' para poder enviarlas como JSON."""
    return valor.strftime('%Y-%m-%d %H:%M:%S') if hasattr(valor, 'strftime') else valor


def contar_alertas_pendientes():
    """Cuántas alertas siguen sin atender. Se muestra en el menú de todas las páginas.

    Usa el índice idx_pendientes (atendida, fecha_hora): es una consulta muy barata.
    """
    return db.session.execute(text("SELECT COUNT(*) FROM alertas WHERE atendida = 0")).scalar()


def resumen_planta():
    """Los números de las 4 tarjetas del dashboard y el estado de llegada de datos."""
    por_estado = {fila['estado']: fila['total'] for fila in db.session.execute(
        text("SELECT estado, COUNT(*) AS total FROM maquinas GROUP BY estado")).mappings().all()}
    ultima = db.session.execute(text("SELECT MAX(fecha_hora) FROM lecturas")).scalar()   # usa idx_fecha
    hace_un_minuto = datetime.now() - timedelta(minutes=1)
    # Ojo: NO se cuenta toda la tabla lecturas (crece sin parar), solo el último minuto.
    ultimo_minuto = db.session.execute(
        text("SELECT COUNT(*) FROM lecturas WHERE fecha_hora >= :desde"), {"desde": hace_un_minuto}).scalar()
    return {
        "maquinas_total": sum(por_estado.values()),
        "operativas": por_estado.get("operativa", 0),
        # "En seguimiento" = máquinas que alguien está atendiendo o que se detuvieron
        "en_seguimiento": por_estado.get("mantenimiento", 0) + por_estado.get("detenida", 0),
        "alertas_pendientes": contar_alertas_pendientes(),
        "lecturas_ultimo_minuto": ultimo_minuto,
        "ultima_lectura": _fecha_a_texto(ultima) if ultima is not None else None,
    }


def ultimas_lecturas(limite=8):
    """Las lecturas guardadas más recientes (sirven para comprobar que el simulador escribe)."""
    limite = max(1, min(int(limite), 50))
    filas = db.session.execute(text("""
        SELECT l.id_lectura, l.valor, l.fecha_hora,
               s.codigo AS codigo_sensor,
               COALESCE(s.nombre_variable, ts.nom_sensor) AS variable,
               ts.unidad_medida, m.codigo AS codigo_maquina
        FROM lecturas AS l
        INNER JOIN sensores AS s       ON s.id_sensor = l.id_sensor
        INNER JOIN tipos_sensor AS ts  ON ts.id_tipo_sensor = s.id_tipo_sensor
        INNER JOIN maquinas AS m       ON m.id_maquina = s.id_maquina
        ORDER BY l.fecha_hora DESC, l.id_lectura DESC
        LIMIT :limite
    """), {"limite": limite}).mappings().all()
    return [{"id_lectura": f["id_lectura"], "valor": float(f["valor"]), "fecha_hora": _fecha_a_texto(f["fecha_hora"]),
             "sensor": f["codigo_sensor"], "variable": f["variable"], "unidad": f["unidad_medida"],
             "maquina": f["codigo_maquina"]} for f in filas]


# ============================================================================
# Datos para las GRÁFICAS del dashboard (static/js/graficas.js)
# ============================================================================
# Ventanas de tiempo permitidas (minutos). Se limitan a propósito: con el simulador a 2 s por ronda,
# una hora son 1800 lecturas por sensor y cada gráfica se pide cada pocos segundos.
VENTANAS_MINUTOS = (5, 15, 60)


def _a_datetime(valor):
    """MySQL entrega datetime; otros motores pueden entregar texto 'AAAA-MM-DD HH:MM:SS'."""
    if isinstance(valor, datetime):
        return valor
    return datetime.strptime(str(valor)[:19], "%Y-%m-%d %H:%M:%S")


def _reducir(puntos, maximo):
    """Reduce una serie a ~`maximo` puntos SIN perder los picos.

    Quedarse con "1 de cada k" podría borrar justo la lectura que cruzó el umbral. Por eso la serie
    se parte en grupos y de cada grupo se conserva el punto que más se aleja del promedio del grupo.
    El último punto (el más reciente) siempre se conserva.
    """
    if len(puntos) <= maximo:
        return puntos
    tam = -(-len(puntos) // maximo)                       # tamaño de grupo, dividiendo hacia arriba
    resultado = []
    for i in range(0, len(puntos), tam):
        grupo = puntos[i:i + tam]
        promedio = sum(p[1] for p in grupo) / len(grupo)
        resultado.append(max(grupo, key=lambda p: abs(p[1] - promedio)))
    if resultado[-1] is not puntos[-1]:
        resultado.append(puntos[-1])
    return resultado


def _estadisticas(valores, minimo, maximo):
    """Resumen de la ventana completa (antes de reducir): sirve para verificar la simulación."""
    if not valores:
        return {"n": 0, "min": None, "max": None, "promedio": None, "ultimo": None, "fuera": 0}
    fuera = sum(1 for v in valores if (maximo is not None and v > maximo) or (minimo is not None and v < minimo))
    return {"n": len(valores), "min": min(valores), "max": max(valores),
            "promedio": sum(valores) / len(valores), "ultimo": valores[-1], "fuera": fuera}


def _ventana(minutos):
    """Devuelve (inicio, fin, segundos_desde_la_ultima_lectura).

    La ventana se cuenta hacia atrás desde la lectura MÁS RECIENTE de la tabla (no desde "ahora"),
    así las gráficas no quedan vacías si el simulador se detuvo hace un rato. Usa el índice idx_fecha.
    """
    ultima = db.session.execute(text("SELECT MAX(fecha_hora) FROM lecturas")).scalar()
    if ultima is None:
        return None, None, None
    fin = _a_datetime(ultima)
    return fin - timedelta(minutes=minutos), fin, max(0, int((datetime.now() - fin).total_seconds()))


def catalogo_graficas():
    """Áreas -> máquinas -> sensores, para llenar los selectores de las gráficas."""
    filas = db.session.execute(text("""
        SELECT a.id_area, a.nombre_area, m.id_maquina, m.codigo AS maquina, m.nombre_maquina,
               s.id_sensor, COALESCE(s.nombre_variable, ts.nom_sensor) AS variable,
               ts.unidad_medida AS unidad
        FROM sensores s
        JOIN maquinas m      ON m.id_maquina = s.id_maquina
        JOIN areas a         ON a.id_area = m.id_area
        JOIN tipos_sensor ts ON ts.id_tipo_sensor = s.id_tipo_sensor
        WHERE s.activo = 1
        ORDER BY a.id_area, m.codigo, s.codigo
    """)).mappings().all()
    areas, maquinas = {}, {}
    for f in filas:
        area = areas.setdefault(f["id_area"], {"id_area": f["id_area"], "nombre": f["nombre_area"], "maquinas": []})
        if f["id_maquina"] not in maquinas:
            maquinas[f["id_maquina"]] = {"id_maquina": f["id_maquina"], "codigo": f["maquina"],
                                         "nombre": f["nombre_maquina"], "sensores": []}
            area["maquinas"].append(maquinas[f["id_maquina"]])
        maquinas[f["id_maquina"]]["sensores"].append(
            {"id_sensor": f["id_sensor"], "variable": f["variable"], "unidad": f["unidad"]})
    return {"areas": list(areas.values())}


def _umbral(valor):
    return float(valor) if valor is not None else None


def serie_sensor(id_sensor, minutos=15, max_puntos=300):
    """Lecturas de UN sensor dentro de la ventana, con sus umbrales y estadísticas. None si no existe."""
    info = db.session.execute(text("""
        SELECT s.id_sensor, s.codigo AS sensor, m.codigo AS maquina,
               COALESCE(s.nombre_variable, ts.nom_sensor) AS variable,
               ts.unidad_medida AS unidad, s.umbral_min, s.umbral_max
        FROM sensores s
        JOIN maquinas m      ON m.id_maquina = s.id_maquina
        JOIN tipos_sensor ts ON ts.id_tipo_sensor = s.id_tipo_sensor
        WHERE s.id_sensor = :id
    """), {"id": id_sensor}).mappings().first()
    if not info:
        return None
    minimo, maximo = _umbral(info["umbral_min"]), _umbral(info["umbral_max"])
    inicio, fin, atraso = _ventana(minutos)
    puntos = []
    if inicio is not None:
        filas = db.session.execute(text("""
            SELECT fecha_hora, valor FROM lecturas
            WHERE id_sensor = :id AND fecha_hora >= :desde
            ORDER BY fecha_hora
        """), {"id": id_sensor, "desde": inicio}).all()
        puntos = [[_fecha_a_texto(f[0]), float(f[1])] for f in filas]
    return {"id_sensor": info["id_sensor"], "sensor": info["sensor"], "maquina": info["maquina"],
            "variable": info["variable"], "unidad": info["unidad"], "umbral_min": minimo, "umbral_max": maximo,
            "minutos": minutos, "segundos_desde_ultimo": atraso,
            "estadisticas": _estadisticas([p[1] for p in puntos], minimo, maximo),
            "puntos": _reducir(puntos, max_puntos)}


def series_maquina(id_maquina, minutos=15, max_puntos=100):
    """Las series de TODOS los sensores de una máquina (para las mini-gráficas). None si no existe."""
    maquina = db.session.execute(text("SELECT id_maquina, codigo, nombre_maquina FROM maquinas WHERE id_maquina = :m"),
                                 {"m": id_maquina}).mappings().first()
    if not maquina:
        return None
    sensores = db.session.execute(text("""
        SELECT s.id_sensor, COALESCE(s.nombre_variable, ts.nom_sensor) AS variable,
               ts.unidad_medida AS unidad, s.umbral_min, s.umbral_max
        FROM sensores s JOIN tipos_sensor ts ON ts.id_tipo_sensor = s.id_tipo_sensor
        WHERE s.id_maquina = :m AND s.activo = 1
        ORDER BY s.codigo
    """), {"m": id_maquina}).mappings().all()
    inicio, fin, atraso = _ventana(minutos)
    por_sensor = {s["id_sensor"]: [] for s in sensores}
    if inicio is not None and sensores:
        filas = db.session.execute(text("""
            SELECT l.id_sensor, l.fecha_hora, l.valor
            FROM lecturas l JOIN sensores s ON s.id_sensor = l.id_sensor
            WHERE s.id_maquina = :m AND l.fecha_hora >= :desde
            ORDER BY l.id_sensor, l.fecha_hora
        """), {"m": id_maquina, "desde": inicio}).all()
        for id_s, fecha, valor in filas:
            por_sensor[id_s].append([_fecha_a_texto(fecha), float(valor)])
    resultado = []
    for s in sensores:
        minimo, maximo = _umbral(s["umbral_min"]), _umbral(s["umbral_max"])
        puntos = por_sensor[s["id_sensor"]]
        resultado.append({"id_sensor": s["id_sensor"], "variable": s["variable"], "unidad": s["unidad"],
                          "umbral_min": minimo, "umbral_max": maximo,
                          "estadisticas": _estadisticas([p[1] for p in puntos], minimo, maximo),
                          "puntos": _reducir(puntos, max_puntos)})
    return {"id_maquina": maquina["id_maquina"], "codigo": maquina["codigo"], "nombre": maquina["nombre_maquina"],
            "minutos": minutos, "segundos_desde_ultimo": atraso, "sensores": resultado}


def resumen_graficas():
    """Datos de la dona (estado actual de los sensores) y de las barras (alertas por área)."""
    conteo = Counter(s["estado_lectura"] for s in obtener_sensores_monitoreo(solo_activos=True))
    estados = {clave: conteo.get(clave, 0) for clave in ("normal", "sobre_maximo", "bajo_minimo", "sin_lectura")}
    por_area = db.session.execute(text("""
        SELECT a.nombre_area AS area, COUNT(*) AS total
        FROM alertas al
        JOIN sensores s ON s.id_sensor = al.id_sensor
        JOIN maquinas m ON m.id_maquina = s.id_maquina
        JOIN areas a    ON a.id_area = m.id_area
        WHERE al.atendida = 0
        GROUP BY a.id_area, a.nombre_area
        ORDER BY total DESC, a.nombre_area
    """)).mappings().all()
    return {"estados": estados, "alertas_por_area": [{"area": f["area"], "total": f["total"]} for f in por_area]}
