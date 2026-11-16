/*
  login.js — pequeños detalles de la pantalla de inicio de sesión.
  La validación REAL del correo y la contraseña ocurre en el servidor (rutas/rutas.py).
  Antes se validaba aquí con usuarios y claves escritos en el código, y cualquiera podía
  verlos desde el navegador; por eso se eliminó.
*/
document.addEventListener('DOMContentLoaded', () => {
  const formulario = document.getElementById('loginForm');
  if (!formulario) return;                          // la página no tiene el formulario: nada que hacer
  const boton = formulario.querySelector('.btn-submit');
  const textoOriginal = boton.textContent;

  formulario.addEventListener('submit', () => {
    // Limpia espacios y mayúsculas del correo antes de enviarlo
    const correo = document.getElementById('username');
    correo.value = correo.value.trim().toLowerCase();

    // Evita que se envíe dos veces si el usuario hace clic repetido
    boton.disabled = true;
    boton.textContent = 'Verificando...';
  });

  // Si el usuario vuelve con el botón "atrás", el botón debe quedar activo de nuevo
  // (salvo que la página esté bloqueada porque no hay conexión con la base de datos)
  window.addEventListener('pageshow', () => {
    if (!document.querySelector('.banner-error')) boton.disabled = false;
    boton.textContent = textoOriginal;
  });
});
