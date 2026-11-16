#!/usr/bin/env python3
"""
simulador/generar_lecturas.py
-----------------------------
Este archivo hace de "sensores de mentira": cada cierto tiempo inventa una lectura
creíble para cada uno de los 131 canales de la planta y la guarda en la tabla
`lecturas` de novadb. Así el dashboard tiene datos que mostrar sin necesitar
máquinas reales.

Se puede usar de DOS maneras:

  1) Desde el dashboard (lo normal): el administrador pulsa "Iniciar" en el panel
     "Simulador de lecturas". Por debajo, simulador/servicio.py llama a las
     funciones de este archivo en un hilo de fondo.

  2) Desde la terminal, como siempre (útil para cargar mucho historial de golpe).
     Ejecútalo desde la carpeta nova/:
         python simulador/generar_lecturas.py --limpiar --horas 6 --intervalo 30
         python simulador/generar_lecturas.py --live --intervalo 5
         python simulador/generar_lecturas.py --dry-run     (no inserta nada)

IMPORTANTE: no uses las dos maneras a la vez, o cada canal recibirá lecturas dobles.

Requiere haber importado novadb.sql y los scripts SQL 01 a 06 (el 06 pone los
umbrales; sin umbrales el trigger no crea alertas).

De dónde salen los valores normales (columna "origen" del PERFIL):
    E = ejemplo numérico que aparece en el Excel del proyecto
    S = valor supuesto (el Excel no da uno) -> ajústalo cuando tengas datos reales
"""
import argparse
import random
import time
from datetime import datetime, timedelta


def P(media, sd, lo=0.0, hi=None, origen='S'):
    """Perfil de un canal numérico: media, desviación, límites físicos (lo=None: sin mínimo)."""
    return {'media': media, 'sd': sd, 'lo': lo, 'hi': hi, 'origen': origen}


E = 'E'
# (código del sensor físico) -> {nombre_variable: perfil}
PERFIL = {
 'EQ-LOG-01-S2': {'Presión hidráulica del cilindro de elevación': P(154.2, 9, 0, 250, E),   # 1850.5 kg de 3000 kg
                  'Altura de elevación del mástil': P(2500, 600, 0, 6000),
                  'Ángulo de inclinación del mástil': P(3, 1.2, -5, 12)},
 'EQ-LOG-01-S3': {'Ángulo de dirección': P(0, 22, -90, 90),
                  'Velocidad del montacargas': P(8, 2)},
 'EQ-LOG-02-S1': {'Distancia mínima a obstáculo': P(4.0, 1.2)},
 'EQ-LOG-02-S3': {'Inclinación del chasis eje X': P(0.4, 0.3, None), 'Inclinación del chasis eje Y': P(0.3, 0.3, None)},
 'EQ-LOG-03-S1': {'Vibración RMS del motorreductor': P(2.0, 0.3)},
 'EQ-LOG-03-S2': {'Corriente fase U del motorreductor': P(8.5, 0.3, origen=E),
                  'Corriente fase V del motorreductor': P(8.4, 0.3),
                  'Corriente fase W del motorreductor': P(8.6, 0.3)},
 'EQ-EST-04-S1': {'Presión hidráulica': P(180, 8)},
 'EQ-EST-04-S2': {'Constante dieléctrica del aceite': P(2.2, 0.03),
                  'Contenido de agua en el aceite': P(150, 20),
                  'Temperatura del aceite': P(48, 3)},
 'EQ-EST-04-S3': {'Posición del vástago del cilindro': P(320.5, 80, origen=E),
                  'Velocidad del vástago': P(120, 25)},
 'EQ-EST-05-S1': {'Fuerza de la prensa': P(125.8, 6, origen=E), 'Deformación del bastidor': P(850, 60)},
 'EQ-EST-05-S2': {'Vibración RMS': P(4.2, 0.4, origen=E), 'Aceleración de impacto': P(6, 1),
                  'Factor de cresta': P(3.2, 0.3), 'Temperatura del punto de medición': P(65.0, 2.5, origen=E)},
 'EQ-EST-05-S3': {'Temperatura superficial de embrague/freno': P(85.3, 4, origen=E)},
 'EQ-EST-06-S1': {'Vibración RMS del husillo': P(1.8, 0.2, origen=E), 'Aceleración pico del husillo': P(3, 0.5),
                  'Factor de cresta del husillo': P(3, 0.3), 'Temperatura del punto de medición': P(42.5, 2, origen=E)},
 'EQ-EST-06-S2': {'Corriente del motor/servomotor': P(14.6, 1.2, origen=E)},
 'EQ-EST-06-S3': {'Caudal de refrigerante': P(12.4, 0.6, origen=E), 'Presión de la línea de refrigerante': P(3.5, 0.15, origen=E)},
 'EQ-CAR-07-S1': {'Fuerza de cierre de la pinza': P(3.2, 0.12, origen=E), 'Tiempo de estabilización de la fuerza': P(45, 6)},
 'EQ-CAR-07-S2': {'Caudal de agua de enfriamiento': P(8.5, 0.3, origen=E), 'Temperatura de retorno del agua': P(34.2, 1.5, origen=E)},
 'EQ-CAR-07-S3': {'Corriente de soldadura': P(9.4, 0.4, origen=E), 'Duración del pulso de corriente': P(200, 15)},
 'EQ-CAR-08-S1': {'Fuerza de alimentación del alambre': P(24.5, 1.5, origen=E)},
 'EQ-CAR-08-S2': {'Caudal del gas de protección': P(15.2, 0.5, origen=E), 'Presión del gas de protección': P(4.2, 0.12, origen=E),
                  'Temperatura del gas': P(24, 1.5)},
 'EQ-CAR-08-S3': {'Voltaje del arco': P(24.8, 0.8, origen=E), 'Corriente del arco': P(185, 8, origen=E)},
 'EQ-CAR-09-S1': {'Ángulo de cierre del clamp': P(90.4, 0.4, origen=E)},
 'EQ-CAR-09-S2': {'Presión del actuador del clamp': P(5.4, 0.15, origen=E)},
 'EQ-CAR-09-S3': {'Vibración RMS eje X': P(1.2, 0.15, origen=E), 'Vibración RMS eje Y': P(2.4, 0.25, origen=E),
                  'Vibración RMS eje Z': P(0.8, 0.1, origen=E), 'Aceleración pico': P(3, 0.5), 'Temperatura': P(45, 2)},
 'EQ-CAR-10-S1': {'Vibración RMS eje X': P(2.1, 0.2, origen=E), 'Vibración RMS eje Y': P(1.8, 0.2), 'Vibración RMS eje Z': P(1.5, 0.2),
                  'Aceleración pico': P(4, 0.6), 'Temperatura del punto de medición': P(58.5, 2, origen=E)},
 'EQ-CAR-10-S2': {'Corriente del servomotor': P(18.4, 1.5, origen=E)},
 'EQ-CAR-10-S3': {'Temperatura del motor': P(68.5, 2.5, origen=E), 'Temperatura del reductor': P(52.4, 2, origen=E)},
 'EQ-PIN-11-S1': {'Vibración RMS del atomizador': P(1.4, 0.15, origen=E), 'Aceleración pico del atomizador': P(2.1, 0.3, origen=E)},
 'EQ-PIN-11-S2': {'Presión del circuito de pintura': P(4.2, 0.12, origen=E)},
 'EQ-PIN-11-S3': {'Temperatura del atomizador': P(45.2, 1.5, origen=E)},
 'EQ-PIN-12-S1': {'Presión diferencial del filtro': P(12.4, 0.8, origen=E)},
 'EQ-PIN-12-S2': {'Caudal de extracción de aire': P(1850, 60, origen=E)},
 'EQ-PIN-12-S3': {'Humedad relativa de la cabina': P(52.4, 2.5, 0, 100, E), 'Temperatura de la cabina': P(22.5, 0.6, origen=E)},
 'EQ-PIN-13-S1': {'Temperatura del horno': P(180.5, 2, origen=E)},
 'EQ-PIN-13-S2': {'Presión diferencial de extracción': P(860, 25, origen=E)},
 'EQ-PIN-13-S3': {'Vibración RMS del extractor': P(3.4, 0.3, origen=E), 'Aceleración pico del extractor': P(5, 0.7),
                  'Temperatura superficial del extractor': P(72.0, 2.5, origen=E)},
 'EQ-ENS-14-S1': {'Fuerza Fx': P(3, 1.5, None), 'Fuerza Fy': P(2, 1, None), 'Fuerza Fz': P(10, 2.5, None),
                  'Torque Mx': P(0.4, 0.1, None), 'Torque My': P(0.3, 0.1, None), 'Torque Mz': P(0.2, 0.08, None)},
 'EQ-ENS-14-S2': {**{f'Ángulo articulación J{i}': P(m, s, None) for i, (m, s) in
                     enumerate([(0, 60), (-45, 25), (60, 25), (0, 40), (30, 20), (0, 60)], 1)},
                  **{f'Corriente motor J{i}': P(3.5, 0.5) for i in range(1, 7)}},
 'EQ-ENS-15-S1': {'Torque de apriete': P(9, 0.6), 'Ángulo de apriete': P(420, 30)},
 'EQ-ENS-15-S2': {'Profundidad de inserción': P(19.5, 0.4)},
 'EQ-ENS-16-S1': {'Fuerza instantánea de inserción': P(10, 1.2), 'Fuerza pico de inserción': P(11.5, 1.2)},
 'EQ-ENS-16-S2': {'Posición actual del vástago': P(30, 12), 'Profundidad final de inserción': P(46.5, 0.5)},
 'EQ-MOT-17-S1': {'Desviación en X': P(0, 0.4, None), 'Desviación en Y': P(0, 0.4, None), 'Desviación en Z': P(0, 0.4, None)},
 'EQ-MOT-17-S2': {'Torque real de apriete': P(135, 6), 'Ángulo de apriete alcanzado': P(90, 8)},
 'EQ-MOT-17-S3': {'Fuerza de inserción vertical (eje Z)': P(3.0, 0.5)},
 'EQ-MOT-18-S1': {'Aceleración de vibración del eje': P(1.5, 0.35)},
 'EQ-MOT-18-S2': {'Torque del eje': P(300, 40), 'Velocidad angular del eje': P(3000, 150)},
 'EQ-MOT-18-S3': {'Temperatura de la carcasa': P(90, 5)},
 'EQ-MOT-19-S1': {'Espesor del cordón (cámara)': P(2.2, 0.2)},
 'EQ-MOT-19-S2': {'Espesor del cordón (perfilómetro)': P(2.2, 0.2)},
 'EQ-MOT-19-S3': {'Temperatura máxima': P(60, 4)},
 'EQ-MOT-20-S1': {'Fuerza de tracción/frenado': P(6, 0.8), 'Desbalanceo de frenado': P(6, 3)},
 'EQ-MOT-20-S2': {'Aceleración de vibración del chasis': P(1.2, 0.3)},
}

# Canales discretos (unidad '0/1' o 'cód.'). La probabilidad de lectura "mala" se liga a --prob-anomalia
# (x2) para que las alertas no se disparen a cada rato. Los códigos de 'Estado del sello' y
# 'Código de error' NO vienen definidos en el Excel: son supuestos (1 = OK / 0 = sin error).
BOOL_MALO = ('OUT1', 'OUT2', 'Colisión', 'excesiva', 'Sobrecalentamiento', 'anormal')   # normal = 0, alerta = 1
BOOL_LIBRE = ('Presencia de carga',)    # horquillas: vacías o cargadas son estados normales (sin umbral)


class Canal:
    def __init__(self, meta):
        self.id_sensor = meta['id_sensor']
        self.codigo = meta['codigo']
        self.nombre = meta['nombre_variable']
        self.umin = meta['umbral_min']
        self.umax = meta['umbral_max']
        self.unidad = meta['unidad_medida']
        self.prev = None
        self.discreto = self.unidad in ('0/1', 'cód.')
        if not self.discreto:
            self.perfil = PERFIL[meta['dispositivo']][self.nombre]

    def tiene_umbral(self):
        return self.umin is not None or self.umax is not None

    def _clamp_umbrales(self, x):
        if self.umax is not None:
            x = min(x, self.umax - (abs(self.umax) * 0.01 or 0.01))
        if self.umin is not None:
            x = max(x, self.umin + (abs(self.umin) * 0.01 or 0.01))
        return x

    def siguiente(self, rng, p_anomalia, phi=0.8):
        if self.discreto:
            return self._discreto(rng, p_anomalia)
        p = self.perfil
        if self.prev is None:
            x = rng.gauss(p['media'], p['sd'])
        else:   # AR(1): series suaves, no ruido blanco
            x = p['media'] + phi * (self.prev - p['media']) + rng.gauss(0, p['sd'] * (1 - phi ** 2) ** 0.5)
        if p['lo'] is not None:
            x = max(x, p['lo'])
        if p['hi'] is not None:
            x = min(x, p['hi'])
        x = self._clamp_umbrales(x)
        self.prev = x
        if self.tiene_umbral() and rng.random() < p_anomalia:      # lectura anómala -> dispara el trigger
            lados = [l for l, t in (('max', self.umax), ('min', self.umin)) if t is not None]
            if rng.choice(lados) == 'max':
                x = self.umax + (abs(self.umax) * rng.uniform(0.02, 0.15) or 0.5)
            else:
                x = self.umin - (abs(self.umin) * rng.uniform(0.02, 0.15) or 0.5)
        return round(x, 4)

    def _discreto(self, rng, p_anomalia):
        malo = min(0.5, p_anomalia * 2)
        if self.nombre.startswith('Estatus de apriete'):      # 0x01 OK, 0x02 NOK, 0x03 trasroscado (Excel)
            return 1 if rng.random() >= malo else rng.choices([2, 3], [0.8, 0.2])[0]
        if self.nombre.startswith('Estado del sello'):         # supuesto: 1 OK, 2 NOK
            return 1 if rng.random() >= malo else 2
        if self.nombre.startswith('Código de error'):          # supuesto: 0 = sin error
            return 0 if rng.random() >= malo else rng.randint(1, 9)
        if any(k in self.nombre for k in BOOL_LIBRE):
            return 1 if rng.random() < 0.8 else 0
        if any(k in self.nombre for k in BOOL_MALO):
            return 1 if rng.random() < malo else 0
        return 0 if rng.random() < malo else 1                 # presencias / "correcto" / "aprobada": normal = 1


def cargar_canales(conn):
    sql = """SELECT s.id_sensor, s.codigo, s.nombre_variable, s.umbral_min, s.umbral_max,
                    ts.unidad_medida, d.codigo AS dispositivo
             FROM sensores s
             JOIN tipos_sensor ts ON ts.id_tipo_sensor = s.id_tipo_sensor
             JOIN dispositivos_sensor d ON d.id_dispositivo = s.id_dispositivo
             WHERE s.activo = 1 AND d.activo = 1
             ORDER BY s.id_sensor"""
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        filas = [dict(zip(cols, r)) for r in cur.fetchall()]
    for f in filas:
        for k in ('umbral_min', 'umbral_max'):
            f[k] = float(f[k]) if f[k] is not None else None
    return [Canal(f) for f in filas]


def insertar(conn, filas, lote=5000):
    """Guarda las filas (id_sensor, valor, fecha_hora) en la tabla lecturas, por lotes.

    Cada INSERT dispara el trigger trg_lectura_alerta de la base de datos, que
    revisa los umbrales y crea la alerta si hace falta. Aquí no se crean alertas.
    """
    sql = "INSERT INTO lecturas (id_sensor, valor, fecha_hora) VALUES (%s, %s, %s)"
    with conn.cursor() as cur:
        for i in range(0, len(filas), lote):
            cur.executemany(sql, filas[i:i + lote])
    conn.commit()


def generar_ciclo(conn, canales, rng, prob_anomalia, momento=None):
    """Una "ronda" de medición: UNA lectura nueva por cada canal, todas con la misma hora.

    Devuelve cuántas lecturas se guardaron. Es lo que se repite en tiempo real.
    """
    momento = momento or datetime.now()
    filas = [(c.id_sensor, c.siguiente(rng, prob_anomalia), momento) for c in canales]
    insertar(conn, filas)
    return len(filas)


def generar_historial(conn, canales, rng, horas, intervalo, prob_anomalia,
                      detener=None, progreso=None):
    """Rellena hacia atrás: crea lecturas desde hace `horas` horas hasta este momento.

    conn      : conexión a la base. Si es None no se guarda nada (modo dry-run).
    detener   : objeto con is_set() (como threading.Event); si se activa, se corta.
    progreso  : función opcional progreso(lecturas_guardadas) para informar avance.
    Devuelve el total de lecturas generadas.
    """
    pasos = int(horas * 3600 / intervalo)
    fin = datetime.now().replace(microsecond=0)
    inicio = fin - timedelta(seconds=pasos * intervalo)
    pendientes, total = [], 0
    for n in range(pasos + 1):
        if detener is not None and detener.is_set():
            break
        momento = inicio + timedelta(seconds=n * intervalo)
        for c in canales:
            pendientes.append((c.id_sensor, c.siguiente(rng, prob_anomalia), momento))
        if len(pendientes) >= 5000:            # guardamos de a poco para no llenar la memoria
            total += len(pendientes)
            if conn is not None:
                insertar(conn, pendientes)
            pendientes = []
            if progreso:
                progreso(total)
    if pendientes:
        total += len(pendientes)
        if conn is not None:
            insertar(conn, pendientes)
        if progreso:
            progreso(total)
    return total


def main():
    """Entrada por línea de comandos (ver la cabecera del archivo)."""
    ap = argparse.ArgumentParser(description='Genera lecturas simuladas para novadb')
    ap.add_argument('--host', default='localhost')
    ap.add_argument('--port', type=int, default=3306)
    ap.add_argument('--user', default='root')
    ap.add_argument('--password', default='')
    ap.add_argument('--db', default='novadb')
    ap.add_argument('--horas', type=float, default=24, help='horas de histórico a generar (default 24)')
    ap.add_argument('--intervalo', type=float, default=60, help='segundos entre lecturas (default 60)')
    ap.add_argument('--prob-anomalia', type=float, default=0.002, help='prob. de lectura fuera de umbral por canal con umbral (default 0.002)')
    ap.add_argument('--live', action='store_true', help='tiempo real: inserta una lectura por canal cada --intervalo')
    ap.add_argument('--limpiar', action='store_true', help='borra alertas y lecturas antes de generar')
    ap.add_argument('--dry-run', action='store_true', help='no inserta nada, solo muestra un resumen')
    ap.add_argument('--semilla', type=int, default=None)
    a = ap.parse_args()

    import pymysql
    conn = pymysql.connect(host=a.host, port=a.port, user=a.user, password=a.password, database=a.db,
                           charset='utf8mb4', autocommit=False)
    rng = random.Random(a.semilla)
    canales = cargar_canales(conn)
    con_umbral = sum(c.tiene_umbral() for c in canales)
    print(f'{len(canales)} canales activos ({con_umbral} con umbral -> pueden generar alertas)')
    if not canales:
        raise SystemExit('No hay canales: ejecuta primero los scripts 01 a 05.')
    if con_umbral == 0:
        print('Aviso: ningún canal tiene umbral; no se generarán alertas (ver 06_umbrales_todos.sql).')

    if a.limpiar and not a.dry_run:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM alertas')
            cur.execute('DELETE FROM lecturas')
            cur.execute('ALTER TABLE alertas AUTO_INCREMENT = 1')
            cur.execute('ALTER TABLE lecturas AUTO_INCREMENT = 1')
        conn.commit()
        print('Lecturas y alertas borradas.')

    if a.live:
        print(f'Tiempo real cada {a.intervalo:g} s. Ctrl+C para detener.')
        try:
            while True:
                ahora = datetime.now()
                n = len(canales) if a.dry_run else generar_ciclo(conn, canales, rng, a.prob_anomalia, ahora)
                print(ahora.strftime('%H:%M:%S'), f'{n} lecturas')
                time.sleep(a.intervalo)
        except KeyboardInterrupt:
            print('Detenido.')
        return

    total = generar_historial(None if a.dry_run else conn, canales, rng, a.horas, a.intervalo, a.prob_anomalia)
    print(f'{total} lecturas generadas (hasta ahora mismo)')
    if a.dry_run:
        print('Dry-run: no se insertó nada.')
        return
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM alertas')
        print('Insertado. Alertas generadas por el trigger:', cur.fetchone()[0])


if __name__ == '__main__':
    main()
