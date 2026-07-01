import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const templatePath = "\\\\redcoto.com.ar\\patagonia\\CD_Automatizaciones\\Carga PHDT\\ExcelBase\\Ingenieria.xlsx";
const input = await FileBlob.load(templatePath);
const workbook = await SpreadsheetFile.importXlsx(input);

console.log((await workbook.inspect({
  kind: "workbook,sheet,region,computedStyle",
  range: "A1:T12",
  tableMaxRows: 12,
  tableMaxCols: 20,
  maxChars: 9000,
})).ndjson);
