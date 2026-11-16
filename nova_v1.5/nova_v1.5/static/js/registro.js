/*
  registro.js — ayudas en vivo del formulario "Crear cuenta".
  Son solo comodidades: el servidor vuelve a validar TODO (model/cuentas.py: validar_registro).
    1. Muestra el aviso cuando el rol elegido necesita aprobación de un administrador.
    2. Indica si la contraseña cumple las reglas y si coincide con su confirmación.
    3. Evita el doble envío.
*/
document.addEventListener('DOMContentLoaded', () => {
  const formulario = document.getElementById('registroForm');
  if (!formulario) return;

  const rol = document.getElementById('rol');
  const aviso = document.getElementById('avisoRol');
  const clave = document.getElementById('password');
  const confirmar = document.getElementById('confirmar');
  const ayuda = document.getElementById('ayudaClave');
  const boton = formulario.querySelector('.btn-submit');

  // 1) Aviso de aprobación: cada <option> trae data-aprobacion="1" si necesita permiso
  function actualizarAviso() {
    const opcion = rol.options[rol.selectedIndex];
    aviso.hidden = !(opcion && opcion.dataset.aprobacion === '1');
  }
  rol.addEventListener('change', actualizarAviso);
  actualizarAviso();

  // 2) Reglas de la contraseña (las mismas del servidor): 8+ caracteres, una letra y un número
  function actualizarAyuda() {
    const v = clave.value;
    if (!v) { ayuda.textContent = ''; ayuda.className = 'ayuda-clave'; return; }
    const largo = v.length >= 8, letra = /[A-Za-z]/.test(v), numero = /\d/.test(v);
    const coincide = confirmar.value === '' || confirmar.value === v;
    if (!(largo && letra && numero)) {
      ayuda.textContent = 'Usa al menos 8 caracteres, con una letra y un número.';
      ayuda.className = 'ayuda-clave mal';
    } else if (!coincide) {
      ayuda.textContent = 'Las contraseñas todavía no coinciden.';
      ayuda.className = 'ayuda-clave mal';
    } else {
      ayuda.textContent = confirmar.value ? 'Contraseña válida y confirmada.' : 'Contraseña válida.';
      ayuda.className = 'ayuda-clave bien';
    }
  }
  clave.addEventListener('input', actualizarAyuda);
  confirmar.addEventListener('input', actualizarAyuda);

  // 3) Normaliza el correo y evita enviar dos veces
  formulario.addEventListener('submit', () => {
    const correo = document.getElementById('email');
    correo.value = correo.value.trim().toLowerCase();
    boton.disabled = true;
    boton.textContent = 'Creando cuenta...';
  });
  window.addEventListener('pageshow', () => {
    if (!document.querySelector('.banner-error')) boton.disabled = false;
    boton.textContent = 'Crear cuenta';
  });
});
