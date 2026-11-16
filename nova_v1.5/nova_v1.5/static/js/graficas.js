/*
  graficas.js
  -----------
  Dibuja las gráficas del comportamiento de los sensores en el dashboard.

  No usa librerías externas: las gráficas se construyen con SVG, así funcionan aunque el
  computador no tenga internet (XAMPP local). Los datos llegan de /api/graficas/... (rutas/graficas.py)
  y se refrescan solos cada pocos segundos, de modo que al encender el simulador se ve la
  gráfica "moverse" en vivo.

  Gráficas:
    1. Tendencia de un sensor (línea, con umbrales, puntos fuera de rango y detalle al pasar el mouse)
    2. Mini-gráficas de todos los sensores de la máquina elegida
    3. Estado actual de los sensores (dona)
    4. Alertas pendientes por área (barras)

  Orden del archivo:  1. Utilidades · 2. Dibujo (línea, dona, barras) · 3. Paneles · 4. Arranque
*/
(() => {
  'use strict';

  const panel = document.getElementById('panelGraficas');
  if (!panel) return;                            // este rol no tiene permiso de ver Monitoreo

  const REFRESCO_MS = 4000;                      // cada cuánto se redibujan las gráficas
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);

  // ===========================================================================
  // 1. Utilidades
  // ===========================================================================
  // Crea un elemento SVG con sus atributos. El texto se inserta como TEXTO (nunca como HTML).
  function svg(etiqueta, atributos = {}, texto) {
    const el = document.createElementNS(NS, etiqueta);
    for (const [k, v] of Object.entries(atributos)) el.setAttribute(k, v);
    if (texto !== undefined) el.textContent = texto;
    return el;
  }
  function html(etiqueta, clase, texto) {
    const el = document.createElement(etiqueta);
    if (clase) el.className = clase;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  // "2026-10-23 11:29:55.863" -> milisegundos. Se ignoran las fracciones: con segundos alcanza.
  const aMs = (texto) => new Date(texto.replace(' ', 'T').slice(0, 19)).getTime();
  const dos = (n) => String(n).padStart(2, '0');
  function hora(ms, conSegundos = true) {
    const d = new Date(ms);
    return `${dos(d.getHours())}:${dos(d.getMinutes())}` + (conSegundos ? `:${dos(d.getSeconds())}` : '');
  }

  // Muestra un valor según su tipo: Sí/No para 0/1, entero para códigos, decimales para el resto
  function formatear(valor, unidad) {
    if (valor === null || valor === undefined) return '—';
    if (unidad === '0/1') return valor ? 'Sí' : 'No';
    if (unidad === 'cód.') return String(Math.round(valor));
    const num = Number(valor);
    return num.toLocaleString('es-CO', { maximumFractionDigits: Math.abs(num) >= 100 ? 1 : 2 });
  }

  // Estado de un valor frente a los umbrales (misma regla que el trigger de la base de datos)
  function estadoDe(valor, minimo, maximo) {
    if (maximo !== null && valor > maximo) return 'alto';
    if (minimo !== null && valor < minimo) return 'bajo';
    return 'normal';
  }

  // Marcas "bonitas" para el eje Y (1, 2, 5, 10, 20, 50...)
  function marcas(min, max, cantidad) {
    const paso0 = (max - min) / Math.max(1, cantidad - 1);
    const mag = Math.pow(10, Math.floor(Math.log10(paso0)));
    const norm = paso0 / mag;
    const paso = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const lista = [];
    for (let v = Math.ceil(min / paso) * paso; v <= max + paso * 1e-6; v += paso) lista.push(Math.round(v / paso) * paso);
    return lista;
  }

  async function pedir(url) {
    const resp = await fetch(url, { credentials: 'same-origin' });
    if (resp.status === 401) { window.location.href = '/login'; throw new Error('Sesión vencida'); }
    const datos = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(datos.error || `Error ${resp.status}`);
    return datos;
  }

  // ===========================================================================
  // 2. Dibujo
  // ===========================================================================
  let contadorId = 0;   // para darle un id único a cada degradado SVG

  /**
   * Gráfica de línea de UN sensor.
   *   cont : elemento HTML donde se dibuja
   *   d    : { puntos: [[fecha, valor], ...], unidad, umbral_min, umbral_max }
   *   op   : { ancho, alto, mini }   (mini = versión pequeña, sin ejes ni detalle)
   */
  function dibujarLinea(cont, d, op) {
    cont.replaceChildren();
    const pts = d.puntos.map(([f, v]) => ({ t: aMs(f), v }));
    if (!pts.length) { cont.append(html('p', 'gr-vacio', 'Sin lecturas en esta ventana')); return; }

    const W = op.ancho, H = op.alto, mini = op.mini;
    const m = mini ? { l: 4, r: 4, t: 6, b: 6 } : { l: 58, r: 16, t: 14, b: 28 };
    const esBool = d.unidad === '0/1';
    const minU = d.umbral_min, maxU = d.umbral_max;

    // Dominio del eje Y: incluye los umbrales para ver qué tan cerca está el sensor del límite
    let lo = Math.min(...pts.map((p) => p.v)), hi = Math.max(...pts.map((p) => p.v));
    if (minU !== null) lo = Math.min(lo, minU);
    if (maxU !== null) hi = Math.max(hi, maxU);
    if (esBool) { lo = 0; hi = 1; }
    if (lo === hi) { lo -= 1; hi += 1; }
    if (!esBool) { const margen = (hi - lo) * 0.08; lo -= margen; hi += margen; }

    const t0 = pts[0].t; let t1 = pts[pts.length - 1].t; if (t1 === t0) t1 = t0 + 1000;
    const x = (t) => m.l + ((t - t0) / (t1 - t0)) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);

    const lienzo = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'gr-svg', role: 'img' });
    const idGrad = `grad${++contadorId}`;
    const defs = svg('defs');
    const grad = svg('linearGradient', { id: idGrad, x1: 0, y1: 0, x2: 0, y2: 1 });
    grad.append(svg('stop', { offset: '0%', 'stop-color': '#818cf8', 'stop-opacity': 0.35 }),
                svg('stop', { offset: '100%', 'stop-color': '#818cf8', 'stop-opacity': 0 }));
    defs.append(grad); lienzo.append(defs);

    // Cuadrícula y etiquetas del eje Y / eje X (solo en la versión grande)
    if (!mini) {
      const ys = esBool ? [0, 1] : marcas(lo, hi, 5);
      for (const v of ys) {
        lienzo.append(svg('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: 'gr-grid' }));
        lienzo.append(svg('text', { x: m.l - 8, y: y(v) + 4, class: 'gr-eje', 'text-anchor': 'end' },
                          esBool ? (v ? 'Sí' : 'No') : formatear(v, d.unidad)));
      }
      const conSeg = (t1 - t0) < 2 * 3600 * 1000;
      for (let i = 0; i < 5; i++) {
        const t = t0 + ((t1 - t0) * i) / 4;
        lienzo.append(svg('text', { x: x(t), y: H - 8, class: 'gr-eje', 'text-anchor': i === 0 ? 'start' : i === 4 ? 'end' : 'middle' }, hora(t, conSeg)));
      }
    }

    // Umbrales (líneas punteadas)
    if (maxU !== null) {
      lienzo.append(svg('line', { x1: m.l, x2: W - m.r, y1: y(maxU), y2: y(maxU), class: 'gr-umbral gr-umbral-max' }));
      if (!mini) lienzo.append(svg('text', { x: W - m.r - 4, y: y(maxU) - 5, class: 'gr-etiqueta gr-etiqueta-max', 'text-anchor': 'end' }, esBool ? 'alerta si = Sí' : `máx ${formatear(maxU, d.unidad)}`));
    }
    if (minU !== null) {
      lienzo.append(svg('line', { x1: m.l, x2: W - m.r, y1: y(minU), y2: y(minU), class: 'gr-umbral gr-umbral-min' }));
      if (!mini) lienzo.append(svg('text', { x: W - m.r - 4, y: y(minU) + 13, class: 'gr-etiqueta gr-etiqueta-min', 'text-anchor': 'end' }, esBool ? 'alerta si = No' : `mín ${formatear(minU, d.unidad)}`));
    }

    // La línea: en escalón para los valores 0/1 y los códigos; recta para los analógicos
    const escalon = esBool || d.unidad === 'cód.';
    let trazo = `M ${x(pts[0].t)} ${y(pts[0].v)}`;
    for (let i = 1; i < pts.length; i++) trazo += escalon ? ` H ${x(pts[i].t)} V ${y(pts[i].v)}` : ` L ${x(pts[i].t)} ${y(pts[i].v)}`;
    const base = H - m.b;
    lienzo.append(svg('path', { d: `${trazo} L ${x(pts[pts.length - 1].t)} ${base} L ${x(pts[0].t)} ${base} Z`, fill: `url(#${idGrad})`, stroke: 'none' }));
    lienzo.append(svg('path', { d: trazo, class: 'gr-linea', fill: 'none' }));

    // Puntos rojos = lecturas fuera de rango; punto final = lectura más reciente
    for (const p of pts) {
      if (estadoDe(p.v, minU, maxU) !== 'normal') lienzo.append(svg('circle', { cx: x(p.t), cy: y(p.v), r: mini ? 2.2 : 4, class: 'gr-punto-fuera' }));
    }
    const ult = pts[pts.length - 1];
    lienzo.append(svg('circle', { cx: x(ult.t), cy: y(ult.v), r: mini ? 2.5 : 4, class: 'gr-punto-ultimo' }));
    cont.append(lienzo);

    // Detalle al pasar el mouse (solo en la versión grande)
    if (!mini) {
      const guia = svg('line', { y1: m.t, y2: H - m.b, class: 'gr-guia', visibility: 'hidden' });
      const marca = svg('circle', { r: 5, class: 'gr-punto-ultimo', visibility: 'hidden' });
      const cuadro = html('div', 'gr-tip'); cuadro.hidden = true;
      const capa = svg('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' });
      lienzo.append(guia, marca, capa); cont.append(cuadro);

      capa.addEventListener('mousemove', (ev) => {
        const caja = lienzo.getBoundingClientRect();
        const px = ((ev.clientX - caja.left) / caja.width) * W;
        let mejor = pts[0];
        for (const p of pts) if (Math.abs(x(p.t) - px) < Math.abs(x(mejor.t) - px)) mejor = p;   // el punto más cercano
        guia.setAttribute('x1', x(mejor.t)); guia.setAttribute('x2', x(mejor.t)); guia.setAttribute('visibility', 'visible');
        marca.setAttribute('cx', x(mejor.t)); marca.setAttribute('cy', y(mejor.v)); marca.setAttribute('visibility', 'visible');
        const estado = estadoDe(mejor.v, minU, maxU);
        cuadro.replaceChildren(html('strong', '', `${formatear(mejor.v, d.unidad)} ${esBool || d.unidad === 'cód.' ? '' : d.unidad}`.trim()),
                               html('span', '', hora(mejor.t)),
                               html('span', `gr-tip-${estado}`, estado === 'alto' ? 'Sobre el máximo' : estado === 'bajo' ? 'Bajo el mínimo' : 'Normal'));
        cuadro.hidden = false;
        cuadro.style.left = `${Math.min(caja.width - 150, Math.max(0, (x(mejor.t) / W) * caja.width + 12))}px`;
        cuadro.style.top = `${(y(mejor.v) / H) * caja.height - 56}px`;
      });
      capa.addEventListener('mouseenter', () => { cont.dataset.hover = '1'; });   // mientras miras un dato no se redibuja
      capa.addEventListener('mouseleave', () => { delete cont.dataset.hover; guia.setAttribute('visibility', 'hidden'); marca.setAttribute('visibility', 'hidden'); cuadro.hidden = true; });
    }
  }

  const COLORES = { normal: '#22c55e', sobre_maximo: '#f87171', bajo_minimo: '#facc15', sin_lectura: '#475569' };
  const NOMBRES = { normal: 'Normal', sobre_maximo: 'Sobre el máximo', bajo_minimo: 'Bajo el mínimo', sin_lectura: 'Sin lectura' };

  /** Dona: cuántos sensores hay en cada estado. */
  function dibujarDona(cont, estados) {
    cont.replaceChildren();
    const total = Object.values(estados).reduce((a, b) => a + b, 0);
    if (!total) { cont.append(html('p', 'gr-vacio', 'No hay sensores activos.')); return; }
    const R = 62, C = 2 * Math.PI * R;
    const lienzo = svg('svg', { viewBox: '0 0 180 180', class: 'gr-svg gr-dona-svg', role: 'img' });
    lienzo.append(svg('circle', { cx: 90, cy: 90, r: R, fill: 'none', stroke: '#161b2c', 'stroke-width': 22 }));
    let acumulado = 0;
    for (const clave of Object.keys(COLORES)) {
      const n = estados[clave] || 0; if (!n) continue;
      const largo = (n / total) * C;
      lienzo.append(svg('circle', { cx: 90, cy: 90, r: R, fill: 'none', stroke: COLORES[clave], 'stroke-width': 22,
                                    'stroke-dasharray': `${largo} ${C - largo}`, 'stroke-dashoffset': -acumulado, transform: 'rotate(-90 90 90)' }));
      acumulado += largo;
    }
    lienzo.append(svg('text', { x: 90, y: 92, class: 'gr-dona-num', 'text-anchor': 'middle' }, String(total)));
    lienzo.append(svg('text', { x: 90, y: 110, class: 'gr-eje', 'text-anchor': 'middle' }, 'sensores'));
    const leyenda = html('ul', 'gr-leyenda');
    for (const clave of Object.keys(COLORES)) {
      const li = html('li'); const punto = html('i'); punto.style.background = COLORES[clave];
      li.append(punto, html('span', '', NOMBRES[clave]), html('strong', '', String(estados[clave] || 0)));
      leyenda.append(li);
    }
    cont.append(lienzo, leyenda);
  }

  /** Barras horizontales: alertas pendientes por área. */
  function dibujarBarras(cont, items) {
    cont.replaceChildren();
    if (!items.length) { cont.append(html('p', 'gr-vacio', 'No hay alertas pendientes. ✔')); return; }
    const mayor = Math.max(...items.map((i) => i.total));
    for (const it of items) {
      const fila = html('div', 'gr-barra-fila');
      const barra = html('div', 'gr-barra'); const relleno = html('div', 'gr-barra-relleno');
      relleno.style.width = `${Math.max(4, (it.total / mayor) * 100)}%`; barra.append(relleno);
      fila.append(html('span', 'gr-barra-nombre', it.area), barra, html('strong', '', String(it.total)));
      cont.append(fila);
    }
  }

  // ===========================================================================
  // 3. Paneles (piden los datos y dibujan)
  // ===========================================================================
  let catalogo = null;
  const sel = { maquina: $('grMaquina'), variable: $('grVariable'), ventana: $('grVentana') };

  function maquinaElegida() {
    const id = Number(sel.maquina.value);
    for (const a of catalogo.areas) { const m = a.maquinas.find((x) => x.id_maquina === id); if (m) return m; }
    return null;
  }
  function llenarVariables(conservar) {
    sel.variable.replaceChildren();
    const m = maquinaElegida(); if (!m) return;
    for (const s of m.sensores) sel.variable.append(new Option(`${s.variable} (${s.unidad})`, s.id_sensor));
    if (conservar && [...sel.variable.options].some((o) => o.value === String(conservar))) sel.variable.value = conservar;
  }

  function estadoEnVivo(atraso) {
    const pill = $('grEstado');
    if (atraso === null || atraso === undefined) { pill.textContent = 'Sin lecturas'; pill.className = 'pill'; }
    else if (atraso <= 15) { pill.textContent = 'En vivo'; pill.className = 'pill activo'; }
    else { pill.textContent = `Último dato hace ${atraso < 120 ? atraso + ' s' : Math.round(atraso / 60) + ' min'}`; pill.className = 'pill'; }
  }

  async function refrescarSensor() {
    const id = sel.variable.value; if (!id) return;
    const caja = $('grLinea'); if (caja.dataset.hover) return;           // no redibujar mientras se mira un dato
    const d = await pedir(`/api/graficas/sensor/${id}?minutos=${sel.ventana.value}`);
    estadoEnVivo(d.segundos_desde_ultimo);
    $('grTitulo').textContent = `${d.maquina} · ${d.variable} (${d.unidad})`;
    $('grUmbrales').textContent = d.unidad === '0/1'
      ? `Alerta cuando el valor es ${d.umbral_max !== null ? 'Sí' : d.umbral_min !== null ? 'No' : '—'}`
      : `Umbral mín: ${formatear(d.umbral_min, d.unidad)}  ·  máx: ${formatear(d.umbral_max, d.unidad)}`;
    dibujarLinea(caja, d, { ancho: 900, alto: 320, mini: false });

    // Estadísticas de toda la ventana: sirven para comprobar la simulación
    const e = d.estadisticas, stats = $('grStats'); stats.replaceChildren();
    const datos = [['Último', formatear(e.ultimo, d.unidad)], ['Mínimo', formatear(e.min, d.unidad)], ['Máximo', formatear(e.max, d.unidad)],
                   ['Promedio', formatear(e.promedio, d.unidad)], ['Lecturas', String(e.n)], ['Fuera de rango', String(e.fuera)]];
    for (const [nombre, valor] of datos) {
      const caja2 = html('div', nombre === 'Fuera de rango' && e.fuera > 0 ? 'gr-stat gr-stat-alerta' : 'gr-stat');
      caja2.append(html('span', '', nombre), html('strong', '', valor)); stats.append(caja2);
    }
  }

  async function refrescarMini() {
    const m = maquinaElegida(); if (!m) return;
    const d = await pedir(`/api/graficas/maquina/${m.id_maquina}?minutos=${sel.ventana.value}`);
    estadoEnVivo(d.segundos_desde_ultimo);
    const rejilla = $('grMini'); rejilla.replaceChildren();
    for (const s of d.sensores) {
      const e = s.estadisticas;
      const estado = e.n ? estadoDe(e.ultimo, s.umbral_min, s.umbral_max) : 'sin';
      const tarjeta = html('button', `gr-mini gr-mini-${estado}${String(s.id_sensor) === sel.variable.value ? ' gr-mini-activa' : ''}`);
      tarjeta.type = 'button';
      const cab = html('div', 'gr-mini-cab');
      cab.append(html('span', 'gr-mini-nombre', s.variable), html('strong', '', e.n ? `${formatear(e.ultimo, s.unidad)} ${s.unidad === '0/1' || s.unidad === 'cód.' ? '' : s.unidad}`.trim() : '—'));
      const dibujo = html('div', 'gr-mini-dibujo');
      tarjeta.append(cab, dibujo); rejilla.append(tarjeta);
      dibujarLinea(dibujo, s, { ancho: 320, alto: 90, mini: true });
      tarjeta.addEventListener('click', () => { sel.variable.value = String(s.id_sensor); refrescarPorCambio(); });   // clic: verlo en grande
    }
  }

  async function refrescarResumen() {
    const r = await pedir('/api/graficas/resumen');
    dibujarDona($('grDona'), r.estados);
    if ($('grBarras')) dibujarBarras($('grBarras'), r.alertas_por_area);
  }

  // ===========================================================================
  // 4. Arranque
  // ===========================================================================
  async function intentar(tarea) {
    try { await tarea(); } catch (e) {
      console.warn('NOVA gráficas:', e.message);
      const pill = $('grEstado'); pill.textContent = 'Sin conexión'; pill.className = 'pill';
    }
  }
  const refrescarTodo = () => Promise.all([intentar(refrescarSensor), intentar(refrescarMini), intentar(refrescarResumen)]);
  // Cambio hecho por la persona (selector o clic): se redibuja aunque el cursor esté sobre la gráfica
  const refrescarPorCambio = () => { delete $('grLinea').dataset.hover; return refrescarTodo(); };

  async function iniciar() {
    await intentar(async () => {
      catalogo = await pedir('/api/graficas/catalogo');
      for (const a of catalogo.areas) {
        const grupo = document.createElement('optgroup'); grupo.label = a.nombre;
        for (const m of a.maquinas) grupo.append(new Option(`${m.codigo} · ${m.nombre}`, m.id_maquina));
        sel.maquina.append(grupo);
      }
      llenarVariables();
    });
    if (!catalogo) return;
    sel.maquina.addEventListener('change', () => { llenarVariables(); refrescarPorCambio(); });
    sel.variable.addEventListener('change', refrescarPorCambio);
    sel.ventana.addEventListener('change', refrescarPorCambio);
    await refrescarTodo();
    // Se repite solo; con la pestaña oculta no se gastan recursos pidiendo datos
    setInterval(() => { if (!document.hidden) refrescarTodo(); }, REFRESCO_MS);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refrescarTodo(); });
  }

  document.addEventListener('DOMContentLoaded', iniciar);
})();
