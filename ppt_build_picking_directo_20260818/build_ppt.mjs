import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const TMP = "C:/Ingenieria/VigIA/ppt_build_picking_directo_20260818";
const INPUT = `${TMP}/template-starter.pptx`;
const OUTPUT_DIR = "C:/Ingenieria/VigIA/outputs";
const OUTPUT = `${OUTPUT_DIR}/Picking_Escenario_Direccion_3_filminas.pptx`;

async function writeBlob(path, blob) {
  await fs.mkdir(path.substring(0, path.lastIndexOf("/")), { recursive: true });
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

const p = await PresentationFile.importPptx(await FileBlob.load(INPUT));

const names = {
  "sh/14nedcre": [0, "kicker"], "sh/hs3ix4j2": [0, "title"],
  "sh/6lszip0f": [0, "card-title-0"], "sh/tojitkj6": [0, "card-body-0"], "sh/8nahkfil": [0, "card-label-0"],
  "sh/yx8ze5kj": [0, "card-title-1"], "sh/4vudcnal": [0, "card-body-1"], "sh/pw3e5sr6": [0, "card-label-1"],
  "sh/3alw3290": [0, "card-title-2"], "sh/g7ad8nap": [0, "card-body-2"], "sh/h83e1sra": [0, "card-label-2"],
  "sh/98jm1sf6": [0, "footer2"], "sh/f61wzi94": [0, "footer"], "sh/03exk7at": [0, "footer2"],
  "sh/cjyl8bud": [1, "kicker"], "sh/tgvmdw3m": [1, "title"],
  "sh/eh4nm147": [1, "s-title-0"], "sh/14vmhw3i": [1, "s-formula-0"], "sh/0jm5ormx": [1, "s-body-0"],
  "sh/n6doj6lo": [1, "s-title-1"], "sh/254nq143": [1, "s-formula-1"], "sh/0bel0ru5": [1, "s-body-1"],
  "sh/1c72twvq": [1, "s-title-2"], "sh/epw3yhcz": [1, "s-formula-2"], "sh/fq5krmdk": [1, "s-body-2"],
  "sh/pg72xwbm": [1, "simple"], "sh/2dg321cb": [1, "refs-title"], "sh/nepkv6dw": [1, "refs"],
  "sh/vi907e1o": [2, "kicker"], "sh/gvulgfa9": [2, "title"],
  "sh/7q1k3a9s": [2, "s-title-0"], "sh/srulcfad": [2, "s-formula-0"], "sh/ts325kry": [2, "s-body-0"],
  "sh/i1s365sv": [2, "s-title-1"], "sh/j21kzqtg": [2, "s-formula-1"], "sh/ratkfy1w": [2, "s-body-1"],
  "sh/69kjmt0b": [2, "s-title-2"], "sh/tcb2hoj2": [2, "s-formula-2"], "sh/sb21ojih": [2, "s-body-2"],
  "sh/edkjqt0n": [2, "simple"], "sh/10v2l8zy": [2, "refs-title"], "sh/gz21s3it": [2, "refs"],
};

function setText(id, value) {
  const [slideIndex, name] = names[id];
  const shape = p.slides.items[slideIndex].shapes.items.find((item) => item.name === name);
  if (!shape) throw new Error(`Missing shape ${name} on slide ${slideIndex + 1}`);
  shape.text = value;
}

// Slide 1 — outcome
setText("sh/14nedcre", "RESULTADO MEDIDO");
setText("sh/hs3ix4j2", "Picking | El cálculo directo queda cercano al pago actual");
setText("sh/6lszip0f", "PAGO ACTUAL · JULIO");
setText("sh/tojitkj6", "$48,42 M\n\nReferencia liquidada de julio.\n\nBultos reales\nHora reloj");
setText("sh/8nahkfil", "Método vigente");
setText("sh/yx8ze5kj", "NUEVO DIRECTO");
setText("sh/4vudcnal", "$49,01 M\n\nCálculo por bultos reales,\nsin ajustes sectoriales.\n\nMisma base horaria");
setText("sh/pw3e5sr6", "Sin calibración");
setText("sh/3alw3290", "DIFERENCIA GLOBAL");
setText("sh/g7ad8nap", "+$0,58 M\n\n+1,2% sobre el pago actual.\n\nResultado global similar\nImpacto redistribuido internamente");
setText("sh/h83e1sra", "Lectura gerencial");
setText("sh/98jm1sf6", "Base comparada: Picking · julio 2026");
setText("sh/f61wzi94", "El nuevo método no cambia la unidad: paga bultos reales por hora reloj.");
setText("sh/03exk7at", "La diferencia global es acotada; la revisión necesaria está en la distribución por sector y legajo.");
const slide1Footer2 = p.slides.items[0].shapes.items
  .filter((item) => item.name === "footer2")
  .sort((a, b) => a.frame.top - b.frame.top);
if (slide1Footer2.length >= 2) {
  slide1Footer2[0].text = "Base comparada: Picking · julio 2026";
  slide1Footer2[1].text = "La diferencia global es acotada; la revisión necesaria está en la distribución por sector y legajo.";
}

// Slide 2 — sector calibration
setText("sh/cjyl8bud", "RESULTADO MEDIDO");
setText("sh/tgvmdw3m", "Cinco sectores requieren una calibración específica");
setText("sh/eh4nm147", "SECTORES PROPUESTOS");
setText("sh/14vmhw3i", "B1 · AM · PI · N1 · VA");
setText("sh/0jm5ormx", "Incremento propuesto: +30% en la escala monetaria del sector. No modifica los bultos registrados ni crea equivalencias.");
setText("sh/n6doj6lo", "EVIDENCIA OPERATIVA");
setText("sh/254nq143", "428,9 m por etapa\nvs 215,9 m en el resto");
setText("sh/0bel0ru5", "El recorrido medio por etapa es 98,6% superior. La operación exige más desplazamiento para producir una unidad efectiva.");
setText("sh/1c72twvq", "IMPACTO OBSERVADO");
setText("sh/epw3yhcz", "16,23 m por bulto\nvs 14,35 m en el resto");
setText("sh/fq5krmdk", "La diferencia es 13,1% en metros por bulto. El ajuste calibra el valor monetario sin convertir metros en bultos.");
setText("sh/pg72xwbm", "Propuesta: mantener bultos reales y hora reloj; ajustar la escala solo donde la evidencia muestra una exigencia de recorrido superior.");
setText("sh/2dg321cb", "BASE DE MEDICIÓN");
setText("sh/nepkv6dw", "Julio 2026 · PV_ETAPA_CAB.DISTANCIA_EN_METROS · Picking · 72.052 etapas en los cinco sectores / 131.807 en el resto");

// Slide 3 — group prize condition
setText("sh/vi907e1o", "CONDICIÓN DE IMPLEMENTACIÓN");
setText("sh/gvulgfa9", "El premio grupal requiere alinear nómina y actividad real");
setText("sh/7q1k3a9s", "NÓMINA TEÓRICA");
setText("sh/srulcfad", "≈143 legajos / día");
setText("sh/ts325kry", "Promedio de legajos-jornada asignados a Picking en julio. Esta nómina alimenta el denominador del objetivo grupal.");
setText("sh/i1s365sv", "ACTIVIDAD REAL");
setText("sh/j21kzqtg", "5–6 legajos / día sin bultos");
setText("sh/ratkfy1w", "3,6% de las jornadas-legajo no registra bultos de Picking y sí registra otra actividad productiva medida.");
setText("sh/69kjmt0b", "EFECTO SOBRE EL GRUPO");
setText("sh/tcb2hoj2", "Denominador alto\nNumerador incompleto");
setText("sh/sb21ojih", "La persona permanece en la nómina de Picking, pero no suma bultos allí. El cumplimiento grupal queda subestimado y el premio no se activa.");
setText("sh/edkjqt0n", "Conclusión: el premio grupal es viable cuando la nómina activa refleje la tarea efectivamente realizada por cada legajo.");
setText("sh/10v2l8zy", "EVIDENCIA DEL CACHÉ");
setText("sh/gz21s3it", "Julio 2026 · 4.433 jornadas-legajo Picking · 170 sin productividad Picking · 160 con otra operación medida · 94,1% de los casos sin Picking tiene otra actividad");

const notes = [
  "Presentar primero la lectura global: el método directo queda prácticamente alineado con el pago vigente.\n\n[Sources]\n- Caché SQLite del módulo análisis premio productividad, Picking, julio 2026.\n- Comparación de pago actual vs. nuevo método directo sin ajustes sectoriales.\n[/Sources]",
  "El +30% se presenta como calibración basada en evidencia de recorrido, no como conversión de metros a bultos.\n\n[Sources]\n- Oracle Productiv, PV_ETAPA_CAB.DISTANCIA_EN_METROS, Picking, julio 2026.\n- Comparación de sectores B1, AM, PI, N1, VA contra el resto.\n[/Sources]",
  "La limitación del premio grupal no es conceptual: es de correspondencia entre la nómina teórica y la tarea efectivamente realizada.\n\n[Sources]\n- Caché SQLite pp_operacion_evidencia_dia, Picking, julio 2026.\n- 4.433 jornadas-legajo; 170 sin productividad Picking; 160 con otra operación medida.\n[/Sources]",
];
for (const [index, noteText] of notes.entries()) {
  const slide = p.slides.items[index];
  slide.speakerNotes.textFrame.setText(noteText);
  slide.speakerNotes.setVisible(true);
}

await fs.mkdir(OUTPUT_DIR, { recursive: true });
for (const [i, slide] of p.slides.items.entries()) {
  const stem = `final-slide-${String(i + 1).padStart(2, "0")}`;
  await writeBlob(`${TMP}/${stem}.png`, await p.export({ slide, format: "png", scale: 1 }));
  await fs.writeFile(`${TMP}/${stem}.layout.json`, await (await slide.export({ format: "layout" })).text());
}
await writeBlob(`${TMP}/final-montage.webp`, await p.export({ format: "webp", montage: true, scale: 1 }));
const pptx = await PresentationFile.exportPptx(p);
await pptx.save(OUTPUT);
console.log(JSON.stringify({ output: OUTPUT, slides: p.slides.items.length }, null, 2));
