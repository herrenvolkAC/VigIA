import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = "C:\\Ingenieria\\VigIA";
const inputPath = path.join(root, ".codex_tmp", "cargas_choferes", "unified_inputs.json");
const outputDir = path.join(root, "outputs", "cargas_choferes_unificado_por_mapa");

const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
await fs.rm(outputDir, { recursive: true, force: true });
await fs.mkdir(outputDir, { recursive: true });

const maxClearRows = 2000;
let fileCount = 0;
let rowCount = 0;

for (const unit of payload.units) {
  const input = await FileBlob.load(payload.templatePath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const sheet = workbook.worksheets.getItem("Cargas");

  sheet.getRange(`A4:M${maxClearRows}`).clear({ applyTo: "contents" });
  if (unit.rows.length > 0) {
    const values = unit.rows.map((row) => [row.legajo, row.idGerencia, row.idUo]);
    sheet.getRange(`A4:C${unit.rows.length + 3}`).values = values;
  }

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(outputDir, unit.filename));
  fileCount += 1;
  rowCount += unit.rows.length;
}

console.log(JSON.stringify({ outputDir, fileCount, rowCount }, null, 2));
