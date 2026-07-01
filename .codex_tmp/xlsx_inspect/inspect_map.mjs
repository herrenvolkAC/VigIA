import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const input = await FileBlob.load('C:/Users/207189/Downloads/MAPA DE PLANIFICACIONES ACTUALIZADO (1).xlsx');
const wb = await SpreadsheetFile.importXlsx(input);
const out = await wb.inspect({kind:'workbook,sheet,region,table,drawing', maxChars:8000, tableMaxRows:20, tableMaxCols:25});
console.log(out.ndjson);
