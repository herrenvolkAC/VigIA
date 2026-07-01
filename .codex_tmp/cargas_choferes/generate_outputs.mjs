import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = "C:/Ingenieria/VigIA";
const inputPath = `${root}/.codex_tmp/cargas_choferes/inputs.json`;
const outputDir = `${root}/outputs/cargas_choferes_por_unidad`;

const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
await fs.mkdir(outputDir, { recursive: true });

for (const item of await fs.readdir(outputDir)) {
  if (item.toLowerCase().endsWith(".xlsx") || item.toLowerCase().endsWith(".ndjson")) {
    await fs.unlink(path.join(outputDir, item));
  }
}

const maxRowsToClear = Math.max(
  500,
  ...payload.units.map((unit) => unit.rows.length + 10),
);

for (const unit of payload.units) {
  const template = await FileBlob.load(payload.templatePath);
  const workbook = await SpreadsheetFile.importXlsx(template);
  const sheet = workbook.worksheets.getItem("Cargas");

  sheet.getRange(`A4:T${maxRowsToClear}`).clear({ applyTo: "contents" });

  if (unit.rows.length) {
    const rows = unit.rows.map((row) => [row.legajo, row.idGerencia, row.idUo]);
    const target = sheet.getRangeByIndexes(3, 0, rows.length, 3);
    target.values = rows;
    target.format.numberFormat = rows.map(() => ["@", "@", "@"]);
  }

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(path.join(outputDir, unit.filename));
}

await fs.writeFile(
  `${outputDir}/_resumen_generacion.json`,
  JSON.stringify(
    {
      generatedAt: new Date().toISOString(),
      outputDir,
      latestBatchId: payload.latestBatchId,
      summary: payload.summary,
      files: payload.units.map((unit) => ({
        file: unit.filename,
        unidad: unit.unidad,
        legajos: unit.legajos,
        mappedRows: unit.mappedRows,
        unmappedRows: unit.unmappedRows,
      })),
    },
    null,
    2,
  ),
  "utf8",
);

console.log(JSON.stringify({ outputDir, summary: payload.summary }, null, 2));
