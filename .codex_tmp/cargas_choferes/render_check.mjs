import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const file = "C:/Ingenieria/VigIA/outputs/cargas_choferes_por_unidad/CHOFERES CORTA DISTANCIA.xlsx";
const input = await FileBlob.load(file);
const workbook = await SpreadsheetFile.importXlsx(input);

const inspect = await workbook.inspect({
  kind: "region,match",
  sheetId: "Cargas",
  range: "A1:F12",
  maxChars: 4000,
  tableMaxRows: 12,
  tableMaxCols: 6,
});
console.log(inspect.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "Cargas",
  range: "A1:F12",
  scale: 2,
  format: "png",
});
await fs.writeFile(
  "C:/Ingenieria/VigIA/outputs/cargas_choferes_por_unidad_preview.png",
  new Uint8Array(await preview.arrayBuffer()),
);
