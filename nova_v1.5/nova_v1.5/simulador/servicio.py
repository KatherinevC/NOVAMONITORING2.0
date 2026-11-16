"""
simulador/servicio.py
---------------------
Es el "interruptor" del simulador. Permite encender y apagar el generador de
lecturas desde el dashboard, sin abrir una terminal.

¿Cómo funciona?
  - Al pulsar "Iniciar" se arranca un HILO de fondo (un trabajo paralelo dentro de
    NOVA) que, cada pocos segundos, inserta una lectura por canal en la tabla
    `lecturas`. Eso lo hace simulador/generar_lecturas.py.
  - Mientras tanto la página sigue funcionando normal y va leyendo esos datos.
  - Al pulsar "Detener" el hilo termina limpiamente.

Cosas a tener en cuenta:
  - Solo puede haber UN simulador activo a la vez (por eso el candado `_candado`).
  - El hilo es "daemon": si apagas NOVA (o Flask se reinicia por un cambio de
    código en modo debug) el simulador se apaga solo.
  - Aquí no se decide quién puede usarlo; eso lo hace rutas/api.py con los permisos.
"""
import random
import threading
from datetime import datetime

from sqlalchemy import text

from conexion import app, db
from simulador import generar_lecturas as gen

# --- Estado compartido entre el hilo y las peticiones web ----------------------
_candado = threading.Lock()      # evita que dos peticiones arranquen dos simuladores
_hilo = None                     # el hilo que está trabajando (o None)
_parar = threading.Event()       # bandera "ya detente": el hilo la revisa en cada vuelta
_estado = {}                     # lo que el panel del dashboard muestra

INTERVALO_MIN, INTERVALO_MAX = 1, 60            # segundos entre rondas
HISTORIAL_PERMITIDO = (0, 0.5, 1, 3)            # horas de historial que se pueden precargar
INTERVALO_HISTORIAL = 30                        # segundos entre lecturas del historial


def _estado_inicial():
    return {'fase': 'detenido', 'intervalo': None, 'ciclos': 0, 'lecturas': 0,
            'canales': 0, 'con_umbral': 0, 'iniciado_en': None, 'ultimo_ciclo': None,
            'error': None}


_estado.update(_estado_inicial())


def estado():
    """Foto actual del simulador (la usa el panel del dashboard cada pocos segundos)."""
    with _candado:
        copia = dict(_estado)
        copia['corriendo'] = bool(_hilo and _hilo.is_alive())
        if not copia['corriendo'] and copia['fase'] in ('cargando_canales', 'historial', 'tiempo_real'):
            copia['fase'] = 'detenido'
        return copia


def iniciar(intervalo=5, historial_horas=0, prob_anomalia=0.002):
    """Arranca el simulador. Devuelve (ok, mensaje)."""
    global _hilo
    # Validamos lo que llega de la web: nunca confiar en los datos del navegador
    try:
        intervalo = float(intervalo)
        historial_horas = float(historial_horas)
    except (TypeError, ValueError):
        return False, 'Los valores recibidos no son números.'
    if not INTERVALO_MIN <= intervalo <= INTERVALO_MAX:
        return False, f'El intervalo debe estar entre {INTERVALO_MIN} y {INTERVALO_MAX} segundos.'
    if historial_horas not in HISTORIAL_PERMITIDO:
        return False, 'Esa cantidad de historial no está permitida.'

    with _candado:
        if _hilo and _hilo.is_alive():
            return False, 'El simulador ya está en marcha.'
        _parar.clear()
        _estado.clear()
        _estado.update(_estado_inicial())
        _estado.update(fase='cargando_canales', intervalo=intervalo,
                       iniciado_en=datetime.now().isoformat(timespec='seconds'))
        _hilo = threading.Thread(target=_trabajar, name='simulador-nova', daemon=True,
                                 args=(intervalo, historial_horas, prob_anomalia))
        _hilo.start()
    return True, 'Simulador iniciado.'


def detener():
    """Pide al hilo que termine y espera un momento a que lo haga. Devuelve (ok, mensaje)."""
    hilo = _hilo
    if not (hilo and hilo.is_alive()):
        return False, 'El simulador no estaba en marcha.'
    _parar.set()
    hilo.join(timeout=10)
    return True, 'Simulador detenido.'


def limpiar_datos():
    """Borra TODAS las lecturas y alertas (para empezar una prueba desde cero).

    Solo se permite con el simulador apagado, para no borrar mientras se inserta.
    """
    if _hilo and _hilo.is_alive():
        return False, 'Detén el simulador antes de borrar los datos.'
    # Primero alertas, porque alertas.id_lectura apunta a lecturas
    db.session.execute(text('DELETE FROM alertas'))
    db.session.execute(text('DELETE FROM lecturas'))
    db.session.commit()
    db.session.execute(text('ALTER TABLE alertas AUTO_INCREMENT = 1'))
    db.session.execute(text('ALTER TABLE lecturas AUTO_INCREMENT = 1'))
    db.session.commit()
    return True, 'Lecturas y alertas borradas.'


def _anotar(**cambios):
    """Actualiza el estado visible de forma segura (el hilo y la web lo tocan a la vez)."""
    with _candado:
        _estado.update(cambios)


def _trabajar(intervalo, historial_horas, prob_anomalia):
    """Lo que hace el hilo de fondo, de principio a fin."""
    with app.app_context():                    # el hilo necesita su propio "contexto" de Flask
        conn = None
        try:
            # Conexión directa al driver (pymysql) para reutilizar el código del generador
            conn = db.engine.raw_connection()
            canales = gen.cargar_canales(conn)
            if not canales:
                _anotar(error='No hay canales: importa los scripts SQL 01 a 05.')
                return
            rng = random.Random()
            _anotar(canales=len(canales), con_umbral=sum(c.tiene_umbral() for c in canales))

            # Fase 1 (opcional): precargar historial para que las gráficas no empiecen vacías
            if historial_horas:
                _anotar(fase='historial')
                total = gen.generar_historial(
                    conn, canales, rng, historial_horas, INTERVALO_HISTORIAL, prob_anomalia,
                    detener=_parar, progreso=lambda n: _anotar(lecturas=n))
                _anotar(lecturas=total)

            # Fase 2: tiempo real. Una ronda cada `intervalo` segundos hasta que pidan parar.
            _anotar(fase='tiempo_real')
            while not _parar.is_set():
                n = gen.generar_ciclo(conn, canales, rng, prob_anomalia)
                with _candado:
                    _estado['ciclos'] += 1
                    _estado['lecturas'] += n
                    _estado['ultimo_ciclo'] = datetime.now().isoformat(timespec='seconds')
                _parar.wait(intervalo)          # duerme, pero se despierta al instante si piden parar
        except Exception as e:                  # cualquier fallo (BD apagada, etc.) queda visible en el panel
            _anotar(error=f'{type(e).__name__}: {e}')
        finally:
            if conn is not None:
                conn.close()                    # devuelve la conexión al pool
            _anotar(fase='detenido')
