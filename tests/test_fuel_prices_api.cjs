// Skutečný exportér testujeme bez připojení ke Google a bez skutečného tokenu.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const groups = [
  ['HA data', input.keys.slice(0, 10), 'pellets'],
  ['RUF HA data', input.keys.slice(10, 13), 'ruf'],
  ['Válcové HA data', input.keys.slice(13), 'valcove']
];
const sheets = {};
for (const [name, keys] of groups) {
  const rows = keys.map((key, index) => [
    key, 'Testovací prodejce', 12.18095238095238,
    index === 0 ? null : 0, 'SKLADEM',
    new Date('2026-09-09T06:18:00Z'), 'https://example.test/nabidka'
  ]);
  rows.push(['', '', '', '', '', '', '']);
  sheets[name] = {
    getLastRow: () => rows.length + 2,
    getRange: (row, col, count, width) => {
      assert.deepEqual([row, col, count, width], [3, 1, rows.length, 7]);
      return {getValues: () => rows};
    }
  };
}
let reads = 0;
const context = vm.createContext({
  Date,
  PropertiesService: {getScriptProperties: () => ({
    getProperty: key => {
      assert.equal(key, 'HA_TOKEN');
      return 'test-only-token';
    }
  })},
  SpreadsheetApp: {openById: id => {
    reads++;
    assert.equal(id, '19xq-1TWFLIzEax05AWibkNSTMfRBEw8Oqv1ujXdRAnk');
    return {getSheetByName: name => sheets[name]};
  }},
  ContentService: {
    MimeType: {JSON: 'application/json'},
    createTextOutput: text => ({setMimeType: () => JSON.parse(text)})
  }
});
vm.runInContext(fs.readFileSync('tools/fuel_prices_api.gs', 'utf8'), context);
assert.equal(context.doGet().error, 'unauthorized');
assert.equal(context.doGet({parameter: {token: 'wrong'}}).error, 'unauthorized');
assert.equal(reads, 0);
const data = context.doGet({parameter: {token: 'test-only-token'}});
assert.equal(data.ok, true);
assert.deepEqual(Object.keys(data.items).sort(), [...input.keys].sort());
assert.equal(Object.keys(data.items).length, 16);
for (const [, keys, group] of groups) {
  assert.deepEqual(Object.keys(data[group]), keys);
  assert.equal(data[group][keys[0]].change_10d_per_kg, null);
  assert.equal(data[group][keys[1]].change_10d_per_kg, 0);
  assert.equal(data[group][keys[0]].checked_at, '2026-09-09T06:18:00.000Z');
  assert.equal(data[group][keys[0]].price_per_kg, 12.18095238095238);
}
for (const value of ['', null, undefined, 'unknown', Infinity, NaN]) {
  assert.equal(context.numberOrNull_(value), null);
}
assert.equal(context.numberOrNull_('12,2'), 12.2);
delete sheets['Válcové HA data'];
assert.equal(context.doGet({parameter: {token: 'test-only-token'}}).ok, false);

// Pomlčka odlišuje chybějící změnu od skutečné nuly, i při výpadku senzoru.
function render(state, change) {
  const elements = [{}, {}];
  const hass = {states: {test: {state, attributes: {
    change_10d_per_kg: change, checked_at: '2026-09-09T06:18:00Z'
  }}}};
  const card = {querySelector: selector => elements[selector.includes('-1 ') ? 0 : 1]};
  vm.runInNewContext('result = `' + input.styles + '`', {hass, card, entity: 'test'});
  return elements;
}
assert.equal(render('12.2', null)[0].textContent, '10 dní: —');
assert.equal(render('12.2', 0)[0].textContent, '10 dní: 0');
assert.equal(render('12.2', 1.364102)[0].textContent, '10 dní: +1,364');
assert.equal(render('12.2', -0.5)[0].textContent, '10 dní: -0,5');
assert.equal(render('unavailable', 0)[0].textContent, '10 dní: —');
assert.equal(render('unknown', 0)[1].textContent, 'Ověřeno: —');
assert.match(render('12.2', 0)[1].textContent, /8:18/);
console.log('Export tří kategorií, ochrana tokenem a zobrazení chybějících dat: OK');
