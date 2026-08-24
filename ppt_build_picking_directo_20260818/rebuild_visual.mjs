import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const TMP = "C:/Ingenieria/VigIA/ppt_build_picking_directo_20260818";
const INPUT = "C:/Ingenieria/VigIA/outputs/Picking_Escenario_Direccion_3_filminas.pptx";
const OUTPUT = "C:/Ingenieria/VigIA/outputs/Picking_Escenario_Direccion_3_filminas_final.pptx";

const C = {
  navy: "#0B1630",
  blue: "#0E5AA7",
  blue2: "#153D72",
  ink: "#142033",
  muted: "#52657E",
  pale: "#F4F7FA",
  white: "#FFFFFF",
  green: "#00A37A",
  greenPale: "#DDF4EC",
  orange: "#F2A33A",
  orangePale: "#FFF0D5",
  red: "#C9444E",
  line: "#D8E1EA",
};

async function writeBlob(path, blob) {
  await fs.mkdir(path.substring(0, path.lastIndexOf("/")), { recursive: true });
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

const p = await PresentationFile.importPptx(await FileBlob.load(INPUT));

function addShape(slide, geometry, left, top, width, height, fill = "none", line = { style: "solid", fill: "none", width: 0 }, name) {
  return slide.shapes.add({ geometry, name, position: { left, top, width, height }, fill, line });
}

function rect(slide, left, top, width, height, fill, radius = 0, line = { style: "solid", fill: "none", width: 0 }, name) {
  const s = addShape(slide, radius ? "roundRect" : "rect", left, top, width, height, fill, line, name);
  if (radius) s.borderRadius = radius;
  return s;
}

function txt(slide, text, left, top, width, height, style = {}, name) {
  const s = addShape(slide, "textbox", left, top, width, height, "none", { style: "solid", fill: "none", width: 0 }, name);
  s.text = text;
  s.text.style = {
    fontSize: style.fontSize ?? 18,
    color: style.color ?? C.ink,
    bold: style.bold ?? false,
    fontFamily: "Aptos",
  };
  if (style.alignment) s.text.alignment = style.alignment;
  return s;
}

function cover(slide, fill) {
  slide.background.fill = fill;
  rect(slide, 0, 0, 1280, 720, fill, 0, { style: "solid", fill, width: 0 }, "visual-cover");
}

function header(slide, kicker, title, subtitle, dark = false) {
  const color = dark ? C.white : C.ink;
  const muted = dark ? "#B9C8DC" : C.muted;
  txt(slide, kicker, 64, 36, 520, 18, { fontSize: 11, color: C.green, bold: true }, "kicker");
  txt(slide, title, 64, 62, 1080, 50, { fontSize: 31, color, bold: true }, "title");
  rect(slide, 64, 120, 92, 5, C.green);
  if (subtitle) txt(slide, subtitle, 64, 142, 1100, 30, { fontSize: 15, color: muted }, "subtitle");
}

function metricCard(slide, x, y, w, h, label, value, detail, accent, dark = false) {
  const fill = dark ? C.blue2 : C.white;
  const labelColor = dark ? "#C9D8EA" : C.muted;
  const valueColor = dark ? C.white : C.ink;
  const detailColor = dark ? "#DCE7F3" : C.muted;
  rect(slide, x, y, w, h, fill, 14, { style: "solid", fill: dark ? C.blue2 : C.line, width: 1 }, `card-${label}`);
  rect(slide, x, y, 8, h, accent, 0);
  txt(slide, label, x + 28, y + 22, w - 50, 20, { fontSize: 12, color: labelColor, bold: true }, `${label}-label`);
  txt(slide, value, x + 28, y + 57, w - 50, 50, { fontSize: 32, color: valueColor, bold: true }, `${label}-value`);
  txt(slide, detail, x + 28, y + 118, w - 50, 64, { fontSize: 14, color: detailColor }, `${label}-detail`);
}

function pill(slide, text, x, y, w, fill, color) {
  rect(slide, x, y, w, 30, fill, 15);
  txt(slide, text, x, y + 6, w, 18, { fontSize: 12, color, bold: true, alignment: "center" });
}

function bar(slide, label, value, max, x, y, w, color, valueText) {
  txt(slide, label, x, y, 180, 20, { fontSize: 14, color: C.ink, bold: true });
  rect(slide, x, y + 29, w, 16, "#E6EDF4", 8);
  rect(slide, x, y + 29, Math.max(8, (value / max) * w), 16, color, 8);
  txt(slide, valueText, x + w + 18, y + 24, 160, 28, { fontSize: 19, color: C.ink, bold: true });
}

function stepCard(slide, x, y, w, h, number, label, value, detail, fill, valueColor = C.ink) {
  rect(slide, x, y, w, h, fill, 16, { style: "solid", fill: fill === C.white ? C.line : fill, width: 1 });
  rect(slide, x + 24, y + 24, 34, 34, C.green, 17);
  txt(slide, String(number), x + 24, y + 31, 34, 20, { fontSize: 15, color: C.white, bold: true, alignment: "center" });
  txt(slide, label, x + 24, y + 78, w - 48, 22, { fontSize: 13, color: C.muted, bold: true });
  txt(slide, value, x + 24, y + 108, w - 48, 45, { fontSize: 27, color: valueColor, bold: true });
  txt(slide, detail, x + 24, y + 164, w - 48, 72, { fontSize: 14, color: C.muted });
}

// Slide 1: outcome
{
  const s = p.slides.items[0];
  cover(s, C.navy);
  header(s, "ESCENARIO PICKING · JULIO 2026", "El nuevo individual queda 25,8% por debajo del actual", "Bultos reales · hora reloj · sin premio grupal", true);
  metricCard(s, 64, 220, 350, 220, "PAGO ACTUAL", "$50,89 M", "Monto liquidado en julio\nBase de comparación", C.orange, false);
  metricCard(s, 465, 220, 350, 220, "NUEVO DIRECTO", "$37,77 M", "Cálculo directo por bultos\nSin calibración sectorial", C.green, true);
  metricCard(s, 866, 220, 350, 220, "DIFERENCIA", "-$13,12 M", "-25,8% frente al pago actual\nSin premio grupal", C.orange, false);
  pill(s, "LECTURA GERENCIAL", 64, 488, 168, C.greenPale, C.green);
  txt(s, "La brecha individual es de $13,12 M antes de cualquier premio grupal.", 64, 535, 1080, 42, { fontSize: 22, color: C.white, bold: true });
  txt(s, "La unidad de pago se mantiene: producción efectiva registrada y horas reloj.", 64, 615, 1000, 24, { fontSize: 14, color: "#B9C8DC" });
  txt(s, "Fuente: caché de productividad · Picking · julio 2026", 1010, 665, 210, 18, { fontSize: 10, color: "#8DA3BE", alignment: "right" });
}

// Slide 2: calibration
{
  const s = p.slides.items[1];
  cover(s, C.pale);
  header(s, "CALIBRACIÓN PROPUESTA", "El ajuste del 30% reduce la brecha, pero no la elimina", "La evidencia muestra mayor recorrido operativo por unidad real", false);
  rect(s, 64, 206, 350, 340, C.blue2, 18, { style: "solid", fill: C.blue2, width: 0 });
  txt(s, "SECTORES", 94, 238, 260, 20, { fontSize: 12, color: "#A9C5E4", bold: true });
  txt(s, "B1 · Bebidas\nAM · Alimentos mascotas\nPI · Electrodomésticos\nN1 · Insumo a sucursales\nVA · Varios No Alimentos", 94, 278, 270, 115, { fontSize: 16, color: C.white, bold: true });
  pill(s, "+30% escala", 94, 420, 146, C.green, C.white);
  txt(s, "Propuesta de calibración\nsobre el valor monetario del premio.", 94, 468, 260, 52, { fontSize: 15, color: "#D8E6F3" });
  txt(s, "No convierte metros en bultos.", 94, 526, 270, 20, { fontSize: 12, color: C.orange, bold: true });
  rect(s, 454, 206, 762, 340, C.white, 18, { style: "solid", fill: C.line, width: 1 });
  txt(s, "¿Qué se midió?", 492, 238, 280, 24, { fontSize: 17, color: C.ink, bold: true });
  txt(s, "Promedio de recorrido por unidad efectiva", 492, 270, 520, 22, { fontSize: 14, color: C.muted });
  bar(s, "Cinco sectores", 428.9, 428.9, 492, 324, 400, C.green, "428,9 m / etapa");
  bar(s, "Resto de sectores", 215.9, 428.9, 492, 394, 400, C.blue, "215,9 m / etapa");
  rect(s, 492, 455, 660, 1, C.line);
  txt(s, "98,6% más metros por etapa", 492, 474, 310, 24, { fontSize: 16, color: C.green, bold: true });
  txt(s, "16,23 m/bulto vs 14,35 m/bulto en el resto (+13,1%)", 492, 505, 650, 22, { fontSize: 14, color: C.muted });
  rect(s, 64, 585, 1152, 64, C.orangePale, 14, { style: "solid", fill: C.orangePale, width: 0 });
  txt(s, "Criterio", 88, 602, 100, 20, { fontSize: 13, color: C.orange, bold: true });
  txt(s, "Mantener bultos reales y hora reloj; calibrar el premio donde el recorrido operativo medido sea sistemáticamente superior.", 190, 601, 990, 32, { fontSize: 15, color: C.ink, bold: true });
  txt(s, "Resultado: $37,77 M directo · $45,03 M con ajuste · $50,89 M actual", 64, 658, 1100, 18, { fontSize: 13, color: C.ink, bold: true });
  txt(s, "Fuente: PV_ETAPA_CAB.DISTANCIA_EN_METROS · julio 2026 · 72.052 etapas en los cinco sectores / 131.807 en el resto", 64, 682, 1100, 14, { fontSize: 9.5, color: C.muted });
}

// Slide 3: group prize condition
{
  const s = p.slides.items[2];
  cover(s, C.white);
  header(s, "PREMIO GRUPAL", "El premio se pierde por dos causas distintas", "La nómina teórica no coincide con la actividad que alcanza premio", false);
  stepCard(s, 64, 220, 340, 270, 1, "NÓMINA TEÓRICA", "≈143 / día", "Legajos asignados a Picking\nque alimentan el denominador\ndel objetivo grupal.", C.pale);
  stepCard(s, 470, 220, 340, 270, 2, "SIN BULTOS EFECTIVOS", "5–6 / día", "179 jornadas-legajo · 4,0%\nNo aportan bultos de Picking\nal numerador.", C.pale);
  stepCard(s, 876, 220, 340, 270, 3, "BULTOS SIN PREMIO", "4–5 / día", "145 jornadas-legajo · 3,3%\nSí tienen bultos, pero no\nalcanzan el mínimo individual.", C.orangePale, C.red);
  // arrows
  txt(s, "→", 420, 326, 40, 38, { fontSize: 30, color: C.green, bold: true, alignment: "center" });
  txt(s, "→", 826, 326, 40, 38, { fontSize: 30, color: C.green, bold: true, alignment: "center" });
  rect(s, 64, 535, 1152, 90, C.navy, 16, { style: "solid", fill: C.navy, width: 0 });
  txt(s, "EVIDENCIA JULIO", 92, 559, 175, 18, { fontSize: 12, color: C.green, bold: true });
  txt(s, "7,3%", 275, 548, 120, 40, { fontSize: 28, color: C.white, bold: true });
  txt(s, "de las jornadas-legajo no obtiene premio individual (≈10–11 por día)", 398, 556, 740, 28, { fontSize: 15, color: "#DCE7F3" });
  txt(s, "Conclusión", 64, 660, 95, 18, { fontSize: 12, color: C.green, bold: true });
  txt(s, "El umbral exige 90% de cumplidores: si una división/día supera 10% sin premio, el adicional no se habilita.", 170, 656, 980, 22, { fontSize: 15, color: C.ink, bold: true });
}

const sourceNote = "[Sources]\n- Caché SQLite del módulo análisis premio productividad, Picking, julio 2026; 4.442 jornadas-legajo.\n- Oracle Productiv: PV_ETAPA_CAB.DISTANCIA_EN_METROS, julio 2026.\n- Evidencia de nómina y actividad: 179 jornadas-legajo sin bultos efectivos; 145 con bultos pero sin premio individual.\n[/Sources]";
for (const slide of p.slides.items) {
  slide.speakerNotes.textFrame.setText(`Presentación ejecutiva.\n\n${sourceNote}`);
  slide.speakerNotes.setVisible(true);
}

await fs.mkdir("C:/Ingenieria/VigIA/outputs", { recursive: true });
for (const [i, slide] of p.slides.items.entries()) {
  const stem = `reconversion-slide-${String(i + 1).padStart(2, "0")}`;
  await writeBlob(`${TMP}/${stem}.png`, await p.export({ slide, format: "png", scale: 1 }));
  await fs.writeFile(`${TMP}/${stem}.layout.json`, await (await slide.export({ format: "layout" })).text());
}
await writeBlob(`${TMP}/reconversion-montage.webp`, await p.export({ format: "webp", montage: true, scale: 1 }));
const pptx = await PresentationFile.exportPptx(p);
await pptx.save(OUTPUT);
console.log(JSON.stringify({ output: OUTPUT, slides: p.slides.items.length }, null, 2));
