import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = path.join(
  "C:\\Ingenieria\\VigIA",
  "outputs",
  "cargas_choferes_unificado_por_mapa",
  "DEPOSITO - DEVOLUCIONES - 126 - ENVASES Y EMBALAJES - DEVOLUCIONES + ENVASES.xlsx",
);
const previewPath = path.join("C:\\Ingenieria\\VigIA", ".codex_tmp", "cargas_choferes", "unified_sample.png");

const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);
console.log((await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 1000 })).ndjson);

const preview = await workbook.render({
  sheetName: "Cargas",
  range: "A1:M16",
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
console.log(previewPath);
