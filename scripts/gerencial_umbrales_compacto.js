/* El detalle se abre fuera del lienzo: no agrega hojas ni reduce la lámina. */
document.querySelectorAll('[data-open-profile]').forEach(button => {
  button.addEventListener('click', () => {
    const dialog = document.getElementById('detalle-' + button.dataset.openProfile);
    if (dialog) { dialog.appendChild(document.getElementById('chart-tooltip')); dialog.showModal(); dialog.scrollTop = 0; }
  });
});
document.querySelectorAll('.profile-dialog').forEach(dialog => {
  dialog.querySelector('[data-close-profile]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('keydown', event => {if (event.key === 'Escape') {event.preventDefault();event.stopPropagation();dialog.close();}});
  dialog.addEventListener('click', event => {if (event.target === dialog) {const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  dialog.addEventListener('close', () => {const tooltip=document.getElementById('chart-tooltip');tooltip.hidden=true;document.body.appendChild(tooltip);});
});
