import fs from 'node:fs/promises';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const inputPath = 'datos/premio_tabla_foto.json';
const outputDir = 'outputs/premios_sector_picking';
const outputPath = `${outputDir}/premios_sector_picking.xlsx`;
const source = JSON.parse(await fs.readFile(inputPath, 'utf8'));
const workbook = Workbook.create();
const grid = workbook.worksheets.add('Grilla por sector');
const summary = workbook.worksheets.add('Resumen sectores');
const base = workbook.worksheets.add('Escala base');
const meta = workbook.worksheets.add('Metadatos');

const header = { fill: '#0F766E', font: { bold: true, color: '#FFFFFF' }, wrapText: true, horizontalAlignment: 'center', verticalAlignment: 'center' };
const title = { fill: '#123047', font: { bold: true, color: '#FFFFFF', size: 14 }, horizontalAlignment: 'left', verticalAlignment: 'center' };
const subheader = { fill: '#DCEFE8', font: { bold: true, color: '#123047' } };
const moneyFormat = '$#,##0.00';
const numberFormat = '#,##0.00';

const hourlyRows = [...(source.escalas_sector_hora || [])].sort((a, b) => String(a.sector).localeCompare(String(b.sector), 'es') || Number(a.nivel) - Number(b.nivel));
const gridHeaders = ['División', 'Sector', 'Grupo productivo', 'Método', 'Nivel', 'Desde bultos/hora', 'Hasta bultos/hora', 'Desde equivalentes/hora', 'Hasta equivalentes/hora', 'Premio por hora', 'Premio jornada', 'Excedente por unidad', 'Equivalencia', 'Unidad umbral'];
grid.getRange('A1:N1').merge();
grid.getRange('A1').values = [['Tablas de premios por sector · PICKING']];
grid.getRange('A1:N1').format = title;
grid.getRange('A2:N2').merge();
grid.getRange('A2').values = [[`Foto local: ${source.snapshot_id} · Capturada: ${source.captured_at} · Filas: ${hourlyRows.length}`]];
grid.getRange('A2:N2').format = subheader;
grid.getRange('A4:N4').values = [gridHeaders];
grid.getRange('A4:N4').format = header;
grid.getRange('A5:N' + (hourlyRows.length + 4)).values = hourlyRows.map(row => [
  row.division, row.sector, row.grupo_productivo, row.metodo_de_calculo, row.nivel,
  row.desde_hora_bultos, row.hasta_hora_bultos, row.desde_hora_equiv, row.hasta_hora_equiv,
  row.premio_hora, row.premio_jornada, row.excedente_por_unidad, row.equivalencia, row.unidad_umbral,
]);
grid.getRange('A4:N' + (hourlyRows.length + 4)).format.borders = { preset: 'all', style: 'thin', color: '#D9E2E5' };
grid.getRange('A5:A' + (hourlyRows.length + 4)).format.numberFormat = '0';
grid.getRange('E5:E' + (hourlyRows.length + 4)).format.numberFormat = '0';
grid.getRange('F5:I' + (hourlyRows.length + 4)).format.numberFormat = numberFormat;
grid.getRange('J5:L' + (hourlyRows.length + 4)).format.numberFormat = moneyFormat;
grid.getRange('M5:M' + (hourlyRows.length + 4)).format.numberFormat = '0.000';
grid.freezePanes.freezeRows(4);
grid.freezePanes.freezeColumns(2);
grid.showGridLines = false;
grid.tables.add(`A4:N${hourlyRows.length + 4}`, true, 'PremiosSectorPicking');
grid.getRange('A:N').format.columnWidth = 14;
grid.getRange('A:A').format.columnWidth = 10;
grid.getRange('B:B').format.columnWidth = 14;
grid.getRange('C:C').format.columnWidth = 28;
grid.getRange('D:D').format.columnWidth = 15;
grid.getRange('N:N').format.columnWidth = 16;

const sectorMap = new Map();
for (const row of hourlyRows) {
  const key = `${row.division}|${row.sector}`;
  if (!sectorMap.has(key)) sectorMap.set(key, { division: row.division, sector: row.sector, grupo_productivo: row.grupo_productivo, metodo_de_calculo: row.metodo_de_calculo, equivalencia: row.equivalencia, niveles: 0, min_premio: null, max_premio: null });
  const item = sectorMap.get(key); item.niveles += 1;
  item.min_premio = item.min_premio == null ? Number(row.premio_hora || 0) : Math.min(item.min_premio, Number(row.premio_hora || 0));
  item.max_premio = item.max_premio == null ? Number(row.premio_hora || 0) : Math.max(item.max_premio, Number(row.premio_hora || 0));
}
const summaryRows = [...sectorMap.values()].sort((a, b) => String(a.sector).localeCompare(String(b.sector), 'es'));
summary.getRange('A1:H1').merge(); summary.getRange('A1').values = [['Resumen de sectores · PICKING']]; summary.getRange('A1:H1').format = title;
summary.getRange('A2:H2').merge(); summary.getRange('A2').values = [['Cada sector mantiene su propia equivalencia y escala de premios por nivel.']]; summary.getRange('A2:H2').format = subheader;
summary.getRange('A4:H4').values = [['División', 'Sector', 'Grupo productivo', 'Método', 'Equivalencia', 'Niveles', 'Premio hora mínimo', 'Premio hora máximo']]; summary.getRange('A4:H4').format = header;
summary.getRange(`A5:H${summaryRows.length + 4}`).values = summaryRows.map(row => [row.division, row.sector, row.grupo_productivo, row.metodo_de_calculo, row.equivalencia, row.niveles, row.min_premio, row.max_premio]);
summary.getRange(`A4:H${summaryRows.length + 4}`).format.borders = { preset: 'all', style: 'thin', color: '#D9E2E5' };
summary.getRange(`E5:E${summaryRows.length + 4}`).format.numberFormat = '0.000'; summary.getRange(`G5:H${summaryRows.length + 4}`).format.numberFormat = moneyFormat;
summary.freezePanes.freezeRows(4); summary.showGridLines = false; summary.tables.add(`A4:H${summaryRows.length + 4}`, true, 'ResumenSectoresPicking');
summary.getRange('A:H').format.columnWidth = 18; summary.getRange('C:C').format.columnWidth = 28; summary.getRange('D:D').format.columnWidth = 15;

const baseRows = [...(source.escalas || [])].filter(row => String(row.operacion).toUpperCase() === 'PICKING').sort((a, b) => String(a.grupo_productivo).localeCompare(String(b.grupo_productivo), 'es') || Number(a.nivel) - Number(b.nivel));
base.getRange('A1:G1').merge(); base.getRange('A1').values = [['Escala base de premios · PICKING']]; base.getRange('A1:G1').format = title;
base.getRange('A2:G2').merge(); base.getRange('A2').values = [['Escala general por grupo productivo; la grilla por sector contiene los cortes específicos de bultos/hora.']]; base.getRange('A2:G2').format = subheader;
base.getRange('A4:G4').values = [['Grupo productivo', 'Nivel', 'Desde jornada', 'Hasta jornada', 'Premio jornada', 'Excedente por unidad', 'ID grupo productivo']]; base.getRange('A4:G4').format = header;
base.getRange(`A5:G${baseRows.length + 4}`).values = baseRows.map(row => [row.grupo_productivo, row.nivel, row.desde, row.hasta, row.premio, row.premio_por_unidad_excedente, row.id_grupo_productivo]);
base.getRange(`A4:G${baseRows.length + 4}`).format.borders = { preset: 'all', style: 'thin', color: '#D9E2E5' };
base.getRange(`E5:F${baseRows.length + 4}`).format.numberFormat = moneyFormat; base.freezePanes.freezeRows(4); base.showGridLines = false; base.tables.add(`A4:G${baseRows.length + 4}`, true, 'EscalaBasePicking');
base.getRange('A:A').format.columnWidth = 28; base.getRange('B:G').format.columnWidth = 18;

meta.getRange('A1:B1').merge(); meta.getRange('A1').values = [['Metadatos de la fuente']]; meta.getRange('A1:B1').format = title;
meta.getRange('A3:B7').values = [['Campo', 'Valor'], ['Snapshot', source.snapshot_id], ['Fecha de captura', source.captured_at], ['Hash de fuente', source.source_hash], ['Origen', 'datos/premio_tabla_foto.json']]; meta.getRange('A3:B3').format = header; meta.getRange('A3:B7').format.borders = { preset: 'all', style: 'thin', color: '#D9E2E5' }; meta.getRange('A:A').format.columnWidth = 22; meta.getRange('B:B').format.columnWidth = 48; meta.showGridLines = false;

await fs.mkdir(outputDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook); await xlsx.save(outputPath);
const check = await workbook.inspect({ kind: 'table', sheetId: 'Grilla por sector', range: 'A1:N12', include: 'values', tableMaxRows: 12, tableMaxCols: 14, maxChars: 4000 });
console.log(check.ndjson);
const preview = await workbook.render({ sheetName: 'Grilla por sector', range: 'A1:N16', scale: 1, format: 'png' });
await fs.writeFile(`${outputDir}/preview.png`, new Uint8Array(await preview.arrayBuffer()));
console.log(`OUTPUT=${outputPath}`);
