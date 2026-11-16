/*
  dashboard.js
  ------------
  Mantiene vivo el dashboard sin recargar la página. Cada pocos segundos le pregunta al
  servidor cómo van las cosas y reescribe solo lo que cambió:
    - /api/dashboard     -> tarjetas, globito de alertas, estado de planta y últimas lecturas
    - /simulador/estado  -> contadores y lista de verificación del simulador (solo administrador)

  Los botones del simulador son formularios normales (POST con token CSRF): este archivo no los
  reemplaza, solo pide confirmación antes de borrar y muestra el avance.

  Orden del archivo:  1. Utilidades · 2. Tarjetas y lecturas · 3. Simulador · 4. Arranque
*/
(() => {
  'use strict';

  const REFRESCO_MS = 5000;      // cada cuánto se actualiza el dashboard
  const REFRESCO_SIM_MS = 2000;  // el simulador se actualiza más seguido

  const $ = (id) => document.getElementById(id);
  const dosDigitos = (n) => String(n ?? 0).padStart(2, '0');
  // Muestra un valor según su tipo: Sí/No para 0/1, entero para códigos, decimales para el resto
  function formatearValor(valor, unidad) {
    if (unidad === '0/1') return valor ? 'Sí' : 'No';
    if (unidad === 'cód.') return String(Math.round(valor));
    return `${valor.toFixed(2)} ${unidad}`;
  }
  const soloHora = (fecha) => (fecha || '').replace(' ', 'T').slice(11, 19);   // "2026-10-20 14:03:05" -> "14:03:05"

  // Crea un elemento con el texto como TEXTO (nunca como HTML): un nombre raro guardado en la
  // base de datos no puede inyectar código en la página.
  function crear(etiqueta, clase, texto) {
    const el = document.createElement(etiqueta);
    if (clase) el.className = clase;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  async function pedir(url) {
    const resp = await fetch(url, { credentials: 'same-origin' });
    if (resp.status === 401) { window.location.href = '/login'; throw new Error('Sesión vencida'); }
    const datos = await resp.json().catch(() => ({}));
    if (!resp.ok) { const e = new Error(datos.error || `Error ${resp.status}`); e.estado = resp.status; throw e; }
    return datos;
  }

  // ===========================================================================
  // 2. Tarjetas, estado de planta y últimas lecturas
  // ===========================================================================
  function pintarResumen(r) {
    $('valMaquinas').textContent = dosDigitos(r.maquinas_total);
    $('valNormal').textContent = dosDigitos(r.operativas);
    $('valSeguimiento').textContent = dosDigitos(r.en_seguimiento);
    $('valAnomalias').textContent = dosDigitos(r.alertas_pendientes);
    const globito = $('badgeAlertas');
    if (globito) globito.textContent = dosDigitos(r.alertas_pendientes);

    // Estado de planta: ¿llegan lecturas? ¿hay alertas sin atender?
    const estado = $('estadoPlanta');
    estado.className = 'status-val';
    if (!r.lecturas_ultimo_minuto) { estado.textContent = 'Sin datos recientes'; estado.classList.add('estado-apagado'); }
    else if (r.alertas_pendientes > 0) { estado.textContent = 'Con alertas'; estado.classList.add('estado-aviso'); }
    else { estado.textContent = 'Operativa'; }
  }

  function pintarUltimas(lecturas) {
    const cuerpo = $('tbodyUltimas');
    if (!cuerpo) return;                       // este rol no ve el panel
    cuerpo.replaceChildren();
    if (!lecturas.length) {
      const fila = crear('tr'); const celda = crear('td', 'empty-state', 'Todavía no hay lecturas.');
      celda.colSpan = 5; fila.append(celda); cuerpo.append(fila); return;
    }
    for (const l of lecturas) {
      const fila = crear('tr');
      fila.append(crear('td', '', soloHora(l.fecha_hora)), crear('td', '', l.maquina), crear('td', '', l.sensor),
                  crear('td', '', l.variable), crear('td', 'num', formatearValor(l.valor, l.unidad)));
      cuerpo.append(fila);
    }
  }

  async function refrescarDashboard() {
    const datos = await pedir('/api/dashboard');
    pintarResumen(datos.resumen);
    pintarUltimas(datos.ultimas);
    return datos;
  }

  // ===========================================================================
  // 3. Simulador de lecturas (solo existe en la página si el rol es administrador)
  // ===========================================================================
  const TEXTO_FASE = {
    detenido: ['Detenido', ''],
    cargando_canales: ['Preparando…', 'trabajando'],
    historial: ['Cargando historial…', 'trabajando'],
    tiempo_real: ['En tiempo real', 'activo'],
  };

  // Marca un punto de la lista de verificación: ok (verde), fallo (rojo) o pendiente (gris)
  function marcar(id, estado) {
    const li = $(id); if (!li) return;
    li.className = estado === 'ok' ? 'ok' : estado === 'fallo' ? 'fallo' : '';
    li.querySelector('.chk-icono').textContent = estado === 'ok' ? '✓' : estado === 'fallo' ? '✕' : '○';
  }

  function pintarSimulador(e, resumen) {
    const [texto, clase] = TEXTO_FASE[e.fase] || TEXTO_FASE.detenido;
    const pill = $('simEstado'); pill.textContent = texto; pill.className = `pill ${clase}`.trim();
    $('simCanales').textContent = e.canales || '--';
    $('simUmbral').textContent = e.canales ? e.con_umbral : '--';
    $('simCiclos').textContent = e.ciclos;
    $('simLecturas').textContent = Number(e.lecturas).toLocaleString('es-CO');
    $('simUltima').textContent = e.ultimo_ciclo ? soloHora(e.ultimo_ciclo) : '--';
    $('btnIniciar').disabled = e.corriendo;
    $('simIntervalo').disabled = $('simHistorial').disabled = e.corriendo;
    $('btnDetener').disabled = !e.corriendo;
    $('btnLimpiar').disabled = e.corriendo;

    // Lista de verificación (el recorrido completo: generador -> base de datos -> trigger -> pantalla)
    marcar('chkBd', 'ok');                                          // si llegó esta respuesta, la BD responde
    marcar('chkCanales', e.canales > 0 ? 'ok' : (e.error ? 'fallo' : ''));
    marcar('chkRondas', e.error ? 'fallo' : (e.corriendo && (e.ciclos > 0 || e.fase === 'historial') ? 'ok' : ''));
    marcar('chkLecturas', resumen && resumen.lecturas_ultimo_minuto > 0 ? 'ok' : '');
    marcar('chkAlertas', resumen && resumen.alertas_pendientes > 0 ? 'ok' : '');

    const mensaje = $('simMensaje');
    if (e.error) { mensaje.hidden = false; mensaje.textContent = `El simulador se detuvo por un error: ${e.error}`; }
    else if (e.corriendo && e.canales && e.con_umbral === 0) {
      mensaje.hidden = false; mensaje.textContent = 'Ningún canal tiene umbral, así que no se generarán alertas. Importa 06_umbrales_todos.sql.';
    } else { mensaje.hidden = true; }
  }

  let ultimoResumen = null;
  async function refrescarSimulador() {
    pintarSimulador(await pedir('/simulador/estado'), ultimoResumen);
  }

  // Pide confirmación antes de enviar los formularios marcados con data-confirmar (borrar datos)
  function conectarConfirmaciones() {
    document.querySelectorAll('form[data-confirmar]').forEach((f) => {
      f.addEventListener('submit', (ev) => { if (!confirm(f.dataset.confirmar)) ev.preventDefault(); });
    });
  }

  // ===========================================================================
  // 4. Arranque
  // ===========================================================================
  async function intentar(tarea) {
    try { await tarea(); } catch (e) { console.warn('NOVA dashboard:', e.message); }
  }

  async function iniciar() {
    conectarConfirmaciones();
    const ciclo = async () => {
      await intentar(async () => { ultimoResumen = (await refrescarDashboard()).resumen; });
      if ($('panelSimulador')) await intentar(refrescarSimulador);
    };
    await ciclo();
    // Se repite solo; con la pestaña oculta no se gastan recursos pidiendo datos
    setInterval(() => { if (!document.hidden) ciclo(); }, REFRESCO_MS);
    if ($('panelSimulador')) {
      setInterval(() => { if (!document.hidden) intentar(refrescarSimulador); }, REFRESCO_SIM_MS);
    }
    document.addEventListener('visibilitychange', () => { if (!document.hidden) ciclo(); });
  }

  document.addEventListener('DOMContentLoaded', iniciar);
})();
