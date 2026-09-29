const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('static/novedades_cd.html', 'utf8');
const source = html.slice(html.indexOf('  async function applyAllTabs()'), html.indexOf('  async function importRequest'));
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => {resolve=yes; reject=no;}); return {promise, resolve, reject}; }
async function scenario(fail) {
  const activity = deferred(), sanctions = deferred();
  const statuses = [], loading = [];
  let calls=0;
  const context = {
    state: {},
    setApplyLoading(value) { context.state.applyLoading=value; loading.push(value); },
    setStatus(value) { statuses.push(value); },
    loadIndicators: async () => {},
    loadActividad: () => { calls++; return activity.promise; },
    loadSanciones: () => sanctions.promise,
    loadFrancos: async () => {},
    loadPresencias: async options => { assert.equal(options.manageApply,false); assert.equal(options.finalStatus,false); },
    loadBatches: async () => {},
    $: () => ({classList:{remove(){}}}), saveFilters() {}
  };
  vm.createContext(context); vm.runInContext(source,context);
  const running = context.applyAllTabs();
  await new Promise(setImmediate);
  await context.applyAllTabs();
  assert.equal(calls,1,'Evita consultas superpuestas');
  if (fail) sanctions.reject(new Error('Fallo de sanciones')); else sanctions.resolve();
  await new Promise(setImmediate);
  assert.equal(context.state.applyLoading,true,'Actividad sigue pendiente');
  assert.deepEqual(loading,[true]);
  activity.resolve(); await running;
  assert.deepEqual(loading,[true,false]);
  assert.ok(statuses.at(-1).includes(fail ? 'Fallo de sanciones' : 'actualizados'));
}
(async () => { await scenario(false); await scenario(true); console.log('OK: espera Actividad, espera tras error y evita consultas simultáneas'); })().catch(error => {console.error(error);process.exitCode=1;});
