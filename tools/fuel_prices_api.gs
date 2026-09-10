const SPREADSHEET_ID = '19xq-1TWFLIzEax05AWibkNSTMfRBEw8Oqv1ujXdRAnk';

// Stejných sedm sloupců čteme i pro válcové brikety; původní klíče zůstávají.
const HA_SHEETS = {
  pellets: 'HA data',
  ruf: 'RUF HA data',
  valcove: 'Válcové HA data'
};

function doGet(e) {
  try {
    const expectedToken = PropertiesService.getScriptProperties().getProperty('HA_TOKEN');
    const suppliedToken = e && e.parameter ? e.parameter.token : '';

    if (!expectedToken || suppliedToken !== expectedToken) {
      return json_({
        ok: false,
        error: 'unauthorized'
      });
    }

    const spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
    const pellets = readHaSheet_(spreadsheet, HA_SHEETS.pellets);
    const ruf = readHaSheet_(spreadsheet, HA_SHEETS.ruf);
    const valcove = readHaSheet_(spreadsheet, HA_SHEETS.valcove);

    return json_({
      ok: true,
      generated_at: new Date().toISOString(),
      pellets: pellets,
      ruf: ruf,
      valcove: valcove,
      // Společný slovník napájí všech 16 senzorů jedním požadavkem HA.
      items: Object.assign({}, pellets, ruf, valcove)
    });
  } catch (error) {
    return json_({
      ok: false,
      error: String(error && error.message ? error.message : error)
    });
  }
}

function readHaSheet_(spreadsheet, sheetName) {
  const sheet = spreadsheet.getSheetByName(sheetName);
  if (!sheet) {
    throw new Error('Chybí list: ' + sheetName);
  }

  const lastRow = sheet.getLastRow();
  if (lastRow < 3) {
    return {};
  }

  const rows = sheet.getRange(3, 1, lastRow - 2, 7).getValues();
  const result = {};

  rows.forEach(function(row) {
    const key = String(row[0] || '').trim();
    if (!key) {
      return;
    }

    result[key] = {
      seller: String(row[1] || ''),
      price_per_kg: numberOrNull_(row[2]),
      change_10d_per_kg: numberOrNull_(row[3]),
      status: String(row[4] || ''),
      checked_at: dateToIso_(row[5]),
      source: String(row[6] || '')
    };
  });

  return result;
}

function numberOrNull_(value) {
  if (typeof value === 'number' && isFinite(value)) {
    return value;
  }
  if (value === '' || value === null || typeof value === 'undefined') {
    return null;
  }

  const parsed = Number(String(value).replace(',', '.'));
  return isFinite(parsed) ? parsed : null;
}

function dateToIso_(value) {
  if (value instanceof Date && !isNaN(value.getTime())) {
    return value.toISOString();
  }
  return value ? String(value) : null;
}

function json_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
