from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import json
import subprocess
from collections import defaultdict
from decimal import Decimal
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from PIL import Image

from db.paths import ROOT_DIR, resolve_db_path


router = APIRouter(prefix="/api/analisis-premio-productividad", tags=["analisis-premio-productividad"])
logger = logging.getLogger("vigia.analisis_premio_productividad")

PREMIO_DB_PATH = resolve_db_path("PREMIO_PRODUCTIVIDAD_DB_PATH", "premio_productividad.db", ROOT_DIR)
JORNADA_HORAS = 8
DIVISORES_HORARIOS = {8.0, 6.5}
JAVA_HELPER_SRC = ROOT_DIR / "scripts" / "OracleProductividadQuery.java"
JAVA_BUILD_DIR = ROOT_DIR / "scripts" / "java_build"
CASO_MODELO_DIA_QUERY_VERSION = "premio_hora_v11_etapas_python"
CASO_MODELO_DETALLE_QUERY_VERSION = "premio_hora_v9_etapas_python"
DEFAULT_OPERACION = "PICKING"
DEFAULT_ALMACEN = "TODOS"
OPERACIONES_PREMIO_PRODUCTIVIDAD = {DEFAULT_OPERACION}
ALMACENES_PREMIO_PRODUCTIVIDAD = {DEFAULT_ALMACEN, "SECOS + NOA", "CAMARA 06", "OTRAS CAMARAS", "AREA SECOS Y NO ALIMENTOS"}

CONSULTA_PP_ESCALAS = """
/* PP_PREMIO_ESCALAS */
SELECT
    D.DESCRIPCION AS OPERACION,
    D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA,
    F.DESCRIPCION AS GRUPOPRODUCTIVO,
    E.NIVEL,
    E.DESDE AS DESDE_ACTUAL,
    E.HASTA AS HASTA_ACTUAL,
    E.PREMIO AS PREMIO_ACTUAL,
    ROUND(E.DESDE / 8, 0) AS DESDE_X_HORA,
    ROUND(E.HASTA / 8, 0) AS HASTA_X_HORA,
    ROUND(E.PREMIO / 8, 0) AS PREMIO_X_HORA,
    E.ID_DE_GRUPO_PRODUCTIVO,
    E.ID_DE_GRUPO_DE_FUNCIONES
FROM PV_ESCALA_DE_PREMIOS E
JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID
WHERE D.DESCRIPCION = :operacion
ORDER BY D.DESCRIPCION, F.DESCRIPCION, E.NIVEL
"""

CONSULTA_PP_ETAPAS_HORA = """
/* PP_PREMIO_ETAPAS_HORA */
WITH FECHA_PARAM AS (
    SELECT TO_DATE(:fecha_base, 'YYYY/MM/DD') AS FECHA_BASE
    FROM DUAL
),
PARAMS AS (
    SELECT
        FECHA_BASE,
        TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO,
        :operacion AS OPERACION
    FROM FECHA_PARAM
),
ETAPAS AS (
    SELECT
        D.DESCRIPCION AS OPERACION,
        Z.LEGAJO,
        Z.TURNO,
        Z.ID AS ID_PV_DIA_LABORAL,
        A.FYHFIN,
        TRUNC(PARA.FECHA_BASE) AS FECHA,
        TO_NUMBER(TO_CHAR(A.FYHFIN, 'HH24')) AS HORA,
        C.ID_PV_GRUPO_DE_FUNCIONES_CAB,
        A.PRODUCCION_REAL AS PROD_REAL,
        A.PRODUCCION_EQUIV_POR_SECTOR AS PROD_EQUIV_SECTOR,
        A.PRODUCCION_EQUIV_POR_TRASLADO AS PROD_TRASLADO,
        A.PROD_EQUIVAL_POR_CONSOLIDACION AS PROD_CONSOLIDACION,
        A.PRODUCCION_EQUIV_POR_SECTOR
          + A.PRODUCCION_EQUIV_POR_TRASLADO
          + A.PROD_EQUIVAL_POR_CONSOLIDACION AS PROD_FINAL
    FROM PARAMS PARA
    JOIN PV_DIA_LABORAL Z ON PARA.FECHA_PREMIO = Z.FECHA
    JOIN PV_ETAPA_CAB A ON Z.ID = A.ID_PV_DIA_LABORAL
    JOIN PV_FUNCION B ON A.COD_FUNCION = B.CODIGO
    JOIN PV_GRUPO_DE_FUNCIONES_DET C ON C.ID_PV_FUNCION = B.ID
    JOIN PV_GRUPO_DE_FUNCIONES_CAB D
      ON D.ID = C.ID_PV_GRUPO_DE_FUNCIONES_CAB
     AND D.DESCRIPCION = PARA.OPERACION
)
SELECT
    A.OPERACION,
    A.LEGAJO,
    A.TURNO,
    A.ID_PV_DIA_LABORAL,
    A.FECHA,
    A.HORA,
    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
    E.ID_PV_GRUPO_PRODUCTIVO,
    F.DESCRIPCION AS GRUPO_PRODUCTIVO,
    SUM(A.PROD_REAL) AS PROD_REAL,
    SUM(A.PROD_EQUIV_SECTOR) AS PROD_EQUIV_SECTOR,
    SUM(A.PROD_TRASLADO) AS PROD_TRASLADO,
    SUM(A.PROD_CONSOLIDACION) AS PROD_CONSOLIDACION,
    SUM(A.PROD_FINAL) AS PROD_FINAL
FROM ETAPAS A
JOIN PV_LIQUIDAC_DIA_DET1 E
  ON A.ID_PV_DIA_LABORAL = E.ID_PV_DIA_LABORAL
 AND E.ID_PV_GRUPO_DE_FUNCIONES = A.ID_PV_GRUPO_DE_FUNCIONES_CAB
JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_PV_GRUPO_PRODUCTIVO = F.ID
GROUP BY
    A.OPERACION,
    A.LEGAJO,
    A.TURNO,
    A.ID_PV_DIA_LABORAL,
    A.FECHA,
    A.HORA,
    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
    E.ID_PV_GRUPO_PRODUCTIVO,
    F.DESCRIPCION
ORDER BY A.LEGAJO, E.ID_PV_GRUPO_PRODUCTIVO, A.HORA
"""

CONSULTA_PP_LIQUIDACION_DIA = """
/* PP_PREMIO_LIQUIDACION_DIA */
WITH FECHA_PARAM AS (
    SELECT TO_DATE(:fecha_base, 'YYYY/MM/DD') AS FECHA_BASE
    FROM DUAL
),
PARAMS AS (
    SELECT
        FECHA_BASE,
        TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO,
        :operacion AS OPERACION
    FROM FECHA_PARAM
),
ETAPAS AS (
    SELECT
        D.DESCRIPCION AS OPERACION,
        Z.LEGAJO,
        Z.TURNO,
        Z.ID AS ID_PV_DIA_LABORAL,
        C.ID_PV_GRUPO_DE_FUNCIONES_CAB,
        A.PRODUCCION_REAL AS PROD_REAL,
        A.PRODUCCION_EQUIV_POR_SECTOR AS PROD_EQUIV_SECTOR,
        A.PRODUCCION_EQUIV_POR_TRASLADO AS PROD_TRASLADO,
        A.PROD_EQUIVAL_POR_CONSOLIDACION AS PROD_CONSOLIDACION
    FROM PARAMS PARA
    JOIN PV_DIA_LABORAL Z ON PARA.FECHA_PREMIO = Z.FECHA
    JOIN PV_ETAPA_CAB A ON Z.ID = A.ID_PV_DIA_LABORAL
    JOIN PV_FUNCION B ON A.COD_FUNCION = B.CODIGO
    JOIN PV_GRUPO_DE_FUNCIONES_DET C ON C.ID_PV_FUNCION = B.ID
    JOIN PV_GRUPO_DE_FUNCIONES_CAB D
      ON D.ID = C.ID_PV_GRUPO_DE_FUNCIONES_CAB
     AND D.DESCRIPCION = PARA.OPERACION
)
SELECT
    A.OPERACION,
    A.LEGAJO,
    A.TURNO,
    A.ID_PV_DIA_LABORAL,
    ROUND(E.A_PAGAR_TOTAL, 0) AS PREMIO,
    F.DESCRIPCION AS GRUPO_PRODUCTIVO,
    E.ID_PV_GRUPO_PRODUCTIVO,
    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
    SUM(A.PROD_REAL) AS PROD_REAL,
    SUM(A.PROD_EQUIV_SECTOR) AS PROD_EQUIV_SECTOR,
    SUM(A.PROD_TRASLADO) AS PROD_TRASLADO,
    SUM(A.PROD_CONSOLIDACION) AS PROD_CONSOLIDACION,
    SUM(A.PROD_EQUIV_SECTOR + A.PROD_TRASLADO + A.PROD_CONSOLIDACION) AS PROD_FINAL,
    NVL(E.PENALIZACION_EXCESO_TNC, 0) AS PENA_TNC,
    NVL(E.PENALIZACION_POR_ERROR, 0) AS PENA_ERROR
FROM ETAPAS A
JOIN PV_LIQUIDAC_DIA_DET1 E
  ON A.ID_PV_DIA_LABORAL = E.ID_PV_DIA_LABORAL
 AND E.ID_PV_GRUPO_DE_FUNCIONES = A.ID_PV_GRUPO_DE_FUNCIONES_CAB
JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_PV_GRUPO_PRODUCTIVO = F.ID
GROUP BY
    A.OPERACION,
    A.LEGAJO,
    A.TURNO,
    A.ID_PV_DIA_LABORAL,
    E.A_PAGAR_TOTAL,
    F.DESCRIPCION,
    E.ID_PV_GRUPO_PRODUCTIVO,
    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
    E.PENALIZACION_EXCESO_TNC,
    E.PENALIZACION_POR_ERROR
ORDER BY A.LEGAJO, E.ID_PV_GRUPO_PRODUCTIVO
"""
CONSULTA_CASO_MODELO_FINAL = """
WITH ESCALAS AS (
    SELECT
        D.DESCRIPCION AS OPERACION,
        D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA,
        CASE
            WHEN F.DESCRIPCION IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA'
            WHEN F.DESCRIPCION = 'CAMARA 06' THEN 'CAMARA 06'
            WHEN F.DESCRIPCION LIKE 'CAMARA%' THEN 'OTRAS CAMARAS'
            ELSE F.DESCRIPCION
        END AS GRUPOPRODUCTIVO,
        NIVEL,
        DESDE AS DESDE_ACTUAL,
        HASTA AS HASTA_ACTUAL,
        PREMIO AS PREMIO_ACTUAL,
        ROUND(DESDE/8, 0) AS DESDE_X_HORA,
        ROUND(HASTA/8, 0) AS HASTA_X_HORA,
        ROUND(PREMIO/8, 0) AS PREMIO_X_HORA
    FROM PV_ESCALA_DE_PREMIOS E
    JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
    JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID
    WHERE ID_DE_GRUPO_DE_FUNCIONES = :grupo_funciones_id
),
TODO AS (
    SELECT
        TO_DATE(:fecha_operativa, 'YYYY-MM-DD') AS FECHA,
        TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) AS HORA,
        CASE
            WHEN TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) >= 6 AND TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) < 14 THEN '1'
            WHEN TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) >= 14 AND TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) < 22 THEN '2'
            ELSE '3'
        END AS TURNO,
        COPECREA AS OPERARIO,
        UPPER(CDESCRIP) AS OPERACION,
        SUM(QCANTIDA) AS CANTIDAD,
        CASE SUB1.DESCDIVI
            WHEN 'SECTOR SECOS' THEN 'SECOS + NOA '
            WHEN 'VARIOS NO ALIMENTOS' THEN 'SECOS + NOA '
            ELSE SUB1.DESCDIVI
        END AS ALMACEN
    FROM F132HIST A
    LEFT JOIN (
        SELECT DISTINCT CZONALMA, DESCDIVI
        FROM VW_UBICACIONES_DIVISION
    ) SUB1 ON SUB1.CZONALMA = A.CZONAORI
    WHERE A.FCREAREG >= TO_DATE(:fecha_ini, 'YYYY-MM-DD HH24:MI:SS')
      AND A.FCREAREG <= TO_DATE(:fecha_fin, 'YYYY-MM-DD HH24:MI:SS')
      AND COPECREA IN (:legajos)
      AND UPPER(CDESCRIP) = :operacion
    GROUP BY
        TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')),
        COPECREA,
        UPPER(CDESCRIP),
        CASE SUB1.DESCDIVI
            WHEN 'SECTOR SECOS' THEN 'SECOS + NOA '
            WHEN 'VARIOS NO ALIMENTOS' THEN 'SECOS + NOA '
            ELSE SUB1.DESCDIVI
        END
),
TODOPREMIO AS (
    SELECT
        A.*,
        B.DESDE_X_HORA,
        B.HASTA_X_HORA,
        ROUND(PREMIO_ACTUAL/8, 2) AS PREMIO_NUEVO
    FROM TODO A
    LEFT JOIN ESCALAS B
      ON B.GRUPOPRODUCTIVO = 'SECOS + NOA '
     AND CANTIDAD > DESDE_X_HORA
     AND CANTIDAD <= B.HASTA_X_HORA
),
COMPARACION AS (
    SELECT
        A.FECHA,
        A.LEGAJO,
        D.DESCRIPCION AS OPERACION,
        C.PROD_REAL,
        C.PROD_REAL/8 AS PROD_REAL_X_HORA,
        B.A_PAGAR_TOTAL,
        B.ID_PV_UNIDAD_DE_PRODUCCION,
        TURNO AS TURNOPROD
    FROM PV_DIA_LABORAL A
    JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL
    JOIN PV_LIQUIDAC_DIA_DET2 C ON A.ID = C.ID_PV_DIA_LABORAL
        AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES
    JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES
    JOIN PV_ESCALA_DE_PREMIOS E ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
        AND C.ID_PV_GRUPO_PRODUCTIVO = E.ID_DE_GRUPO_PRODUCTIVO
        AND B.OBJETIVO_NIVEL_ALCANZADO = E.NIVEL
    WHERE FECHA = :fecha_yyyymmdd
      AND D.DESCRIPCION = :operacion
      AND A.LEGAJO IN (:legajos)
),
AGG AS (
    SELECT
        A.*,
        B.TURNOPROD,
        PROD_REAL AS PRODUCTIVIDAD_ANTERIOR,
        A_PAGAR_TOTAL AS PREMIO_ANTERIOR,
        CASE
            WHEN TURNO = TURNOPROD THEN CANTIDAD
            ELSE 0
        END AS DENTROTURNO
    FROM TODOPREMIO A
    JOIN COMPARACION B ON A.OPERARIO = B.LEGAJO
),
FINAL AS (
    SELECT
        FECHA,
        OPERARIO,
        OPERACION,
        SUM(CANTIDAD) AS BULTOS,
        ALMACEN,
        SUM(PREMIO_NUEVO) AS PREMIO_X_HORAS,
        SUM(CASE WHEN TURNO = TURNOPROD THEN PREMIO_NUEVO ELSE 0 END) AS PREMIO_X_HORAS_SIN_EXTRAS,
        PRODUCTIVIDAD_ANTERIOR,
        PREMIO_ANTERIOR,
        SUM(DENTROTURNO) AS BULTOSTURNO
    FROM AGG A
    GROUP BY
        FECHA,
        OPERARIO,
        OPERACION,
        ALMACEN,
        PRODUCTIVIDAD_ANTERIOR,
        PREMIO_ANTERIOR
)
SELECT DISTINCT
    A.*,
    B.PREMIO_ACTUAL,
    PREMIO_ANTERIOR - PREMIO_X_HORAS AS DIFERENCIA_X_HORAS,
    PREMIO_ANTERIOR - PREMIO_ACTUAL AS DIFERENCIA_SIN_EXTRAS,
    PREMIO_ANTERIOR - PREMIO_X_HORAS_SIN_EXTRAS AS DIFERENCIA_X_HORAS_SIN_EXTRAS
FROM FINAL A
LEFT JOIN ESCALAS B
  ON B.GRUPOPRODUCTIVO = A.ALMACEN
 AND BULTOSTURNO >= DESDE_ACTUAL
 AND BULTOSTURNO < HASTA_ACTUAL
ORDER BY A.OPERARIO
"""

CONSULTA_CASO_MODELO_RANGO = """
WITH FECHA_PARAM AS (
    SELECT TO_DATE(:fecha_base, 'YYYY/MM/DD') AS FECHA_BASE
    FROM DUAL
),
PARAMS AS (
    SELECT
        FECHA_BASE,
        FECHA_BASE + (6 / 24) AS FECHA_DESDE,
        FECHA_BASE + 1 + (10.5 / 24) AS FECHA_HASTA,
        TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO
    FROM FECHA_PARAM
),
ESCALAS AS (
    SELECT
        D.DESCRIPCION AS OPERACION,
        D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA,
        F.DESCRIPCION AS GRUPOPRODUCTIVO,
        NIVEL,
        DESDE AS DESDE_ACTUAL,
        HASTA AS HASTA_ACTUAL,
        PREMIO AS PREMIO_ACTUAL,
        ROUND(DESDE/8, 0) AS DESDE_X_HORA,
        ROUND(HASTA/8, 0) AS HASTA_X_HORA,
        ROUND(PREMIO/8, 0) AS PREMIO_X_HORA
    FROM PV_ESCALA_DE_PREMIOS E
    JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
    JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID
    WHERE ID_DE_GRUPO_DE_FUNCIONES = 1
),
COMPARACION AS (
    SELECT
        A.FECHA,
        A.LEGAJO,
        D.DESCRIPCION AS OPERACION,
        C.PROD_REAL,
        C.PROD_REAL/8 AS PROD_REAL_X_HORA,
        B.A_PAGAR_TOTAL AS PREMIO_ANTERIOR_NETO,
        NVL(B.PENALIZACION_EXCESO_TNC, 0) AS DESCUENTO_TNC,
        NVL(B.PENALIZACION_POR_ERROR, 0) AS DESCUENTO_ERROR,
        NVL(B.PENALIZACION_EXCESO_TNC, 0)
          + NVL(B.PENALIZACION_POR_ERROR, 0) AS DESCUENTOS_TOTAL,
        B.A_PAGAR_TOTAL
          + NVL(B.PENALIZACION_EXCESO_TNC, 0)
          + NVL(B.PENALIZACION_POR_ERROR, 0) AS PREMIO_ANTERIOR_BRUTO,
        B.ID_PV_UNIDAD_DE_PRODUCCION,
        A.TURNO AS TURNOPROD
    FROM PV_DIA_LABORAL A
    JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL
    JOIN PV_LIQUIDAC_DIA_DET2 C ON A.ID = C.ID_PV_DIA_LABORAL AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES
    JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES
    JOIN PV_ESCALA_DE_PREMIOS E ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES AND C.ID_PV_GRUPO_PRODUCTIVO = E.ID_DE_GRUPO_PRODUCTIVO AND B.OBJETIVO_NIVEL_ALCANZADO = E.NIVEL
    JOIN PV_GRUPO_PRODUCTIVO_CAB F ON C.ID_PV_GRUPO_PRODUCTIVO = F.ID
    JOIN PARAMS param ON A.FECHA = PARAM.FECHA_PREMIO
    WHERE D.DESCRIPCION = :operacion
      AND CASE
            WHEN F.DESCRIPCION IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA'
            WHEN F.DESCRIPCION = 'CAMARA 06' THEN 'CAMARA 06'
            WHEN F.DESCRIPCION LIKE 'CAMARA%' THEN 'OTRAS CAMARAS'
            ELSE F.DESCRIPCION
          END = :almacen
),
F132_SOURCE AS (
    SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI
    FROM F132HIST A
    JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA
    WHERE COPECREA IN (SELECT LEGAJO FROM COMPARACION)
      AND (
          A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24)
          OR COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
      )
      AND UPPER(CDESCRIP) = :operacion
    UNION ALL
    SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI
    FROM F132HIST_HIST A
    JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA
    WHERE COPECREA IN (SELECT LEGAJO FROM COMPARACION)
      AND (
          A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24)
          OR COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
      )
      AND UPPER(CDESCRIP) = :operacion
      AND NOT EXISTS (
          SELECT 1
          FROM F132HIST X
          JOIN PARAMS P ON X.FCREAREG >= P.FECHA_DESDE AND X.FCREAREG <= P.FECHA_HASTA
          WHERE X.COPECREA IN (SELECT LEGAJO FROM COMPARACION)
            AND (
                X.FCREAREG <= P.FECHA_BASE + 1 + (6 / 24)
                OR X.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
            )
            AND UPPER(X.CDESCRIP) = :operacion
      )
),
TODO AS (
    SELECT
        TRUNC(FECHA_DESDE) AS FECHA,
        TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) AS HORA,
        CASE
            WHEN TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) >= 6 AND TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) < 14 THEN '1'
            WHEN TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) >= 14 AND TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) < 22 THEN '2'
            ELSE '3'
        END AS TURNO,
        COPECREA AS OPERARIO,
        UPPER(CDESCRIP) AS OPERACION,
        SUM(QCANTIDA) AS CANTIDAD,
        CASE
            WHEN SUB1.DESCDIVI IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA'
            WHEN SUB1.DESCDIVI = 'CAMARA 06' THEN 'CAMARA 06'
            WHEN SUB1.DESCDIVI LIKE 'CAMARA%' THEN 'OTRAS CAMARAS'
            ELSE SUB1.DESCDIVI
        END AS ALMACEN
    FROM F132_SOURCE A
    JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA
    LEFT JOIN (
        SELECT DISTINCT CZONALMA, DESCDIVI
        FROM VW_UBICACIONES_DIVISION
    ) SUB1 ON SUB1.CZONALMA = A.CZONAORI
    WHERE COPECREA IN (SELECT LEGAJO FROM COMPARACION)
      AND (
          A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24)
          OR COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
      )
      AND UPPER(CDESCRIP) = :operacion
    GROUP BY
        TRUNC(FECHA_DESDE),
        TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')),
        COPECREA,
        UPPER(CDESCRIP),
        CASE
            WHEN SUB1.DESCDIVI IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA'
            WHEN SUB1.DESCDIVI = 'CAMARA 06' THEN 'CAMARA 06'
            WHEN SUB1.DESCDIVI LIKE 'CAMARA%' THEN 'OTRAS CAMARAS'
            ELSE SUB1.DESCDIVI
        END
),
TODOPREMIO AS (
    SELECT
        A.*,
        B.DESDE_X_HORA,
        B.HASTA_X_HORA,
        ROUND(PREMIO_ACTUAL/8, 2) AS PREMIO_NUEVO
    FROM TODO A
    LEFT JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = A.ALMACEN
        AND CANTIDAD > DESDE_X_HORA
        AND CANTIDAD <= B.HASTA_X_HORA
),
AGG AS (
    SELECT
        A.*,
        B.TURNOPROD,
        B.PROD_REAL AS PRODUCTIVIDAD_ANTERIOR,
        B.PREMIO_ANTERIOR_NETO AS PREMIO_ANTERIOR,
        B.PREMIO_ANTERIOR_BRUTO,
        B.DESCUENTO_TNC,
        B.DESCUENTO_ERROR,
        B.DESCUENTOS_TOTAL,
        CASE WHEN TURNO = TURNOPROD THEN CANTIDAD ELSE 0 END AS DENTROTURNO
    FROM TODOPREMIO A
    JOIN COMPARACION B ON A.OPERARIO = B.LEGAJO
),
FINAL AS (
    SELECT
        FECHA,
        OPERARIO,
        OPERACION,
        SUM(CANTIDAD) AS BULTOS,
        ALMACEN,
        SUM(PREMIO_NUEVO) AS PREMIO_X_HORAS_BRUTO,
        SUM(CASE WHEN TURNO = TURNOPROD THEN PREMIO_NUEVO ELSE 0 END) AS PREMIO_X_HORAS_SIN_EXT_BRUTO,
        PRODUCTIVIDAD_ANTERIOR,
        PREMIO_ANTERIOR,
        PREMIO_ANTERIOR_BRUTO,
        DESCUENTO_TNC,
        DESCUENTO_ERROR,
        DESCUENTOS_TOTAL,
        SUM(DENTROTURNO) AS BULTOSTURNO
    FROM AGG A
    GROUP BY
        FECHA,
        OPERARIO,
        OPERACION,
        ALMACEN,
        PRODUCTIVIDAD_ANTERIOR,
        PREMIO_ANTERIOR,
        PREMIO_ANTERIOR_BRUTO,
        DESCUENTO_TNC,
        DESCUENTO_ERROR,
        DESCUENTOS_TOTAL
)
SELECT
    A.FECHA,
    A.OPERARIO,
    A.OPERACION,
    A.BULTOS,
    A.ALMACEN,
    GREATEST(A.PREMIO_X_HORAS_BRUTO - A.DESCUENTOS_TOTAL, 0) AS PREMIO_X_HORAS,
    A.PREMIO_X_HORAS_BRUTO,
    GREATEST(A.PREMIO_X_HORAS_SIN_EXT_BRUTO - A.DESCUENTOS_TOTAL, 0) AS PREMIO_X_HORAS_SIN_EXTRAS,
    A.PREMIO_X_HORAS_SIN_EXT_BRUTO AS PREMIO_X_HORAS_SIN_EXTRAS_BRUTO,
    A.PRODUCTIVIDAD_ANTERIOR,
    A.PREMIO_ANTERIOR,
    A.PREMIO_ANTERIOR_BRUTO,
    A.DESCUENTO_TNC,
    A.DESCUENTO_ERROR,
    A.DESCUENTOS_TOTAL,
    A.BULTOSTURNO,
    GREATEST(B.PREMIO_ACTUAL - A.DESCUENTOS_TOTAL, 0) AS PREMIO_ACTUAL,
    B.PREMIO_ACTUAL AS PREMIO_ACTUAL_BRUTO,
    PREMIO_ANTERIOR - GREATEST(A.PREMIO_X_HORAS_BRUTO - A.DESCUENTOS_TOTAL, 0) AS DIFERENCIA_X_HORAS,
    PREMIO_ANTERIOR - GREATEST(B.PREMIO_ACTUAL - A.DESCUENTOS_TOTAL, 0) AS DIFERENCIA_SIN_EXTRAS,
    PREMIO_ANTERIOR - GREATEST(A.PREMIO_X_HORAS_SIN_EXT_BRUTO - A.DESCUENTOS_TOTAL, 0) AS DIFERENCIA_X_HORAS_SIN_EXTRAS
FROM FINAL A
JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = A.ALMACEN
    AND BULTOSTURNO >= DESDE_ACTUAL
    AND BULTOSTURNO < HASTA_ACTUAL
ORDER BY A.FECHA, A.OPERARIO
"""

CONSULTA_CASO_MODELO_DETALLE = """
WITH FECHA_PARAM AS (
    SELECT TO_DATE(:fecha_base, 'YYYY/MM/DD') AS FECHA_BASE
    FROM DUAL
),
PARAMS AS (
    SELECT
        FECHA_BASE,
        FECHA_BASE + (6 / 24) AS FECHA_DESDE,
        FECHA_BASE + 1 + (10.5 / 24) AS FECHA_HASTA,
        TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO
    FROM FECHA_PARAM
),
ESCALAS AS (
    SELECT
        D.DESCRIPCION AS OPERACION,
        D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA,
        CASE
            WHEN F.DESCRIPCION IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA'
            WHEN F.DESCRIPCION = 'CAMARA 06' THEN 'CAMARA 06'
            WHEN F.DESCRIPCION LIKE 'CAMARA%' THEN 'OTRAS CAMARAS'
            ELSE F.DESCRIPCION
        END AS GRUPOPRODUCTIVO,
        NIVEL,
        DESDE AS DESDE_ACTUAL,
        HASTA AS HASTA_ACTUAL,
        PREMIO AS PREMIO_ACTUAL,
        ROUND(DESDE / 8, 0) AS DESDE_X_HORA,
        ROUND(HASTA / 8, 0) AS HASTA_X_HORA,
        ROUND(PREMIO / 8, 0) AS PREMIO_X_HORA
    FROM PV_ESCALA_DE_PREMIOS E
    JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
    JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID
    WHERE E.ID_DE_GRUPO_DE_FUNCIONES = 1
),
COMPARACION AS (
    SELECT
        A.FECHA,
        A.LEGAJO,
        D.DESCRIPCION AS OPERACION,
        C.PROD_REAL,
        C.PROD_REAL / 8 AS PROD_REAL_X_HORA,
        B.A_PAGAR_TOTAL,
        B.ID_PV_UNIDAD_DE_PRODUCCION,
        A.TURNO AS TURNOPROD,
        CASE
            WHEN B.PENALIZACION_EXCESO_TNC > 0 THEN 'PENALIZACION TNC'
            ELSE 'SIN PENALIZACION'
        END AS PENALIZACION_TNC,
        CASE
            WHEN B.PENALIZACION_POR_ERROR > 0 THEN 'PENALIZACION ERROR'
            ELSE ''
        END AS PENALIZACION_ERROR
    FROM PV_DIA_LABORAL A
    JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL
    JOIN PV_LIQUIDAC_DIA_DET2 C ON A.ID = C.ID_PV_DIA_LABORAL
        AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES
    JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES
    JOIN PV_ESCALA_DE_PREMIOS E ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
        AND C.ID_PV_GRUPO_PRODUCTIVO = E.ID_DE_GRUPO_PRODUCTIVO
        AND B.OBJETIVO_NIVEL_ALCANZADO = E.NIVEL
    JOIN PV_GRUPO_PRODUCTIVO_CAB F ON C.ID_PV_GRUPO_PRODUCTIVO = F.ID
    JOIN PARAMS PARAM ON A.FECHA = PARAM.FECHA_PREMIO
    WHERE D.DESCRIPCION = :operacion
      AND CASE
            WHEN F.DESCRIPCION IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA'
            WHEN F.DESCRIPCION = 'CAMARA 06' THEN 'CAMARA 06'
            WHEN F.DESCRIPCION LIKE 'CAMARA%' THEN 'OTRAS CAMARAS'
            ELSE F.DESCRIPCION
          END = :almacen
      AND A.LEGAJO = :legajo
),
F132_SOURCE AS (
    SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI
    FROM F132HIST A
    JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA
    WHERE A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION)
      AND (
          A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24)
          OR A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
      )
      AND UPPER(A.CDESCRIP) = :operacion
    UNION ALL
    SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI
    FROM F132HIST_HIST A
    JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA
    WHERE A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION)
      AND (
          A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24)
          OR A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
      )
      AND UPPER(A.CDESCRIP) = :operacion
      AND NOT EXISTS (
          SELECT 1
          FROM F132HIST X
          JOIN PARAMS P ON X.FCREAREG >= P.FECHA_DESDE AND X.FCREAREG <= P.FECHA_HASTA
          WHERE X.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION)
            AND (
                X.FCREAREG <= P.FECHA_BASE + 1 + (6 / 24)
                OR X.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
            )
            AND UPPER(X.CDESCRIP) = :operacion
      )
),
TODO AS (
    SELECT
        TRUNC(B.FECHA_DESDE) AS FECHA,
        TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) AS HORA,
        CASE
            WHEN TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) >= 6 AND TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) < 14 THEN '1'
            WHEN TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) >= 14 AND TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) < 22 THEN '2'
            ELSE '3'
        END AS TURNO,
        A.COPECREA AS OPERARIO,
        UPPER(A.CDESCRIP) AS OPERACION,
        SUM(A.QCANTIDA) AS CANTIDAD,
        CASE
            WHEN SUB1.DESCDIVI IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA'
            WHEN SUB1.DESCDIVI = 'CAMARA 06' THEN 'CAMARA 06'
            WHEN SUB1.DESCDIVI LIKE 'CAMARA%' THEN 'OTRAS CAMARAS'
            ELSE SUB1.DESCDIVI
        END AS ALMACEN
    FROM F132_SOURCE A
    JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA
    LEFT JOIN (
        SELECT DISTINCT CZONALMA, DESCDIVI
        FROM VW_UBICACIONES_DIVISION
    ) SUB1 ON SUB1.CZONALMA = A.CZONAORI
    WHERE A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION)
      AND (
          A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24)
          OR A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
      )
      AND UPPER(A.CDESCRIP) = :operacion
    GROUP BY
        TRUNC(B.FECHA_DESDE),
        TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')),
        A.COPECREA,
        UPPER(A.CDESCRIP),
        CASE
            WHEN SUB1.DESCDIVI IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA'
            WHEN SUB1.DESCDIVI = 'CAMARA 06' THEN 'CAMARA 06'
            WHEN SUB1.DESCDIVI LIKE 'CAMARA%' THEN 'OTRAS CAMARAS'
            ELSE SUB1.DESCDIVI
        END
),
TODOPREMIO AS (
    SELECT
        A.*,
        B.DESDE_X_HORA,
        B.HASTA_X_HORA,
        ROUND(B.PREMIO_ACTUAL / 8, 2) AS PREMIO_NUEVO
    FROM TODO A
    LEFT JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = A.ALMACEN
        AND A.CANTIDAD > B.DESDE_X_HORA
        AND A.CANTIDAD <= B.HASTA_X_HORA
),
AGG AS (
    SELECT
        A.*,
        B.TURNOPROD,
        B.PROD_REAL AS PRODUCTIVIDAD_ANTERIOR,
        B.A_PAGAR_TOTAL AS PREMIO_ANTERIOR,
        CASE
            WHEN A.TURNO = B.TURNOPROD THEN A.CANTIDAD
            ELSE 0
        END AS DENTROTURNO,
        B.PENALIZACION_TNC,
        B.PENALIZACION_ERROR
    FROM TODOPREMIO A
    JOIN COMPARACION B ON TO_CHAR(A.OPERARIO) = TO_CHAR(B.LEGAJO)
),
AGG2 AS (
SELECT
    A.FECHA,
    A.HORA,
    CASE A.TURNO WHEN '1' THEN 'MAÑANA' WHEN '2' THEN 'TARDE' ELSE 'NOCHE' END AS TURNO,
    A.OPERARIO,
    B.NOMBRE,
    A.OPERACION,
    A.CANTIDAD AS BULTOS,
    A.ALMACEN,
    A.DESDE_X_HORA AS BULTOS_HORA_MIN,
    A.HASTA_X_HORA AS BULTOS_HORA_MAX,
    A.PREMIO_NUEVO AS PREMIO_X_HORA,
    A.PRODUCTIVIDAD_ANTERIOR AS PROD_MODULO,
    A.PREMIO_ANTERIOR AS PAGO_MODULO,
    A.DENTROTURNO AS BULTOS_MODULO,
    A.PENALIZACION_TNC,
    A.PENALIZACION_ERROR,
    SUM(A.DENTROTURNO) OVER (PARTITION BY A.OPERARIO) AS BULTOSTURNO
FROM AGG A
JOIN PV_LEGAJO B ON A.OPERARIO = B.LEGAJO
)
SELECT
    A.*,
    B.PREMIO_ACTUAL AS PREMIO_SIN_EXTRA
FROM AGG2 A
JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = A.ALMACEN
    AND BULTOSTURNO >= DESDE_ACTUAL
    AND BULTOSTURNO < HASTA_ACTUAL
ORDER BY A.HORA
"""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pp_caso_modelo_dia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_base DATE NOT NULL,
    operacion TEXT NOT NULL DEFAULT 'PICKING',
    query_version TEXT NOT NULL,
    fecha DATE,
    operario TEXT,
    bultos REAL NOT NULL DEFAULT 0,
    almacen TEXT,
    premio_x_horas REAL NOT NULL DEFAULT 0,
    productividad_anterior REAL NOT NULL DEFAULT 0,
    premio_anterior REAL NOT NULL DEFAULT 0,
    bultosturno REAL NOT NULL DEFAULT 0,
    premio_actual REAL NOT NULL DEFAULT 0,
    premio_actual_bruto REAL NOT NULL DEFAULT 0,
    premio_x_horas_sin_extras REAL NOT NULL DEFAULT 0,
    premio_x_horas_bruto REAL NOT NULL DEFAULT 0,
    premio_x_horas_sin_extras_bruto REAL NOT NULL DEFAULT 0,
    premio_anterior_bruto REAL NOT NULL DEFAULT 0,
    descuento_tnc REAL NOT NULL DEFAULT 0,
    descuento_error REAL NOT NULL DEFAULT 0,
    descuentos_total REAL NOT NULL DEFAULT 0,
    diferencia_x_horas REAL NOT NULL DEFAULT 0,
    diferencia_sin_extras REAL NOT NULL DEFAULT 0,
    diferencia_x_horas_sin_extras REAL NOT NULL DEFAULT 0,
    loaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pp_caso_modelo_detalle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_base DATE NOT NULL,
    legajo TEXT NOT NULL,
    query_version TEXT NOT NULL,
    fecha DATE,
    hora INTEGER,
    turno TEXT,
    operario TEXT,
    nombre TEXT,
    operacion TEXT,
    bultos REAL NOT NULL DEFAULT 0,
    almacen TEXT,
    bultos_hora_min REAL,
    bultos_hora_max REAL,
    premio_x_hora REAL NOT NULL DEFAULT 0,
    prod_modulo REAL NOT NULL DEFAULT 0,
    pago_modulo REAL NOT NULL DEFAULT 0,
    bultos_modulo REAL NOT NULL DEFAULT 0,
    bultosturno REAL NOT NULL DEFAULT 0,
    premio_sin_extra REAL NOT NULL DEFAULT 0,
    penalizacion_tnc TEXT NOT NULL DEFAULT '',
    penalizacion_error TEXT NOT NULL DEFAULT '',
    loaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pp_caso_dia ON pp_caso_modelo_dia(fecha_base, operacion, almacen, query_version);
CREATE INDEX IF NOT EXISTS idx_pp_caso_detalle ON pp_caso_modelo_detalle(fecha_base, operacion, almacen, legajo, query_version);
"""


class RangoCasoModeloRequest(BaseModel):
    fecha_desde: str
    fecha_hasta: str
    force: bool = False
    operacion: str = DEFAULT_OPERACION
    almacen: str = DEFAULT_ALMACEN
    divisor_horario: float = JORNADA_HORAS


class GifExportRequest(BaseModel):
    frames: list[str]
    duration_ms: int = 90
    filename: str = "detalle-impacto-extras.gif"


class ExplicacionPremioRequest(BaseModel):
    fecha_desde: str
    fecha_hasta: str
    operacion: str = DEFAULT_OPERACION
    almacen: str = DEFAULT_ALMACEN
    provider: str | None = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _upper(value: Any) -> str:
    return _clean(value).upper()


def _normalize_operacion(value: Any) -> str:
    raw = value if isinstance(value, str) else DEFAULT_OPERACION
    operacion = _upper(raw or DEFAULT_OPERACION)
    if operacion not in OPERACIONES_PREMIO_PRODUCTIVIDAD:
        raise HTTPException(status_code=400, detail=f"Operacion no soportada: {operacion}.")
    return operacion


def _normalize_almacen(value: Any) -> str:
    raw = value if isinstance(value, str) else DEFAULT_ALMACEN
    almacen = _upper(raw or DEFAULT_ALMACEN)
    if almacen in {"", "ALL", "TODO", "TODOS"}:
        return DEFAULT_ALMACEN
    if almacen in {"SECOS+NOA", "SECOS NOA", "SECTOR SECOS", "VARIOS NO ALIMENTOS"}:
        almacen = "SECOS + NOA"
    if almacen in {"AREA SECOS Y NO ALIMENTOS", "AREA SECOS Y NO ALIMENTOS "}:
        almacen = "AREA SECOS Y NO ALIMENTOS"
    if almacen not in ALMACENES_PREMIO_PRODUCTIVIDAD:
        raise HTTPException(status_code=400, detail=f"Almacen no soportado: {almacen}.")
    return almacen


def _normalize_grupo_productivo(value: Any) -> str:
    grupo = _upper(value)
    if grupo in {"SECOS+NOA", "SECOS NOA", "SECTOR SECOS", "VARIOS NO ALIMENTOS"}:
        return "SECOS + NOA"
    if grupo in {"AREA SECOS Y NO ALIMENTOS", "AREA SECOS Y NO ALIMENTOS "}:
        return "AREA SECOS Y NO ALIMENTOS"
    if grupo == "CAMARA 06":
        return "CAMARA 06"
    if grupo.startswith("CAMARA"):
        return "OTRAS CAMARAS"
    return grupo


def _matches_almacen_filter(grupo: str, almacen: str) -> bool:
    return almacen == DEFAULT_ALMACEN or _normalize_grupo_productivo(grupo) == almacen


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _param_float(value: Any, default: float) -> float:
    return _num(value if isinstance(value, (str, int, float, Decimal)) else default, default)


def _param_int(value: Any, default: int) -> int:
    return int(_param_float(value, float(default)))


def _param_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "si", "s"}
    return default


def _oracle_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _to_date(value: str) -> date:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Fecha invalida: {value}")


def _date_range_inclusive(fecha_desde: str, fecha_hasta: str) -> list[date]:
    start = _to_date(fecha_desde)
    end = _to_date(fecha_hasta)
    max_day = date.today() - timedelta(days=1)
    if start > max_day or end > max_day:
        raise HTTPException(
            status_code=400,
            detail=f"La fecha maxima permitida es {max_day.isoformat()}. No se puede consultar el dia actual ni futuro.",
        )
    if end < start:
        raise HTTPException(status_code=400, detail="La fecha hasta no puede ser menor a la fecha desde.")
    days = (end - start).days
    if days > 60:
        raise HTTPException(status_code=400, detail="El rango maximo permitido es de 61 dias por consulta.")
    return [start + timedelta(days=i) for i in range(days + 1)]


def _expand_in_binds(sql: str, binds: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    expanded = dict(binds)
    for key, value in list(binds.items()):
        if not isinstance(value, (list, tuple, set)):
            continue
        values = list(value)
        if not values:
            values = ["__SIN_LEGAJOS__"]
        names = []
        for index, item in enumerate(values):
            name = f"{key}_{index}"
            names.append(f":{name}")
            expanded[name] = item
        expanded.pop(key, None)
        sql = sql.replace(f":{key}", ", ".join(names))
    return sql, expanded


def _oracle_connect():
    if os.getenv("PRODUCTIVE_DB_LOCAL_ONLY", "").strip().lower() in {"1", "true", "yes", "si"}:
        raise RuntimeError("La BD productiva Oracle esta bloqueada por PRODUCTIVE_DB_LOCAL_ONLY.")
    try:
        import oracledb
    except ImportError as exc:
        raise RuntimeError("Falta instalar la dependencia 'oracledb'.") from exc

    user = os.getenv("PRODUCTIVE_DB_USER", "").strip()
    password = os.getenv("PRODUCTIVE_DB_PASSWORD", "").strip()
    host = os.getenv("PRODUCTIVE_DB_HOST", "").strip()
    port = os.getenv("PRODUCTIVE_DB_PORT", "1521").strip()
    service_name = os.getenv("PRODUCTIVE_DB_SERVICE_NAME", "").strip()
    dsn = os.getenv("PRODUCTIVE_DB_DSN", "").strip()
    if not dsn and not all([host, port, service_name]):
        raise RuntimeError("Faltan PRODUCTIVE_DB_HOST/PORT/SERVICE_NAME o PRODUCTIVE_DB_DSN.")
    if not all([user, password]):
        raise RuntimeError("Faltan PRODUCTIVE_DB_USER o PRODUCTIVE_DB_PASSWORD.")
    if not dsn:
        dsn = oracledb.makedsn(host=host, port=int(port), service_name=service_name)

    client_lib_dir = os.getenv("PRODUCTIVE_DB_CLIENT_LIB_DIR", "").strip()
    if client_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=client_lib_dir)
        except Exception as exc:
            msg = str(exc)
            if "already been initialized" not in msg:
                raise RuntimeError(f"No se pudo inicializar Oracle Client en {client_lib_dir}: {msg}") from exc
    return oracledb.connect(user=user, password=password, dsn=dsn)


def _query_oracle(sql: str, binds: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if os.getenv("PRODUCTIVE_DB_USE_JDBC", "1").strip().lower() in {"1", "true", "yes", "si"}:
        return _query_oracle_via_jdbc(sql, binds or {})
    query, query_binds = _expand_in_binds(sql, binds or {})
    connection = _oracle_connect()
    try:
        cursor = connection.cursor()
        cursor.execute(query, query_binds)
        columns = [str(col[0]).upper() for col in cursor.description or []]
        rows = []
        for raw in cursor.fetchall():
            rows.append({columns[index]: _oracle_value(value) for index, value in enumerate(raw)})
        return rows
    finally:
        connection.close()


def _ensure_java_helper_compiled() -> None:
    JAVA_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    class_file = JAVA_BUILD_DIR / "OracleProductividadQuery.class"
    if class_file.exists() and class_file.stat().st_mtime >= JAVA_HELPER_SRC.stat().st_mtime:
        return
    javac_bin = os.getenv(
        "PRODUCTIVE_DB_JAVAC_BIN",
        r"C:\Program Files\Android\openjdk\jdk-21.0.8\bin\javac.exe",
    ).strip()
    result = subprocess.run(
        [javac_bin, "-d", str(JAVA_BUILD_DIR), str(JAVA_HELPER_SRC)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"No se pudo compilar helper JDBC: {result.stderr[:500]}")


def _query_oracle_via_jdbc(sql: str, binds: dict[str, Any]) -> list[dict[str, Any]]:
    user = os.getenv("PRODUCTIVE_DB_USER", "").strip()
    password = os.getenv("PRODUCTIVE_DB_PASSWORD", "").strip()
    host = os.getenv("PRODUCTIVE_DB_HOST", "").strip()
    port = os.getenv("PRODUCTIVE_DB_PORT", "1521").strip()
    service_name = os.getenv("PRODUCTIVE_DB_SERVICE_NAME", "").strip()
    java_bin = os.getenv("PRODUCTIVE_DB_JAVA_BIN", r"C:\Users\207189\AppData\Local\DBeaver\jre\bin\java.exe").strip()
    ojdbc_jar = os.getenv(
        "PRODUCTIVE_DB_OJDBC_JAR",
        r"C:\Users\207189\AppData\Roaming\DBeaverData\drivers\maven\maven-central\com.oracle.database.jdbc\ojdbc11-23.2.0.0.jar",
    ).strip()
    if not all([user, password, host, service_name]):
        raise RuntimeError("Faltan variables JDBC PRODUCTIVE_DB_USER/PASSWORD/HOST/SERVICE_NAME.")
    if not Path(java_bin).exists():
        raise RuntimeError(f"No se encontro Java para JDBC: {java_bin}")
    if not Path(ojdbc_jar).exists():
        raise RuntimeError(f"No se encontro driver JDBC Oracle: {ojdbc_jar}")

    normalized = " ".join(sql.upper().split())
    if "PP_PREMIO_ESCALAS" in normalized:
        query_key = "pp_premio_escalas"
    elif "PP_PREMIO_ETAPAS_HORA" in normalized:
        query_key = "pp_premio_etapas_hora"
    elif "PP_PREMIO_LIQUIDACION_DIA" in normalized:
        query_key = "pp_premio_liquidacion_dia"
    elif "BULTOS_HORA_MIN" in normalized and "BULTOSTURNO" in normalized:
        query_key = "premio_caso_modelo_detalle"
    elif "FECHA_PARAM" in normalized and "DIFERENCIA_SIN_EXTRAS" in normalized:
        query_key = "premio_caso_modelo_rango"
    elif "TODOPREMIO" in normalized and "DIFERENCIA_SIN_EXTRAS" in normalized:
        query_key = "premio_caso_modelo_final"
    elif "PV_LIQUIDAC_DIA_DET1" in normalized:
        query_key = "premio_pago_actual"
    elif "F132HIST" in normalized and "SUM(QCANTIDA) AS CANTIDAD" in normalized:
        query_key = "premio_produccion_hora"
    elif "PV_ESCALA_DE_PREMIOS" in normalized:
        query_key = "premio_escala"
    else:
        raise RuntimeError("Consulta premio productividad no soportada por helper JDBC.")

    _ensure_java_helper_compiled()
    jdbc_url = f"jdbc:oracle:thin:@//{host}:{port}/{service_name}"
    classpath = os.pathsep.join([str(JAVA_BUILD_DIR), ojdbc_jar])
    legajos = ",".join(str(x) for x in binds.get("legajos", []))
    command = [
        java_bin,
        "-cp",
        classpath,
        "OracleProductividadQuery",
        jdbc_url,
        user,
        password,
        str(binds.get("fecha_ini") or binds.get("fecha_yyyymmdd") or ""),
        str(binds.get("fecha_fin") or binds.get("fecha_yyyymmdd") or ""),
        query_key,
        legajos,
        str(binds.get("operacion") or "PICKING"),
        str(binds.get("nivel") or ""),
        str(binds.get("grupo_funciones_id") or 1),
        str(binds.get("fecha_operativa") or binds.get("fecha_base") or ""),
        str(binds.get("legajo") or ""),
        str(binds.get("almacen") or DEFAULT_ALMACEN),
    ]
    timeout_seconds = int(os.getenv("PRODUCTIVE_DB_JDBC_TIMEOUT_SECONDS", "90"))
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Timeout consultando Oracle por JDBC luego de {timeout_seconds}s "
            f"para {query_key}."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(f"Error consultando Oracle por JDBC: {result.stderr[:800]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"La respuesta JDBC no fue JSON valido. Salida: {result.stdout[:300]}") from exc


async def init_premio_productividad_db() -> None:
    PREMIO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await _ensure_columns(db)
        await db.commit()


async def _ensure_columns(db: aiosqlite.Connection) -> None:
    additions = {
        "pp_caso_modelo_detalle": [
            ("premio_sin_extra", "REAL NOT NULL DEFAULT 0"),
            ("penalizacion_tnc", "TEXT NOT NULL DEFAULT ''"),
            ("penalizacion_error", "TEXT NOT NULL DEFAULT ''"),
        ],
        "pp_caso_modelo_dia": [
            ("premio_x_horas_sin_extras", "REAL NOT NULL DEFAULT 0"),
            ("premio_actual_bruto", "REAL NOT NULL DEFAULT 0"),
            ("premio_x_horas_bruto", "REAL NOT NULL DEFAULT 0"),
            ("premio_x_horas_sin_extras_bruto", "REAL NOT NULL DEFAULT 0"),
            ("premio_anterior_bruto", "REAL NOT NULL DEFAULT 0"),
            ("descuento_tnc", "REAL NOT NULL DEFAULT 0"),
            ("descuento_error", "REAL NOT NULL DEFAULT 0"),
            ("descuentos_total", "REAL NOT NULL DEFAULT 0"),
            ("diferencia_x_horas_sin_extras", "REAL NOT NULL DEFAULT 0"),
        ],
    }
    for table, columns in additions.items():
        async with db.execute(f"PRAGMA table_info({table})") as cur:
            existing = {row[1] for row in await cur.fetchall()}
        for name, definition in columns:
            if name not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


async def _fetch_rows(db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    async with db.execute(sql, args) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def _fetch_one(db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    async with db.execute(sql, args) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


def _date_range(fecha_desde: str, fecha_hasta: str) -> list[str]:
    start = _to_date(fecha_desde)
    end = _to_date(fecha_hasta)
    if end < start:
        raise HTTPException(status_code=400, detail="Fecha hasta no puede ser menor a fecha desde.")
    days = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _within_shift(hora: int, turno: str) -> bool:
    turno = _upper(turno)
    if turno in {"MANANA", "MAÑANA", "MAÃ±ANA"}:
        return 6 <= hora < 14
    if turno == "TARDE":
        return 14 <= hora < 22
    if turno == "NOCHE":
        return hora >= 22 or hora < 6
    return False


def _tipo_hora(hora: int, turno: str) -> str:
    turno = _upper(turno)
    if not turno:
        return "SIN_TURNO"
    if _within_shift(hora, turno):
        return "NORMAL"
    if turno in {"MANANA", "MAÑANA", "MAÃ±ANA"}:
        return "FUERA_TURNO_ANTES" if hora < 6 else "FUERA_TURNO_DESPUES"
    if turno == "TARDE":
        return "FUERA_TURNO_ANTES" if hora < 14 else "FUERA_TURNO_DESPUES"
    if turno == "NOCHE":
        return "FUERA_TURNO_DESPUES" if hora == 6 else "FUERA_TURNO_ANTES"
    return "SIN_TURNO"


def _turno_code(value: Any) -> str:
    text = _upper(value)
    if text in {"1", "TM", "MANANA", "MAÃ‘ANA", "MAÑANA"}:
        return "1"
    if text in {"2", "TT", "TARDE"}:
        return "2"
    if text in {"3", "TN", "NOCHE"}:
        return "3"
    return text


def _hora_en_turno(hora: int, turno: Any) -> bool:
    code = _turno_code(turno)
    if code == "1":
        return 6 <= hora < 14
    if code == "2":
        return 14 <= hora < 22
    if code == "3":
        return hora >= 22 or hora < 6
    return False


def _scale_key(row: dict[str, Any]) -> tuple[str, int, int]:
    return (
        _upper(row.get("OPERACION") or row.get("operacion")),
        int(_num(row.get("ID_DE_GRUPO_DE_FUNCIONES") or row.get("ID_PV_GRUPO_DE_FUNCIONES_CAB"))),
        int(_num(row.get("ID_DE_GRUPO_PRODUCTIVO") or row.get("ID_PV_GRUPO_PRODUCTIVO"))),
    )


def _build_scale_index(rows: list[dict[str, Any]]) -> dict[tuple[str, int, int], list[dict[str, Any]]]:
    index: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = {
            "operacion": _upper(row.get("OPERACION")),
            "grupo_productivo": _normalize_grupo_productivo(row.get("GRUPOPRODUCTIVO")),
            "nivel": int(_num(row.get("NIVEL"))),
            "desde_actual": _num(row.get("DESDE_ACTUAL")),
            "hasta_actual": _num(row.get("HASTA_ACTUAL")),
            "premio_actual": _num(row.get("PREMIO_ACTUAL")),
            "desde_x_hora": _num(row.get("DESDE_X_HORA")),
            "hasta_x_hora": _num(row.get("HASTA_X_HORA")),
            "premio_x_hora": _num(row.get("PREMIO_X_HORA")),
            "id_grupo_productivo": int(_num(row.get("ID_DE_GRUPO_PRODUCTIVO"))),
            "id_grupo_funciones": int(_num(row.get("ID_DE_GRUPO_DE_FUNCIONES"))),
        }
        index[(item["operacion"], item["id_grupo_funciones"], item["id_grupo_productivo"])].append(item)
    for key in index:
        index[key].sort(key=lambda item: (item["desde_actual"], item["hasta_actual"], item["nivel"]))
    return index


def _find_scale(
    scales: dict[tuple[str, int, int], list[dict[str, Any]]],
    operacion: str,
    id_funciones: int,
    id_grupo: int,
    value: float,
    hourly: bool = False,
) -> dict[str, Any] | None:
    rows = scales.get((_upper(operacion), int(id_funciones), int(id_grupo)), [])
    desde_key = "desde_x_hora" if hourly else "desde_actual"
    hasta_key = "hasta_x_hora" if hourly else "hasta_actual"
    candidates = [float(value or 0)]
    if not hourly:
        rounded = float(round(float(value or 0), 0))
        if rounded not in candidates:
            candidates.append(rounded)
    for candidate in candidates:
        for row in rows:
            low = float(row.get(desde_key) or 0)
            high = float(row.get(hasta_key) or 0)
            if candidate > low and candidate < high:
                return row
            if not hourly and candidate >= low and candidate <= high:
                return row
    return None


def _day_key_from_row(row: dict[str, Any]) -> tuple[str, str, int, int]:
    return (
        str(row.get("LEGAJO") or "").strip(),
        _upper(row.get("OPERACION")),
        int(_num(row.get("ID_PV_GRUPO_DE_FUNCIONES_CAB"))),
        int(_num(row.get("ID_PV_GRUPO_PRODUCTIVO"))),
    )


async def _fetch_premio_base(fecha_base: str, operacion: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, int, int], list[dict[str, Any]]]]:
    binds = {"fecha_base": _to_date(fecha_base).strftime("%Y/%m/%d"), "operacion": operacion}
    if os.getenv("PRODUCTIVE_DB_USE_JDBC", "1").strip().lower() in {"1", "true", "yes", "si"}:
        await asyncio.to_thread(_ensure_java_helper_compiled)
    raw_scales, raw_hours, raw_days = await asyncio.gather(
        asyncio.to_thread(_query_oracle, CONSULTA_PP_ESCALAS, {"operacion": operacion}),
        asyncio.to_thread(_query_oracle, CONSULTA_PP_ETAPAS_HORA, binds),
        asyncio.to_thread(_query_oracle, CONSULTA_PP_LIQUIDACION_DIA, binds),
    )
    return raw_hours, raw_days, _build_scale_index(raw_scales)


def _simulate_premio_rows(
    fecha_base: str,
    operacion: str,
    almacen: str,
    hour_rows: list[dict[str, Any]],
    day_rows: list[dict[str, Any]],
    scales: dict[tuple[str, int, int], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    detail_by_key: dict[tuple[str, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in hour_rows:
        grupo = _normalize_grupo_productivo(row.get("GRUPO_PRODUCTIVO"))
        if not _matches_almacen_filter(grupo, almacen):
            continue
        legajo = str(row.get("LEGAJO") or "").strip()
        id_funciones = int(_num(row.get("ID_PV_GRUPO_DE_FUNCIONES_CAB")))
        id_grupo = int(_num(row.get("ID_PV_GRUPO_PRODUCTIVO")))
        prod_final = _num(row.get("PROD_FINAL"))
        scale = _find_scale(scales, operacion, id_funciones, id_grupo, prod_final, hourly=True) or {}
        hora = int(_num(row.get("HORA")))
        turno = _turno_code(row.get("TURNO"))
        dentro = _hora_en_turno(hora, turno)
        key = (legajo, _upper(row.get("OPERACION") or operacion), id_funciones, id_grupo)
        detail_by_key[key].append({
            "fecha": fecha_base,
            "hora": hora,
            "turno": turno,
            "operario": legajo,
            "nombre": "",
            "operacion": _upper(row.get("OPERACION") or operacion),
            "bultos": prod_final,
            "almacen": grupo,
            "bultos_hora_min": _num(scale.get("desde_x_hora")),
            "bultos_hora_max": _num(scale.get("hasta_x_hora")),
            "premio_x_hora": _num(scale.get("premio_x_hora")),
            "prod_real": _num(row.get("PROD_REAL")),
            "prod_equiv_sector": _num(row.get("PROD_EQUIV_SECTOR")),
            "prod_traslado": _num(row.get("PROD_TRASLADO")),
            "prod_consolidacion": _num(row.get("PROD_CONSOLIDACION")),
            "bultos_modulo": prod_final if dentro else 0.0,
            "es_extra": 0 if dentro else 1,
            "id_pv_dia_laboral": int(_num(row.get("ID_PV_DIA_LABORAL"))),
            "id_grupo_productivo": id_grupo,
            "id_grupo_funciones": id_funciones,
        })

    daily_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    for day in day_rows:
        grupo = _normalize_grupo_productivo(day.get("GRUPO_PRODUCTIVO"))
        if not _matches_almacen_filter(grupo, almacen):
            continue
        legajo = str(day.get("LEGAJO") or "").strip()
        id_funciones = int(_num(day.get("ID_PV_GRUPO_DE_FUNCIONES_CAB")))
        id_grupo = int(_num(day.get("ID_PV_GRUPO_PRODUCTIVO")))
        key = (legajo, _upper(day.get("OPERACION") or operacion), id_funciones, id_grupo)
        details = sorted(detail_by_key.get(key, []), key=lambda item: item["hora"])

        prod_final = _num(day.get("PROD_FINAL"))
        premio_pagado = round(_num(day.get("PREMIO")), 0)
        scale_diaria = _find_scale(scales, operacion, id_funciones, id_grupo, prod_final, hourly=False)
        premio_actual_bruto = _num((scale_diaria or {}).get("premio_actual"))
        if not scale_diaria and premio_pagado > 0:
            premio_actual_bruto = premio_pagado
        descuento_monetario = max(premio_actual_bruto - premio_pagado, 0.0)
        bultosturno = round(sum(float(item["bultos_modulo"]) for item in details), 3)
        premio_x_horas_bruto = round(sum(float(item["premio_x_hora"]) for item in details), 2)
        premio_x_horas_sin_extras_bruto = round(
            sum(float(item["premio_x_hora"]) for item in details if not item["es_extra"]),
            2,
        )
        scale_sin_extras = _find_scale(scales, operacion, id_funciones, id_grupo, bultosturno, hourly=False)
        if not scale_sin_extras and abs(bultosturno - prod_final) <= 0.01:
            scale_sin_extras = scale_diaria
        premio_actual_sin_extras_bruto = _num((scale_sin_extras or {}).get("premio_actual"))
        if not scale_sin_extras and abs(bultosturno - prod_final) <= 0.01 and premio_pagado > 0:
            premio_actual_sin_extras_bruto = premio_pagado + descuento_monetario

        premio_x_horas = round(premio_x_horas_bruto - descuento_monetario, 2)
        premio_x_horas_sin_extras = round(premio_x_horas_sin_extras_bruto - descuento_monetario, 2)
        premio_actual_sin_extras = round(premio_actual_sin_extras_bruto - descuento_monetario, 2)
        if abs(bultosturno - prod_final) <= 0.01:
            premio_actual_sin_extras = premio_pagado
            premio_actual_sin_extras_bruto = premio_pagado + descuento_monetario

        for item in details:
            item["prod_modulo"] = prod_final
            item["pago_modulo"] = premio_pagado
            item["bultosturno"] = bultosturno
            item["premio_sin_extra"] = premio_actual_sin_extras
            item["penalizacion_tnc"] = _num(day.get("PENA_TNC"))
            item["penalizacion_error"] = _num(day.get("PENA_ERROR"))
            detail_rows.append(item)

        daily_rows.append({
            "fecha": fecha_base,
            "operario": legajo,
            "operacion": _upper(day.get("OPERACION") or operacion),
            "bultos": prod_final,
            "almacen": grupo,
            "premio_x_horas": premio_x_horas,
            "premio_x_horas_bruto": premio_x_horas_bruto,
            "premio_x_horas_sin_extras": premio_x_horas_sin_extras,
            "premio_x_horas_sin_extras_bruto": premio_x_horas_sin_extras_bruto,
            "productividad_anterior": prod_final,
            "premio_anterior": premio_pagado,
            "premio_anterior_bruto": premio_actual_bruto,
            "descuento_tnc": _num(day.get("PENA_TNC")),
            "descuento_error": _num(day.get("PENA_ERROR")),
            "descuentos_total": round(descuento_monetario, 2),
            "bultosturno": bultosturno,
            "premio_actual": premio_actual_sin_extras,
            "premio_actual_bruto": premio_actual_sin_extras_bruto,
            "diferencia_x_horas": round(premio_pagado - premio_x_horas, 2),
            "diferencia_sin_extras": round(premio_pagado - premio_actual_sin_extras, 2),
            "diferencia_x_horas_sin_extras": round(premio_pagado - premio_x_horas_sin_extras, 2),
        })
    return daily_rows, detail_rows


async def obtenerCasoModeloFinal(params: dict[str, Any]) -> list[dict[str, Any]]:
    operacion = _normalize_operacion(params.get("operacion"))
    almacen = _normalize_almacen(params.get("almacen"))
    fecha_base = _to_date(params["fecha_desde"]).isoformat()
    hour_rows, day_rows, scales = await _fetch_premio_base(fecha_base, operacion)
    rows, _ = _simulate_premio_rows(fecha_base, operacion, almacen, hour_rows, day_rows, scales)
    return rows


async def _cache_rows_for_range(
    db: aiosqlite.Connection,
    fecha_desde: str,
    fecha_hasta: str,
    operacion: str,
    almacen: str,
) -> list[dict[str, Any]]:
    return await _fetch_rows(
        db,
        """
        SELECT fecha, operario, operacion, bultos, almacen, premio_x_horas,
               premio_x_horas_sin_extras, premio_x_horas_bruto,
               premio_x_horas_sin_extras_bruto,
               productividad_anterior, premio_anterior, premio_anterior_bruto,
               descuento_tnc, descuento_error, descuentos_total,
               bultosturno, premio_actual, premio_actual_bruto,
               diferencia_x_horas, diferencia_sin_extras, diferencia_x_horas_sin_extras
        FROM pp_caso_modelo_dia
        WHERE fecha_base >= ?
          AND fecha_base <= ?
          AND operacion = ?
          AND (? = 'TODOS' OR almacen = ?)
          AND query_version = ?
        ORDER BY fecha_base, operario
        """,
        (fecha_desde, fecha_hasta, operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION),
    )


async def _detail_rows_for_range_internal(
    db: aiosqlite.Connection,
    fecha_desde: str,
    fecha_hasta: str,
    operacion: str,
    almacen: str,
) -> list[dict[str, Any]]:
    return await _fetch_rows(
        db,
        """
        SELECT fecha_base, legajo, fecha, hora, turno, operario, nombre, operacion,
               bultos, almacen, bultos_hora_min, bultos_hora_max, premio_x_hora,
               prod_modulo, pago_modulo, bultos_modulo, bultosturno,
               premio_sin_extra, penalizacion_tnc, penalizacion_error, loaded_at
        FROM pp_caso_modelo_detalle
        WHERE fecha_base >= ?
          AND fecha_base <= ?
          AND operacion = ?
          AND (? = 'TODOS' OR almacen = ?)
          AND query_version = ?
        ORDER BY fecha_base, legajo, hora
        """,
        (fecha_desde, fecha_hasta, operacion, almacen, almacen, CASO_MODELO_DETALLE_QUERY_VERSION),
    )


async def _load_day_to_cache(
    db: aiosqlite.Connection,
    day: date,
    operacion: str,
    almacen: str,
    force: bool = False,
) -> dict[str, Any]:
    fecha_base = day.isoformat()
    existing = await _fetch_one(
        db,
        """
        SELECT COUNT(*) qty
        FROM pp_caso_modelo_dia
        WHERE fecha_base = ?
          AND operacion = ?
          AND (? = 'TODOS' OR almacen = ?)
          AND query_version = ?
        """,
        (fecha_base, operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION),
    )
    if existing and int(existing["qty"] or 0) > 0 and not force:
        return {"fecha": fecha_base, "estado": "cache", "rows": int(existing["qty"])}

    if force:
        await db.execute(
            """
            DELETE FROM pp_caso_modelo_dia
            WHERE fecha_base = ?
              AND operacion = ?
              AND (? = 'TODOS' OR almacen = ?)
              AND query_version = ?
            """,
            (fecha_base, operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION),
        )
        await db.execute(
            """
            DELETE FROM pp_caso_modelo_detalle
            WHERE fecha_base = ?
              AND operacion = ?
              AND (? = 'TODOS' OR almacen = ?)
              AND query_version = ?
            """,
            (fecha_base, operacion, almacen, almacen, CASO_MODELO_DETALLE_QUERY_VERSION),
        )

    hour_rows, day_rows, scales = await _fetch_premio_base(fecha_base, operacion)
    rows, detail_rows = _simulate_premio_rows(fecha_base, operacion, almacen, hour_rows, day_rows, scales)
    await db.executemany(
        """
        INSERT INTO pp_caso_modelo_dia
            (fecha_base, operacion, query_version, fecha, operario, bultos, almacen,
             premio_x_horas, premio_x_horas_bruto, productividad_anterior,
             premio_anterior, premio_anterior_bruto, descuento_tnc, descuento_error,
             descuentos_total, bultosturno, premio_actual, premio_actual_bruto,
             premio_x_horas_sin_extras, premio_x_horas_sin_extras_bruto, diferencia_x_horas,
             diferencia_sin_extras, diferencia_x_horas_sin_extras, loaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                fecha_base, operacion, CASO_MODELO_DIA_QUERY_VERSION, r["fecha"], r["operario"], r["bultos"], r["almacen"],
                r["premio_x_horas"], r["premio_x_horas_bruto"], r["productividad_anterior"],
                r["premio_anterior"], r["premio_anterior_bruto"], r["descuento_tnc"], r["descuento_error"],
                r["descuentos_total"], r["bultosturno"], r["premio_actual"], r["premio_actual_bruto"],
                r["premio_x_horas_sin_extras"], r["premio_x_horas_sin_extras_bruto"], r["diferencia_x_horas"],
                r["diferencia_sin_extras"], r["diferencia_x_horas_sin_extras"], _now(),
            )
            for r in rows
        ],
    )
    await db.executemany(
        """
        INSERT INTO pp_caso_modelo_detalle
            (fecha_base, legajo, query_version, fecha, hora, turno, operario, nombre,
             operacion, bultos, almacen, bultos_hora_min, bultos_hora_max,
             premio_x_hora, prod_modulo, pago_modulo, bultos_modulo, bultosturno,
             premio_sin_extra, penalizacion_tnc, penalizacion_error, loaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                fecha_base, r["operario"], CASO_MODELO_DETALLE_QUERY_VERSION, r["fecha"], r["hora"], r["turno"],
                r["operario"], r["nombre"], r["operacion"], r["bultos"], r["almacen"],
                r["bultos_hora_min"], r["bultos_hora_max"], r["premio_x_hora"],
                r["prod_modulo"], r["pago_modulo"], r["bultos_modulo"], r["bultosturno"],
                r["premio_sin_extra"], r["penalizacion_tnc"], r["penalizacion_error"], _now(),
            )
            for r in detail_rows
        ],
    )
    return {"fecha": fecha_base, "estado": "oracle", "rows": len(rows)}


async def obtenerDetalleLegajo(params: dict[str, Any]) -> list[dict[str, Any]]:
    operacion = _normalize_operacion(params.get("operacion"))
    almacen = _normalize_almacen(params.get("almacen"))
    fecha_base = _to_date(params["fecha_base"]).isoformat()
    legajo = str(params["legajo"]).strip()
    hour_rows, day_rows, scales = await _fetch_premio_base(fecha_base, operacion)
    _, detail_rows = _simulate_premio_rows(fecha_base, operacion, almacen, hour_rows, day_rows, scales)
    return [row for row in detail_rows if str(row.get("operario") or "") == legajo]


async def _detalle_rows(
    db: aiosqlite.Connection,
    fecha_base: str,
    legajo: str,
    operacion: str,
    almacen: str,
) -> list[dict[str, Any]]:
    return await _fetch_rows(
        db,
        """
        SELECT fecha, hora, turno, operario, nombre, operacion, bultos, almacen,
               bultos_hora_min, bultos_hora_max, premio_x_hora, prod_modulo,
               pago_modulo, bultos_modulo, bultosturno, premio_sin_extra,
               penalizacion_tnc, penalizacion_error
        FROM pp_caso_modelo_detalle
        WHERE fecha_base = ?
          AND legajo = ?
          AND operacion = ?
          AND (? = 'TODOS' OR almacen = ?)
          AND query_version = ?
        ORDER BY fecha, hora
        """,
        (fecha_base, legajo, operacion, almacen, almacen, CASO_MODELO_DETALLE_QUERY_VERSION),
    )


async def _load_detalle_to_cache(
    db: aiosqlite.Connection,
    fecha_base: str,
    legajo: str,
    operacion: str,
    almacen: str,
    force: bool = False,
) -> dict[str, Any]:
    rows = await _detalle_rows(db, fecha_base, legajo, operacion, almacen)
    if rows and not force:
        return {"estado": "cache", "rows": rows}
    await db.execute(
        """
        DELETE FROM pp_caso_modelo_detalle
        WHERE fecha_base = ?
          AND legajo = ?
          AND operacion = ?
          AND (? = 'TODOS' OR almacen = ?)
          AND query_version = ?
        """,
        (fecha_base, legajo, operacion, almacen, almacen, CASO_MODELO_DETALLE_QUERY_VERSION),
    )
    rows = await obtenerDetalleLegajo({
        "fecha_base": fecha_base,
        "legajo": legajo,
        "operacion": operacion,
        "almacen": almacen,
    })
    await db.executemany(
        """
        INSERT INTO pp_caso_modelo_detalle
            (fecha_base, legajo, query_version, fecha, hora, turno, operario, nombre,
             operacion, bultos, almacen, bultos_hora_min, bultos_hora_max,
             premio_x_hora, prod_modulo, pago_modulo, bultos_modulo, bultosturno,
             premio_sin_extra, penalizacion_tnc, penalizacion_error, loaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                fecha_base, legajo, CASO_MODELO_DETALLE_QUERY_VERSION, r["fecha"], r["hora"], r["turno"],
                r["operario"], r["nombre"], r["operacion"], r["bultos"], r["almacen"],
                r["bultos_hora_min"], r["bultos_hora_max"], r["premio_x_hora"],
                r["prod_modulo"], r["pago_modulo"], r["bultos_modulo"], r["bultosturno"],
                r["premio_sin_extra"], r["penalizacion_tnc"], r["penalizacion_error"], _now(),
            )
            for r in rows
        ],
    )
    return {"estado": "oracle", "rows": rows}


def _hour_label(hora: int | None) -> str:
    if hora is None:
        return ""
    return f"{int(hora):02d}:00"


TURNO_HOURS = {
    "manana": [6, 7, 8, 9, 10, 11, 12, 13],
    "tarde": [14, 15, 16, 17, 18, 19, 20, 21],
    "noche": [22, 23, 0, 1, 2, 3, 4, 5],
}
CICLO_HOURS = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]


def _detalle_sin_penalizaciones(detalle_rows: list[dict[str, Any]]) -> bool:
    if not detalle_rows:
        return False
    for row in detalle_rows:
        tnc = _upper(row.get("penalizacion_tnc"))
        error = _clean(row.get("penalizacion_error"))
        if tnc and tnc != "SIN PENALIZACION":
            return False
        if error:
            return False
    return True


def _turno_asignado_from_detalle(detalle_rows: list[dict[str, Any]]) -> str:
    positive_hours = {
        int(row["hora"])
        for row in detalle_rows
        if row.get("hora") is not None and float(row.get("bultos_modulo") or 0) > 0
    }
    for turno, hours in TURNO_HOURS.items():
        if positive_hours.intersection(hours):
            return turno
    return ""


def _build_hour_index(detalle_rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    by_hour: dict[int, dict[str, Any]] = {}
    for row in detalle_rows:
        hora_raw = row.get("hora")
        if hora_raw is None:
            continue
        hora = int(hora_raw)
        item = by_hour.setdefault(
            hora,
            {
                "hora": hora,
                "hora_label": _hour_label(hora),
                "bultos": 0.0,
                "bultos_dentro": 0.0,
                "bultos_extra": 0.0,
                "premio_x_hora": 0.0,
                "bultos_hora_min": 0.0,
                "bultos_hora_max": 0.0,
            },
        )
        bultos = float(row.get("bultos") or 0)
        dentro = float(row.get("bultos_modulo") or 0)
        extra = max(bultos - dentro, 0.0)
        item["bultos"] += bultos
        item["bultos_dentro"] += dentro
        item["bultos_extra"] += extra
        item["premio_x_hora"] += float(row.get("premio_x_hora") or 0)
        item["bultos_hora_min"] = float(row.get("bultos_hora_min") or 0)
        item["bultos_hora_max"] = float(row.get("bultos_hora_max") or 0)
    return by_hour


def _escala_para_objetivo(detalle_rows: list[dict[str, Any]], objetivo_hora: float) -> dict[str, Any]:
    if objetivo_hora <= 0:
        return {"min_hora": 0, "max_hora": 0, "premio_hora": 0, "premio_diario": 0, "label": ""}
    best = None
    for row in detalle_rows:
        min_hora = float(row.get("bultos_hora_min") or 0)
        max_hora = float(row.get("bultos_hora_max") or 0)
        premio_hora = float(row.get("premio_x_hora") or 0)
        if premio_hora <= 0:
            continue
        max_cmp = float("inf") if max_hora >= 10000 else max_hora
        if objetivo_hora > min_hora and objetivo_hora <= max_cmp:
            best = (min_hora, max_hora, premio_hora)
            break
    if best is None:
        candidates = [
            (
                abs(objetivo_hora - float(row.get("bultos_hora_min") or 0)),
                float(row.get("bultos_hora_min") or 0),
                float(row.get("bultos_hora_max") or 0),
                float(row.get("premio_x_hora") or 0),
            )
            for row in detalle_rows
            if float(row.get("premio_x_hora") or 0) > 0
        ]
        if candidates:
            _, min_hora, max_hora, premio_hora = sorted(candidates, key=lambda item: item[0])[0]
            best = (min_hora, max_hora, premio_hora)
    if best is None:
        return {"min_hora": 0, "max_hora": 0, "premio_hora": 0, "premio_diario": 0, "label": ""}
    min_hora, max_hora, premio_hora = best
    max_label = "sin tope" if max_hora >= 10000 else f"{max_hora:.0f}"
    return {
        "min_hora": round(min_hora, 2),
        "max_hora": round(max_hora, 2),
        "premio_hora": round(premio_hora, 2),
        "premio_diario": round(premio_hora * JORNADA_HORAS, 2),
        "label": f"{min_hora:.0f}-{max_label} b/h",
    }


def _escala_premio_actual(detalle_rows: list[dict[str, Any]], productividad: float, premio_actual: float) -> dict[str, Any]:
    if productividad <= 0 and premio_actual <= 0:
        return {"min_bultos": 0, "max_bultos": 0, "premio_cobrado": 0, "label": ""}
    best = None
    for row in detalle_rows:
        min_hora = float(row.get("bultos_hora_min") or 0)
        max_hora = float(row.get("bultos_hora_max") or 0)
        premio_hora = float(row.get("premio_x_hora") or 0)
        pago_modulo = float(row.get("pago_modulo") or 0)
        if premio_hora <= 0 and pago_modulo <= 0:
            continue
        min_bultos = min_hora * JORNADA_HORAS
        max_bultos = max_hora * JORNADA_HORAS
        max_cmp = float("inf") if max_hora >= 10000 else max_bultos
        premio_cobrado = pago_modulo or premio_hora * JORNADA_HORAS
        matches_premio = premio_actual > 0 and abs(premio_cobrado - premio_actual) < 1
        matches_productividad = productividad > min_bultos and productividad <= max_cmp
        if matches_premio or matches_productividad:
            best = (min_bultos, max_bultos, premio_cobrado)
            if matches_premio and matches_productividad:
                break
    if best is None:
        objetivo = productividad / JORNADA_HORAS if productividad > 0 else 0
        escala_hora = _escala_para_objetivo(detalle_rows, objetivo)
        if escala_hora.get("label"):
            best = (
                float(escala_hora.get("min_hora") or 0) * JORNADA_HORAS,
                float(escala_hora.get("max_hora") or 0) * JORNADA_HORAS,
                float(escala_hora.get("premio_diario") or premio_actual or 0),
            )
    if best is None:
        return {"min_bultos": 0, "max_bultos": 0, "premio_cobrado": round(premio_actual, 2), "label": ""}
    min_bultos, max_bultos, premio_cobrado = best
    max_label = "sin tope" if max_bultos >= 10000 * JORNADA_HORAS else f"{max_bultos:.0f}"
    return {
        "min_bultos": round(min_bultos, 2),
        "max_bultos": round(max_bultos, 2),
        "premio_cobrado": round(premio_actual or premio_cobrado, 2),
        "label": f"{min_bultos:.0f}-{max_label} bultos",
    }


def _calcular_caida_posterior(
    candidate: dict[str, Any],
    detalle_rows: list[dict[str, Any]],
    detalle_origen: str,
    caida_min_pct: float,
    concentracion_min_pct: float,
) -> dict[str, Any] | None:
    if not _detalle_sin_penalizaciones(detalle_rows):
        return None
    by_hour = _build_hour_index(detalle_rows)
    assigned_turno = _turno_asignado_from_detalle(detalle_rows)
    if not assigned_turno:
        return None
    total_extra = sum(float(item.get("bultos_extra") or 0) for item in by_hour.values())

    horas = []
    for idx, hora in enumerate(TURNO_HOURS[assigned_turno]):
        item = by_hour.get(hora) or {
            "hora": hora,
            "hora_label": _hour_label(hora),
            "bultos": 0.0,
            "bultos_dentro": 0.0,
            "bultos_extra": 0.0,
            "premio_x_hora": 0.0,
            "bultos_hora_min": 0.0,
            "bultos_hora_max": 0.0,
        }
        horas.append({**item, "bultos": float(item.get("bultos_dentro") or 0), "turno_index": idx, "es_extra": False})
    horas_con_produccion = [item for item in horas if float(item.get("bultos") or 0) > 0]
    if len(horas_con_produccion) < 2:
        return None

    pico = max(horas, key=lambda item: float(item.get("bultos") or 0))
    posteriores = [item for item in horas if int(item["turno_index"]) > int(pico["turno_index"])]
    if len(posteriores) < 2:
        return None
    if float(pico.get("premio_x_hora") or 0) <= 0:
        return None

    bultos_turno = sum(float(item.get("bultos") or 0) for item in horas)
    promedio_posterior = sum(float(item.get("bultos") or 0) for item in posteriores) / len(posteriores)
    bultos_pico = float(pico.get("bultos") or 0)
    if bultos_pico <= 0:
        return None

    caida_pct = max(0.0, (bultos_pico - promedio_posterior) / bultos_pico * 100)
    concentracion_pct = bultos_pico / bultos_turno * 100 if bultos_turno else 0
    cumple = caida_pct >= caida_min_pct and concentracion_pct >= concentracion_min_pct
    severidad = "Critico" if caida_pct >= 65 else "Revisar" if cumple else "Leve"
    productividad_reconocida = float(candidate.get("productividad_anterior") or 0)
    premio_actual = float(candidate.get("premio_anterior") or 0)
    objetivo_cobrado_hora = productividad_reconocida / JORNADA_HORAS
    escala_objetivo = _escala_para_objetivo(detalle_rows, objetivo_cobrado_hora)
    escala_actual = _escala_premio_actual(detalle_rows, productividad_reconocida, premio_actual)
    horas_sobre_objetivo = sum(
        1 for item in horas
        if objetivo_cobrado_hora > 0 and float(item.get("bultos") or 0) >= objetivo_cobrado_hora
    )
    horas_bajo_objetivo = sum(
        1 for item in horas
        if objetivo_cobrado_hora > 0 and float(item.get("bultos") or 0) < objetivo_cobrado_hora
    )
    horas_sin_premio_horario = sum(1 for item in horas if float(item.get("premio_x_hora") or 0) <= 0)

    max_bultos = max([float(item.get("bultos") or 0) for item in horas] + [1.0])
    horas_payload = []
    for item in horas:
        bultos = float(item.get("bultos") or 0)
        es_pico = int(item["turno_index"]) == int(pico["turno_index"])
        es_posterior = int(item["turno_index"]) > int(pico["turno_index"])
        horas_payload.append({
            **item,
            "bultos": round(bultos, 2),
            "premio_x_hora": round(float(item.get("premio_x_hora") or 0), 2),
            "bultos_hora_min": round(float(item.get("bultos_hora_min") or 0), 2),
            "bultos_hora_max": round(float(item.get("bultos_hora_max") or 0), 2),
            "es_pico": es_pico,
            "es_posterior": es_posterior,
            "caida_vs_pico_pct": round(max(0.0, (bultos_pico - bultos) / bultos_pico * 100), 1) if es_posterior else 0,
            "pct_max": round(bultos / max_bultos * 100, 1),
        })

    return {
        "fecha": candidate["fecha"],
        "operario": str(candidate["operario"]),
        "premio_actual": round(premio_actual, 2),
        "premio_x_horas": round(float(candidate.get("premio_x_horas") or 0), 2),
        "premio_x_horas_sin_extras": round(float(candidate.get("premio_x_horas_sin_extras") or 0), 2),
        "diferencia_x_horas_sin_extras": round(float(candidate.get("diferencia_x_horas_sin_extras") or 0), 2),
        "productividad_reconocida": round(productividad_reconocida, 2),
        "objetivo_cobrado_hora": round(objetivo_cobrado_hora, 2),
        "escala_objetivo": escala_objetivo,
        "escala_premio_actual": escala_actual,
        "bultos_turno": round(bultos_turno, 2),
        "hora_pico": int(pico["hora"]),
        "hora_pico_label": pico["hora_label"],
        "bultos_pico": round(bultos_pico, 2),
        "promedio_posterior": round(promedio_posterior, 2),
        "horas_posteriores": len(posteriores),
        "caida_posterior_pct": round(caida_pct, 1),
        "concentracion_pico_pct": round(concentracion_pct, 1),
        "severidad": severidad,
        "cumple_regla": cumple,
        "detalle_origen": detalle_origen,
        "tipo_problematica": "caida_inicio",
        "titulo_caso": "Acumulacion inicial y caida posterior",
        "resumen_modelo": {
            "horas_sobre_objetivo_cobrado": horas_sobre_objetivo,
            "horas_bajo_objetivo_cobrado": horas_bajo_objetivo,
            "horas_sin_premio_horario": horas_sin_premio_horario,
            "bultos_dentro_turno": round(bultos_turno, 2),
            "bultos_fuera_turno": round(total_extra, 2),
            "pct_fuera_turno": round(total_extra / (bultos_turno + total_extra) * 100, 1) if (bultos_turno + total_extra) else 0,
            "premio_actual": round(premio_actual, 2),
            "premio_horario_turno": round(float(candidate.get("premio_x_horas_sin_extras") or 0), 2),
            "diferencia": round(float(candidate.get("diferencia_x_horas_sin_extras") or 0), 2),
        },
        "horas": horas_payload,
    }


def _calcular_horas_extra(
    candidate: dict[str, Any],
    detalle_rows: list[dict[str, Any]],
    detalle_origen: str,
) -> dict[str, Any] | None:
    if not _detalle_sin_penalizaciones(detalle_rows):
        return None
    by_hour = _build_hour_index(detalle_rows)
    assigned_turno = _turno_asignado_from_detalle(detalle_rows)
    if not assigned_turno:
        return None
    productividad_reconocida = float(candidate.get("productividad_anterior") or 0)
    premio_actual = float(candidate.get("premio_anterior") or 0)
    objetivo_cobrado_hora = productividad_reconocida / JORNADA_HORAS
    escala_objetivo = _escala_para_objetivo(detalle_rows, objetivo_cobrado_hora)
    escala_actual = _escala_premio_actual(detalle_rows, productividad_reconocida, premio_actual)
    total = sum(float(item.get("bultos") or 0) for item in by_hour.values())
    dentro = sum(float(item.get("bultos_dentro") or 0) for item in by_hour.values())
    extra = sum(float(item.get("bultos_extra") or 0) for item in by_hour.values())
    if total <= 0 or extra < 300:
        return None
    pct_extra = extra / total * 100
    inside_avg = dentro / JORNADA_HORAS
    extra_active = [
        float(item.get("bultos_extra") or 0)
        for item in by_hour.values()
        if float(item.get("bultos_extra") or 0) > 0
    ]
    extra_avg = sum(extra_active) / len(extra_active) if extra_active else 0
    if not (inside_avg < objetivo_cobrado_hora * 0.85 and extra_avg >= objetivo_cobrado_hora * 0.65 and pct_extra >= 25):
        return None

    horas = []
    turno_set = set(TURNO_HOURS[assigned_turno])
    for idx, hora in enumerate(CICLO_HOURS):
        item = by_hour.get(hora) or {
            "hora": hora,
            "hora_label": _hour_label(hora),
            "bultos": 0.0,
            "bultos_dentro": 0.0,
            "bultos_extra": 0.0,
            "premio_x_hora": 0.0,
            "bultos_hora_min": 0.0,
            "bultos_hora_max": 0.0,
        }
        horas.append({
            **item,
            "turno_index": idx,
            "es_extra": hora not in turno_set,
            "es_pico": False,
            "es_posterior": False,
        })
    if not horas:
        return None
    pico = max(horas, key=lambda item: float(item.get("bultos") or 0))
    max_bultos = max([float(item.get("bultos") or 0) for item in horas] + [1.0])
    horas_payload = []
    for item in horas:
        bultos = float(item.get("bultos") or 0)
        es_pico = int(item["hora"]) == int(pico["hora"])
        horas_payload.append({
            **item,
            "bultos": round(bultos, 2),
            "bultos_dentro": round(float(item.get("bultos_dentro") or 0), 2),
            "bultos_extra": round(float(item.get("bultos_extra") or 0), 2),
            "premio_x_hora": round(float(item.get("premio_x_hora") or 0), 2),
            "bultos_hora_min": round(float(item.get("bultos_hora_min") or 0), 2),
            "bultos_hora_max": round(float(item.get("bultos_hora_max") or 0), 2),
            "es_pico": es_pico,
            "pct_max": round(bultos / max_bultos * 100, 1),
        })
    diferencia = float(candidate.get("diferencia_x_horas_sin_extras") or 0)
    return {
        "fecha": candidate["fecha"],
        "operario": str(candidate["operario"]),
        "premio_actual": round(premio_actual, 2),
        "premio_x_horas": round(float(candidate.get("premio_x_horas") or 0), 2),
        "premio_x_horas_sin_extras": round(float(candidate.get("premio_x_horas_sin_extras") or 0), 2),
        "diferencia_x_horas_sin_extras": round(diferencia, 2),
        "productividad_reconocida": round(productividad_reconocida, 2),
        "objetivo_cobrado_hora": round(objetivo_cobrado_hora, 2),
        "escala_objetivo": escala_objetivo,
        "escala_premio_actual": escala_actual,
        "bultos_turno": round(dentro, 2),
        "bultos_fuera_turno": round(extra, 2),
        "pct_fuera_turno": round(pct_extra, 1),
        "hora_pico": int(pico["hora"]),
        "hora_pico_label": pico["hora_label"],
        "bultos_pico": round(float(pico.get("bultos") or 0), 2),
        "promedio_dentro_turno": round(inside_avg, 2),
        "promedio_extra_activa": round(extra_avg, 2),
        "caida_posterior_pct": 0,
        "concentracion_pico_pct": round(float(pico.get("bultos") or 0) / total * 100, 1),
        "severidad": "Critico" if pct_extra >= 50 else "Revisar",
        "cumple_regla": True,
        "detalle_origen": detalle_origen,
        "tipo_problematica": "horas_extra",
        "titulo_caso": "Baja productividad estandar y alta productividad extra",
        "resumen_modelo": {
            "horas_sobre_objetivo_cobrado": sum(1 for item in horas if float(item.get("bultos") or 0) >= objetivo_cobrado_hora),
            "horas_bajo_objetivo_cobrado": sum(1 for item in horas if float(item.get("bultos") or 0) < objetivo_cobrado_hora),
            "horas_sin_premio_horario": sum(1 for item in horas if float(item.get("premio_x_hora") or 0) <= 0),
            "bultos_dentro_turno": round(dentro, 2),
            "bultos_fuera_turno": round(extra, 2),
            "pct_fuera_turno": round(pct_extra, 1),
            "promedio_dentro_turno": round(inside_avg, 2),
            "promedio_extra_activa": round(extra_avg, 2),
            "premio_actual": round(premio_actual, 2),
            "premio_horario_turno": round(float(candidate.get("premio_x_horas_sin_extras") or 0), 2),
            "premio_horario_total": round(float(candidate.get("premio_x_horas") or 0), 2),
            "diferencia": round(diferencia, 2),
        },
        "horas": horas_payload,
    }


async def _problematica_candidates(
    db: aiosqlite.Connection,
    fecha_desde: str,
    fecha_hasta: str,
    operacion: str,
    almacen: str,
    umbral_premio: float,
    min_bultos_turno: float,
    limit: int,
) -> list[dict[str, Any]]:
    return await _fetch_rows(
        db,
        """
        SELECT
            fecha_base AS fecha,
            operario,
            ROUND(SUM(bultos), 2) AS bultos,
            ROUND(SUM(bultosturno), 2) AS bultosturno,
            ROUND(MAX(productividad_anterior), 2) AS productividad_anterior,
            ROUND(SUM(premio_anterior), 2) AS premio_anterior,
            ROUND(SUM(premio_x_horas), 2) AS premio_x_horas,
            ROUND(SUM(premio_x_horas_sin_extras), 2) AS premio_x_horas_sin_extras,
            ROUND(SUM(diferencia_x_horas), 2) AS diferencia_x_horas,
            ROUND(SUM(diferencia_x_horas_sin_extras), 2) AS diferencia_x_horas_sin_extras
        FROM pp_caso_modelo_dia
        WHERE fecha_base >= ?
          AND fecha_base <= ?
          AND operacion = ?
          AND (? = 'TODOS' OR almacen = ?)
          AND query_version = ?
        GROUP BY fecha_base, operario
        HAVING premio_anterior > ?
           AND bultosturno >= ?
        ORDER BY diferencia_x_horas_sin_extras DESC, premio_anterior DESC
        LIMIT ?
        """,
        (fecha_desde, fecha_hasta, operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION, umbral_premio, min_bultos_turno, limit),
    )


def _sum(rows: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(row.get(key) or 0) for row in rows), 2)


def _normalize_divisor_horario(value: Any) -> float:
    try:
        divisor = float(value)
    except (TypeError, ValueError):
        divisor = float(JORNADA_HORAS)
    for allowed in DIVISORES_HORARIOS:
        if abs(divisor - allowed) < 0.001:
            return allowed
    return float(JORNADA_HORAS)


def _hourly_scenario_label(divisor: float) -> str:
    return "/6.5" if abs(float(divisor) - 6.5) < 0.001 else "/8"


def _scale_catalog_from_detail(detail_rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, float]]]:
    catalog: dict[tuple[str, str], dict[tuple[int, int, int], dict[str, float]]] = defaultdict(dict)
    for row in detail_rows:
        min_hora = float(row.get("bultos_hora_min") or 0)
        max_hora = float(row.get("bultos_hora_max") or 0)
        premio_hora = float(row.get("premio_x_hora") or 0)
        if premio_hora <= 0 or max_hora <= 0:
            continue
        item = {
            "desde_actual": round(min_hora * JORNADA_HORAS, 0),
            "hasta_actual": round(max_hora * JORNADA_HORAS, 0),
            "premio_actual": round(premio_hora * JORNADA_HORAS, 0),
        }
        key = (_upper(row.get("operacion")), _normalize_grupo_productivo(row.get("almacen")))
        catalog[key][(int(item["desde_actual"]), int(item["hasta_actual"]), int(item["premio_actual"]))] = item
    return {key: sorted(items.values(), key=lambda x: (x["desde_actual"], x["hasta_actual"], x["premio_actual"])) for key, items in catalog.items()}


def _find_hourly_scale_from_catalog(
    catalog: dict[tuple[str, str], list[dict[str, float]]],
    operacion: str,
    almacen: str,
    bultos: float,
    divisor: float,
) -> dict[str, float] | None:
    rows = catalog.get((_upper(operacion), _normalize_grupo_productivo(almacen)), [])
    for row in rows:
        low = round(float(row["desde_actual"]) / divisor, 0)
        high = round(float(row["hasta_actual"]) / divisor, 0)
        value = float(bultos or 0)
        if value > low and value < high:
            return {
                "bultos_hora_min": low,
                "bultos_hora_max": high,
                "premio_x_hora": round(float(row["premio_actual"]) / divisor, 0),
            }
    return None


def _apply_hourly_divisor_to_details(
    detail_rows: list[dict[str, Any]],
    divisor: float,
    catalog: dict[tuple[str, str], list[dict[str, float]]] | None = None,
) -> list[dict[str, Any]]:
    divisor = _normalize_divisor_horario(divisor)
    if abs(divisor - JORNADA_HORAS) < 0.001:
        return [dict(row) for row in detail_rows]
    catalog = catalog or _scale_catalog_from_detail(detail_rows)
    out: list[dict[str, Any]] = []
    for row in detail_rows:
        item = dict(row)
        scale = _find_hourly_scale_from_catalog(catalog, item.get("operacion"), item.get("almacen"), float(item.get("bultos") or 0), divisor)
        if scale:
            item["bultos_hora_min"] = scale["bultos_hora_min"]
            item["bultos_hora_max"] = scale["bultos_hora_max"]
            item["premio_x_hora"] = scale["premio_x_hora"]
        else:
            item["bultos_hora_min"] = 0.0
            item["bultos_hora_max"] = 0.0
            item["premio_x_hora"] = 0.0
        out.append(item)
    return out


def _detail_group_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("fecha_base") or row.get("fecha") or "")[:10],
        str(row.get("operario") or row.get("legajo") or "").strip(),
        _normalize_grupo_productivo(row.get("almacen")),
    )


def _apply_hourly_divisor_to_daily(
    daily_rows: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
    divisor: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    divisor = _normalize_divisor_horario(divisor)
    if abs(divisor - JORNADA_HORAS) < 0.001:
        return [dict(row) for row in daily_rows], [dict(row) for row in detail_rows]
    catalog = _scale_catalog_from_detail(detail_rows)
    scenario_details = _apply_hourly_divisor_to_details(detail_rows, divisor, catalog)
    grouped: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: {"bruto": 0.0, "sin_extras_bruto": 0.0})
    for detail in scenario_details:
        key = _detail_group_key(detail)
        premio = float(detail.get("premio_x_hora") or 0)
        grouped[key]["bruto"] += premio
        if float(detail.get("bultos_modulo") or 0) > 0:
            grouped[key]["sin_extras_bruto"] += premio
    out: list[dict[str, Any]] = []
    for row in daily_rows:
        item = dict(row)
        key = _detail_group_key(item)
        values = grouped.get(key, {"bruto": 0.0, "sin_extras_bruto": 0.0})
        descuento = float(item.get("descuentos_total") or 0)
        bruto = round(values["bruto"], 2)
        sin_ext_bruto = round(values["sin_extras_bruto"], 2)
        neto = round(max(0.0, bruto - descuento), 2)
        sin_ext_neto = round(max(0.0, sin_ext_bruto - descuento), 2)
        item["premio_x_horas"] = neto
        item["premio_x_horas_bruto"] = bruto
        item["premio_x_horas_sin_extras"] = sin_ext_neto
        item["premio_x_horas_sin_extras_bruto"] = sin_ext_bruto
        item["diferencia_x_horas"] = round(float(item.get("premio_anterior") or 0) - neto, 2)
        item["diferencia_x_horas_sin_extras"] = round(float(item.get("premio_anterior") or 0) - sin_ext_neto, 2)
        out.append(item)
    return out, scenario_details


def _scenario_explanation(rows: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    premio_anterior = _sum(rows, "premio_anterior")
    premio_anterior_bruto = _sum(rows, "premio_anterior_bruto")
    premio_actual = _sum(rows, "premio_actual")
    premio_actual_bruto = _sum(rows, "premio_actual_bruto")
    premio_x_horas = _sum(rows, "premio_x_horas")
    premio_x_horas_bruto = _sum(rows, "premio_x_horas_bruto")
    premio_x_horas_sin_extras = _sum(rows, "premio_x_horas_sin_extras")
    premio_x_horas_sin_extras_bruto = _sum(rows, "premio_x_horas_sin_extras_bruto")
    diferencia_sin_extras = _sum(rows, "diferencia_sin_extras")
    diferencia_x_horas_sin_extras = _sum(rows, "diferencia_x_horas_sin_extras")
    descuento_tnc = _sum(rows, "descuento_tnc")
    descuento_error = _sum(rows, "descuento_error")
    descuentos_total = _sum(rows, "descuentos_total")
    brecha_metodos_sin_extra = round(premio_x_horas_sin_extras - premio_actual, 2)
    bultos = _sum(rows, "bultos")
    bultosturno = _sum(rows, "bultosturno")
    bultos_extra = round(sum(max(0, float(row.get("bultos") or 0) - float(row.get("bultosturno") or 0)) for row in rows), 2)
    pct_extra = round((bultos_extra / bultos * 100) if bultos else 0, 2)
    diarios_mayor_ahorro = [row for row in rows if float(row.get("diferencia_sin_extras") or 0) > float(row.get("diferencia_x_horas_sin_extras") or 0)]
    horarios_mayor_ahorro = [row for row in rows if float(row.get("diferencia_sin_extras") or 0) < float(row.get("diferencia_x_horas_sin_extras") or 0)]
    pago_diario_cero_con_horas = [
        row for row in rows
        if float(row.get("premio_actual") or 0) <= 0 and float(row.get("premio_x_horas_sin_extras") or 0) > 0
    ]
    top = sorted(
        [
            {
                "fecha": str(row.get("fecha") or "")[:10],
                "operario": str(row.get("operario") or ""),
                "premio_actual": round(float(row.get("premio_actual") or 0), 2),
                "premio_x_horas_sin_extras": round(float(row.get("premio_x_horas_sin_extras") or 0), 2),
                "brecha": round(float(row.get("premio_x_horas_sin_extras") or 0) - float(row.get("premio_actual") or 0), 2),
                "bultos": round(float(row.get("bultos") or 0), 2),
                "bultosturno": round(float(row.get("bultosturno") or 0), 2),
            }
            for row in rows
            if float(row.get("premio_x_horas_sin_extras") or 0) > float(row.get("premio_actual") or 0)
        ],
        key=lambda item: item["brecha"],
        reverse=True,
    )[:8]
    return {
        "meta": meta or {},
        "totales": {
            "premio_actual_pagado": premio_anterior,
            "premio_actual_pagado_bruto": premio_anterior_bruto,
            "premio_diario_sin_extras": premio_actual,
            "premio_diario_sin_extras_bruto": premio_actual_bruto,
            "premio_horario_con_extras": premio_x_horas,
            "premio_horario_con_extras_bruto": premio_x_horas_bruto,
            "premio_horario_sin_extras": premio_x_horas_sin_extras,
            "premio_horario_sin_extras_bruto": premio_x_horas_sin_extras_bruto,
            "ahorro_diario_sin_extras": diferencia_sin_extras,
            "ahorro_horario_sin_extras": diferencia_x_horas_sin_extras,
            "brecha_metodos_sin_extra": brecha_metodos_sin_extra,
            "descuento_tnc": descuento_tnc,
            "descuento_error": descuento_error,
            "descuentos_total": descuentos_total,
            "bultos": bultos,
            "bultosturno": bultosturno,
            "bultos_extra": bultos_extra,
            "pct_bultos_extra": pct_extra,
        },
        "diagnostico": {
            "casos": len(rows),
            "casos_diario_ahorra_mas": len(diarios_mayor_ahorro),
            "casos_horario_ahorra_mas": len(horarios_mayor_ahorro),
            "casos_diario_cero_con_pago_horario": len(pago_diario_cero_con_horas),
            "top_brechas": top,
        },
        "lectura": [
            "El metodo diario sin extras recalcula el premio completo contra la escala diaria usando solo los bultos dentro del turno.",
            "Todos los escenarios mostrados como pago o diferencia se comparan netos: al premio bruto simulado se le descuentan TNC y errores con piso cero.",
            "Como la escala es por niveles, sacar bultos extra no reduce el premio en forma proporcional: puede hacer caer al legajo a un nivel menor o directamente a premio cero.",
            "El metodo por horas sin extras evalua cada hora dentro del turno por separado y despues suma esos pagos; por eso conserva pagos parciales en horas buenas aunque el total diario quede por debajo de un umbral.",
            "La diferencia no indica necesariamente un error de suma: muestra el efecto no lineal de comparar una escala diaria por niveles contra una suma de segmentos horarios.",
        ],
    }


def _caso_modelo_payload(
    rows: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
    sensibilidad_65_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    extra_rows = [
        row for row in rows
        if max(0, float(row.get("bultos") or 0) - float(row.get("bultosturno") or 0)) > 0
    ]
    kpis = {
        "premio_anterior": _sum(rows, "premio_anterior"),
        "premio_anterior_bruto": _sum(rows, "premio_anterior_bruto"),
        "premio_x_horas": _sum(rows, "premio_x_horas"),
        "premio_x_horas_bruto": _sum(rows, "premio_x_horas_bruto"),
        "premio_x_horas_sin_extras": _sum(rows, "premio_x_horas_sin_extras"),
        "premio_x_horas_sin_extras_bruto": _sum(rows, "premio_x_horas_sin_extras_bruto"),
        "premio_actual": _sum(rows, "premio_actual"),
        "premio_actual_bruto": _sum(rows, "premio_actual_bruto"),
        "descuento_tnc": _sum(rows, "descuento_tnc"),
        "descuento_error": _sum(rows, "descuento_error"),
        "descuentos_total": _sum(rows, "descuentos_total"),
        "diferencia_x_horas": _sum(rows, "diferencia_x_horas"),
        "diferencia_sin_extras": _sum(rows, "diferencia_sin_extras"),
        "diferencia_x_horas_sin_extras": _sum(rows, "diferencia_x_horas_sin_extras"),
        "operarios": len({str(row.get("operario") or "") for row in rows if row.get("operario")}),
        "operarios_extra": len({str(row.get("operario") or "") for row in extra_rows if row.get("operario")}),
        "casos": len(rows),
        "bultos": _sum(rows, "bultos"),
        "bultosturno": _sum(rows, "bultosturno"),
        "bultos_extra": sum(
            max(0, float(row.get("bultos") or 0) - float(row.get("bultosturno") or 0))
            for row in rows
        ),
    }
    if sensibilidad_65_rows is not None:
        kpis["sensibilidad_65_premio_x_horas"] = _sum(sensibilidad_65_rows, "premio_x_horas")
        kpis["sensibilidad_65_premio_x_horas_sin_extras"] = _sum(sensibilidad_65_rows, "premio_x_horas_sin_extras")
        kpis["sensibilidad_65_diferencia_x_horas"] = _sum(sensibilidad_65_rows, "diferencia_x_horas")
        kpis["sensibilidad_65_casos_horas_mayor"] = sum(
            1
            for row in sensibilidad_65_rows
            if float(row.get("premio_x_horas") or 0) > float(row.get("premio_anterior") or 0) + 0.01
        )
        kpis["sensibilidad_65_casos_con_premio"] = sum(
            1 for row in sensibilidad_65_rows if float(row.get("premio_x_horas") or 0) > 0.01
        )
    return {
        "meta": meta or {},
        "kpis": kpis,
        "rows": rows,
        "explicacion": _scenario_explanation(rows, meta),
        "graficos": {
            "comparativo": [
                {"grupo": "Actual jornada", "valor": kpis["premio_anterior"]},
                {"grupo": "Actual sin extras", "valor": kpis["premio_actual"]},
                {"grupo": "Horas con extras", "valor": kpis["premio_x_horas"]},
                {"grupo": "Horas sin extras", "valor": kpis["premio_x_horas_sin_extras"]},
            ],
            "ahorros": [
                {"grupo": "Actual - actual sin extras", "valor": kpis["diferencia_sin_extras"]},
                {"grupo": "Actual - horas con extras", "valor": kpis["diferencia_x_horas"]},
                {"grupo": "Actual - horas sin extras", "valor": kpis["diferencia_x_horas_sin_extras"]},
            ],
        },
    }


@router.post("/consultar-rango")
async def consultar_rango(req: RangoCasoModeloRequest):
    await init_premio_productividad_db()
    days = _date_range_inclusive(req.fecha_desde, req.fecha_hasta)
    operacion = _normalize_operacion(req.operacion)
    almacen = _normalize_almacen(req.almacen)
    divisor_horario = _normalize_divisor_horario(req.divisor_horario)
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        estados = []
        for day in days:
            estados.append(await _load_day_to_cache(db, day, operacion, almacen, force=req.force))
            await db.commit()
        rows = await _cache_rows_for_range(db, days[0].isoformat(), days[-1].isoformat(), operacion, almacen)
        detail_rows = await _detail_rows_for_range_internal(db, days[0].isoformat(), days[-1].isoformat(), operacion, almacen)
    rows, _ = _apply_hourly_divisor_to_daily(rows, detail_rows, divisor_horario)
    sensibilidad_65_rows, _ = _apply_hourly_divisor_to_daily(rows, detail_rows, 6.5) if abs(divisor_horario - 6.5) >= 0.001 else (rows, [])
    meta = {
        "fecha_desde": days[0].isoformat(),
        "fecha_hasta": days[-1].isoformat(),
        "operacion": operacion,
        "almacen": almacen,
        "dias": len(days),
        "dias_oracle": sum(1 for row in estados if row["estado"] == "oracle"),
        "dias_cache": sum(1 for row in estados if row["estado"] == "cache"),
        "detalle_dias": estados,
        "query_version": CASO_MODELO_DIA_QUERY_VERSION,
        "divisor_horario": divisor_horario,
        "escenario_horario": _hourly_scenario_label(divisor_horario),
        "origen": "cache_sqlite",
    }
    return _caso_modelo_payload(rows, meta, sensibilidad_65_rows)


@router.get("/rango-cache")
async def rango_cache(
    fecha_desde: str = Query(...),
    fecha_hasta: str = Query(...),
    operacion: str = Query(DEFAULT_OPERACION),
    almacen: str = Query(DEFAULT_ALMACEN),
    divisor_horario: float = Query(JORNADA_HORAS),
):
    days = _date_range_inclusive(fecha_desde, fecha_hasta)
    operacion = _normalize_operacion(operacion)
    almacen = _normalize_almacen(almacen)
    divisor_horario = _normalize_divisor_horario(divisor_horario)
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _cache_rows_for_range(db, days[0].isoformat(), days[-1].isoformat(), operacion, almacen)
        detail_rows = await _detail_rows_for_range_internal(db, days[0].isoformat(), days[-1].isoformat(), operacion, almacen)
    selected_rows, _ = _apply_hourly_divisor_to_daily(rows, detail_rows, divisor_horario)
    sensibilidad_65_rows, _ = _apply_hourly_divisor_to_daily(rows, detail_rows, 6.5)
    return _caso_modelo_payload(selected_rows, {
        "fecha_desde": days[0].isoformat(),
        "fecha_hasta": days[-1].isoformat(),
        "operacion": operacion,
        "almacen": almacen,
        "dias": len(days),
        "query_version": CASO_MODELO_DIA_QUERY_VERSION,
        "divisor_horario": divisor_horario,
        "escenario_horario": _hourly_scenario_label(divisor_horario),
        "origen": "cache_sqlite",
    }, sensibilidad_65_rows)


@router.post("/explicacion-ia")
async def explicacion_ia(req: ExplicacionPremioRequest):
    days = _date_range_inclusive(req.fecha_desde, req.fecha_hasta)
    operacion = _normalize_operacion(req.operacion)
    almacen = _normalize_almacen(req.almacen)
    meta = {
        "fecha_desde": days[0].isoformat(),
        "fecha_hasta": days[-1].isoformat(),
        "operacion": operacion,
        "almacen": almacen,
        "dias": len(days),
        "query_version": CASO_MODELO_DIA_QUERY_VERSION,
        "origen": "cache_sqlite",
    }
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _cache_rows_for_range(db, days[0].isoformat(), days[-1].isoformat(), operacion, almacen)
    explicacion = _scenario_explanation(rows, meta)
    provider = (req.provider or "").strip().lower()
    try:
        from routers.ai import _active_provider, _call_ai

        provider = provider or _active_provider()
        system = (
            "Sos un analista senior de productividad y compensaciones de un centro de distribucion. "
            "Explica diferencias entre escenarios de premios con numeros concretos, en espanol claro, "
            "sin senalar personas ni legajos como culpables. Maximo 5 bullets."
        )
        user = (
            "Necesito explicar por que el metodo diario sin extras puede ahorrar mas que el metodo horario sin extras. "
            "Usa este resumen calculado por el backend y no inventes datos:\n"
            f"{json.dumps(explicacion, ensure_ascii=False)}"
        )
        texto, model_used = await _call_ai(provider, system, [{"role": "user", "content": user}])
        return {
            "explicacion": explicacion,
            "ia": {
                "texto": texto.strip(),
                "provider": provider,
                "model_used": model_used,
                "error": "",
            },
        }
    except Exception as exc:
        logger.warning("No se pudo generar explicacion IA de premio: %s", exc)
        return {
            "explicacion": explicacion,
            "ia": {
                "texto": "",
                "provider": provider,
                "model_used": "",
                "error": str(exc),
            },
        }


@router.get("/cache-cobertura")
async def cache_cobertura(
    fecha_desde: str = Query(...),
    fecha_hasta: str = Query(...),
    operacion: str = Query(DEFAULT_OPERACION),
    almacen: str = Query(DEFAULT_ALMACEN),
):
    days = _date_range_inclusive(fecha_desde, fecha_hasta)
    expected = [day.isoformat() for day in days]
    operacion = _normalize_operacion(operacion)
    almacen = _normalize_almacen(almacen)
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cached_rows = await _fetch_rows(
            db,
            """
            SELECT fecha_base, COUNT(*) rows
            FROM pp_caso_modelo_dia
            WHERE fecha_base >= ?
              AND fecha_base <= ?
              AND operacion = ?
              AND (? = 'TODOS' OR almacen = ?)
              AND query_version = ?
            GROUP BY fecha_base
            ORDER BY fecha_base
            """,
            (expected[0], expected[-1], operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION),
        )
    cached = {row["fecha_base"]: int(row["rows"] or 0) for row in cached_rows}
    missing = [day for day in expected if day not in cached]
    return {
        "fecha_desde": expected[0],
        "fecha_hasta": expected[-1],
        "operacion": operacion,
        "almacen": almacen,
        "dias": len(expected),
        "dias_cache": len(cached),
        "dias_faltantes": len(missing),
        "faltantes": missing,
        "cache": [{"fecha": day, "rows": cached[day]} for day in expected if day in cached],
        "query_version": CASO_MODELO_DIA_QUERY_VERSION,
    }


@router.get("/ultima-fecha-cache")
async def ultima_fecha_cache(
    operacion: str = Query(DEFAULT_OPERACION),
    almacen: str = Query(DEFAULT_ALMACEN),
):
    operacion = _normalize_operacion(operacion)
    almacen = _normalize_almacen(almacen)
    await init_premio_productividad_db()
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await _fetch_one(
            db,
            """
            WITH candidatos AS (
                SELECT fecha_base, operario
                FROM pp_caso_modelo_dia
                WHERE operacion = ?
                  AND (? = 'TODOS' OR almacen = ?)
                  AND query_version = ?
                GROUP BY fecha_base, operario
                HAVING SUM(premio_anterior) > 40000
                   AND SUM(bultosturno) >= 400
            ),
            detalle AS (
                SELECT fecha_base, legajo
                FROM pp_caso_modelo_detalle
                WHERE operacion = ?
                  AND (? = 'TODOS' OR almacen = ?)
                  AND query_version = ?
                GROUP BY fecha_base, legajo
                HAVING SUM(bultos_modulo) >= 400
            )
            SELECT c.fecha_base AS fecha
            FROM candidatos c
            JOIN detalle d
              ON d.fecha_base = c.fecha_base
             AND CAST(d.legajo AS TEXT) = CAST(c.operario AS TEXT)
            GROUP BY c.fecha_base
            HAVING COUNT(*) >= 5
            ORDER BY c.fecha_base DESC
            LIMIT 1
            """,
            (operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION, operacion, almacen, almacen, CASO_MODELO_DETALLE_QUERY_VERSION),
        )
        if not row or not row.get("fecha"):
            row = await _fetch_one(
                db,
                """
                SELECT fecha_base AS fecha
                FROM pp_caso_modelo_dia
                WHERE operacion = ?
                  AND (? = 'TODOS' OR almacen = ?)
                  AND query_version = ?
                GROUP BY fecha_base
                HAVING SUM(CASE WHEN premio_anterior > 40000 AND bultosturno >= 400 THEN 1 ELSE 0 END) > 0
                ORDER BY fecha_base DESC
                LIMIT 1
                """,
                (operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION),
            )
        if not row or not row.get("fecha"):
            row = await _fetch_one(
                db,
                """
                SELECT MAX(fecha_base) AS fecha
                FROM pp_caso_modelo_dia
                WHERE operacion = ?
                  AND (? = 'TODOS' OR almacen = ?)
                  AND query_version = ?
                """,
                (operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION),
            )
    return {
        "fecha": row.get("fecha") if row else None,
        "operacion": operacion,
        "almacen": almacen,
        "query_version": CASO_MODELO_DIA_QUERY_VERSION,
        "origen": "cache_sqlite",
    }


@router.get("/detalle-legajo")
async def detalle_legajo(
    fecha: str = Query(...),
    legajo: str = Query(...),
    force: bool = False,
    operacion: str = Query(DEFAULT_OPERACION),
    almacen: str = Query(DEFAULT_ALMACEN),
    divisor_horario: float = Query(JORNADA_HORAS),
):
    fecha_base = _to_date(fecha).isoformat()
    legajo = _clean(legajo)
    operacion = _normalize_operacion(operacion)
    almacen = _normalize_almacen(almacen)
    divisor_horario = _normalize_divisor_horario(divisor_horario)
    if not legajo:
        raise HTTPException(status_code=400, detail="Indica un legajo.")
    await init_premio_productividad_db()
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        loaded = await _load_detalle_to_cache(db, fecha_base, legajo, operacion, almacen, force=force)
        await db.commit()
    rows = _apply_hourly_divisor_to_details(loaded["rows"], divisor_horario)
    return {
        "meta": {
            "fecha": fecha_base,
            "legajo": legajo,
            "operacion": operacion,
            "almacen": almacen,
            "origen": loaded["estado"],
            "query_version": CASO_MODELO_DETALLE_QUERY_VERSION,
            "divisor_horario": divisor_horario,
            "escenario_horario": _hourly_scenario_label(divisor_horario),
        },
        "kpis": {
            "horas": len(rows),
            "bultos": _sum(rows, "bultos"),
            "premio_x_hora": _sum(rows, "premio_x_hora"),
            "bultos_modulo": _sum(rows, "bultos_modulo"),
            "bultosturno": rows[0].get("bultosturno", 0) if rows else 0,
            "premio_sin_extra": rows[0].get("premio_sin_extra", 0) if rows else 0,
            "penalizacion_tnc": rows[0].get("penalizacion_tnc", "") if rows else "",
            "penalizacion_error": rows[0].get("penalizacion_error", "") if rows else "",
        },
        "rows": rows,
    }


@router.get("/problematica-modelo-actual")
async def problematica_modelo_actual(
    fecha_desde: str = Query(...),
    fecha_hasta: str = Query(...),
    operacion: str = Query(DEFAULT_OPERACION),
    almacen: str = Query(DEFAULT_ALMACEN),
    umbral_premio: float = Query(40000, ge=0),
    caida_min_pct: float = Query(50, ge=0, le=100),
    concentracion_min_pct: float = Query(0, ge=0, le=100),
    min_bultos_turno: float = Query(400, ge=0),
    max_candidatos: int = Query(40, ge=1, le=150),
    force_detalle: bool = Query(False),
):
    days = _date_range_inclusive(fecha_desde, fecha_hasta)
    operacion = _normalize_operacion(operacion)
    almacen = _normalize_almacen(almacen)
    umbral_premio = _param_float(umbral_premio, 40000)
    caida_min_pct = _param_float(caida_min_pct, 50)
    concentracion_min_pct = _param_float(concentracion_min_pct, 0)
    min_bultos_turno = _param_float(min_bultos_turno, 400)
    max_candidatos = _param_int(max_candidatos, 40)
    force_detalle = _param_bool(force_detalle, False)
    await init_premio_productividad_db()
    casos_caida: list[dict[str, Any]] = []
    casos_extra: list[dict[str, Any]] = []
    candidatos_sin_detalle: list[dict[str, Any]] = []
    detalle_oracle = 0
    detalle_cache = 0
    dias_oracle = 0
    dias_cache = 0

    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for day in days:
            estado = await _load_day_to_cache(db, day, operacion, almacen, force=False)
            if estado["estado"] == "oracle":
                dias_oracle += 1
            else:
                dias_cache += 1
            await db.commit()

        candidates = await _problematica_candidates(
            db,
            days[0].isoformat(),
            days[-1].isoformat(),
            operacion,
            almacen,
            umbral_premio,
            min_bultos_turno,
            max_candidatos,
        )
        for candidate in candidates:
            legajo = str(candidate.get("operario") or "").strip()
            fecha = _to_date(candidate["fecha"]).isoformat()
            if not legajo:
                continue
            try:
                loaded = await _load_detalle_to_cache(db, fecha, legajo, operacion, almacen, force=force_detalle)
                await db.commit()
                if loaded["estado"] == "oracle":
                    detalle_oracle += 1
                else:
                    detalle_cache += 1
                caso = _calcular_caida_posterior(
                    candidate,
                    loaded["rows"],
                    loaded["estado"],
                    caida_min_pct,
                    concentracion_min_pct,
                )
                if caso:
                    casos_caida.append(caso)
                caso_extra = _calcular_horas_extra(candidate, loaded["rows"], loaded["estado"])
                if caso_extra:
                    casos_extra.append(caso_extra)
                elif not loaded["rows"]:
                    item_sin_detalle = {
                        "fecha": fecha,
                        "operario": legajo,
                        "premio_actual": round(float(candidate.get("premio_anterior") or 0), 2),
                        "premio_x_horas_sin_extras": round(float(candidate.get("premio_x_horas_sin_extras") or 0), 2),
                        "diferencia_x_horas_sin_extras": round(float(candidate.get("diferencia_x_horas_sin_extras") or 0), 2),
                        "severidad": "Pendiente",
                        "detalle_origen": "sin_detalle",
                        "cumple_regla": False,
                        "horas": [],
                        "motivo": "Oracle no devolvio detalle horario para el legajo y fecha.",
                    }
                    candidatos_sin_detalle.append(item_sin_detalle)
            except Exception as exc:
                logger.exception("No se pudo enriquecer detalle para %s %s", fecha, legajo)
                candidatos_sin_detalle.append({
                    "fecha": fecha,
                    "operario": legajo,
                    "premio_actual": round(float(candidate.get("premio_anterior") or 0), 2),
                    "premio_x_horas_sin_extras": round(float(candidate.get("premio_x_horas_sin_extras") or 0), 2),
                    "diferencia_x_horas_sin_extras": round(float(candidate.get("diferencia_x_horas_sin_extras") or 0), 2),
                    "severidad": "Pendiente",
                    "detalle_origen": "error_oracle",
                    "cumple_regla": False,
                    "horas": [],
                    "motivo": str(exc),
                })

    casos_caida.sort(
        key=lambda item: (
            0 if item["cumple_regla"] else 1,
            -float(item.get("caida_posterior_pct") or 0),
            -float(item.get("premio_actual") or 0),
        )
    )
    casos_extra.sort(key=lambda item: (-float(item.get("pct_fuera_turno") or 0), -float(item.get("premio_actual") or 0)))
    casos_confirmados = [item for item in casos_caida if item["cumple_regla"]]

    def kpis_for(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
        premio_actual = _sum(rows, "premio_actual")
        premio_horas = _sum(rows, "premio_x_horas_sin_extras")
        out = {
            "casos_detectados": len(rows),
            "candidatos": len(candidates),
            "candidatos_sin_detalle": len(candidatos_sin_detalle),
            "detalle_oracle": detalle_oracle,
            "detalle_cache": detalle_cache,
            "premio_actual": round(premio_actual, 2),
            "premio_x_horas_sin_extras": round(premio_horas, 2),
            "diferencia_estimada": round(premio_actual - premio_horas, 2),
        }
        if metric == "caida":
            out["caida_posterior_promedio"] = round(
                sum(float(item.get("caida_posterior_pct") or 0) for item in rows) / len(rows),
                1,
            ) if rows else 0
        else:
            out["pct_fuera_turno_promedio"] = round(
                sum(float(item.get("pct_fuera_turno") or 0) for item in rows) / len(rows),
                1,
            ) if rows else 0
        return out

    kpis_caida = kpis_for(casos_confirmados, "caida")
    kpis_caida["casos_analizados"] = len(casos_caida)
    kpis_extra = kpis_for(casos_extra, "extra")
    kpis_extra["casos_analizados"] = len(casos_extra)
    return {
        "meta": {
            "fecha_desde": days[0].isoformat(),
            "fecha_hasta": days[-1].isoformat(),
            "operacion": operacion,
            "almacen": almacen,
            "dias": len(days),
            "dias_oracle": dias_oracle,
            "dias_cache": dias_cache,
            "detalle_oracle": detalle_oracle,
            "detalle_cache": detalle_cache,
            "umbral_premio": umbral_premio,
            "caida_min_pct": caida_min_pct,
            "concentracion_min_pct": concentracion_min_pct,
            "min_bultos_turno": min_bultos_turno,
            "max_candidatos": max_candidatos,
            "query_version_dia": CASO_MODELO_DIA_QUERY_VERSION,
            "query_version_detalle": CASO_MODELO_DETALLE_QUERY_VERSION,
        },
        "kpis": kpis_caida,
        "kpis_por_modo": {
            "caida_inicio": kpis_caida,
            "horas_extra": kpis_extra,
        },
        "casos": casos_caida,
        "casos_confirmados": casos_confirmados,
        "casos_horas_extra": casos_extra,
        "modos": {
            "caida_inicio": {
                "titulo": "Acumulacion inicial y caida posterior",
                "casos": casos_confirmados,
                "analizados": casos_caida,
                "kpis": kpis_caida,
            },
            "horas_extra": {
                "titulo": "Baja productividad estandar y alta productividad extra",
                "casos": casos_extra,
                "analizados": casos_extra,
                "kpis": kpis_extra,
            },
        },
        "candidatos_pendientes": candidatos_sin_detalle,
        "candidatos_sin_detalle": candidatos_sin_detalle,
        "lectura": [
            "La vista ilustra una limitacion del metodo actual: el premio diario puede quedar alto aunque la productividad no se sostenga despues del pico horario.",
            "La caida posterior al pico se calcula solo con horas dentro del turno asignado.",
            "Los legajos se muestran como ejemplos operativos para explicar el comportamiento del modelo, no como senalamiento individual.",
        ],
    }


@router.get("/detalle-cache")
async def detalle_cache(
    fecha_desde: str = Query(...),
    fecha_hasta: str = Query(...),
    operacion: str = Query(DEFAULT_OPERACION),
    almacen: str = Query(DEFAULT_ALMACEN),
    divisor_horario: float = Query(JORNADA_HORAS),
    legajo: str = "",
):
    days = _date_range_inclusive(fecha_desde, fecha_hasta)
    operacion = _normalize_operacion(operacion)
    almacen = _normalize_almacen(almacen)
    divisor_horario = _normalize_divisor_horario(divisor_horario)
    params: list[Any] = [days[0].isoformat(), days[-1].isoformat(), operacion, almacen, almacen, CASO_MODELO_DETALLE_QUERY_VERSION]
    legajo_filter = _clean(legajo)
    legajo_sql = ""
    if legajo_filter:
        legajo_sql = "AND CAST(legajo AS TEXT) LIKE ?"
        params.append(f"%{legajo_filter}%")
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _fetch_rows(
            db,
            f"""
            SELECT fecha_base, legajo, fecha, hora, turno, operario, nombre, operacion,
                   bultos, almacen, bultos_hora_min, bultos_hora_max, premio_x_hora,
                   prod_modulo, pago_modulo, bultos_modulo, bultosturno,
                   premio_sin_extra, penalizacion_tnc, penalizacion_error, loaded_at
            FROM pp_caso_modelo_detalle
            WHERE fecha_base >= ?
              AND fecha_base <= ?
              AND operacion = ?
              AND (? = 'TODOS' OR almacen = ?)
              AND query_version = ?
              {legajo_sql}
            ORDER BY fecha_base DESC, legajo, hora
            LIMIT 5000
            """,
            tuple(params),
        )
    rows = _apply_hourly_divisor_to_details(rows, divisor_horario)
    return {
        "fecha_desde": days[0].isoformat(),
        "fecha_hasta": days[-1].isoformat(),
        "operacion": operacion,
        "almacen": almacen,
        "divisor_horario": divisor_horario,
        "escenario_horario": _hourly_scenario_label(divisor_horario),
        "query_version": CASO_MODELO_DETALLE_QUERY_VERSION,
        "rows": rows,
        "limit": 5000,
    }


@router.post("/exportar-gif")
async def exportar_gif(req: GifExportRequest):
    if not req.frames:
        raise HTTPException(status_code=400, detail="No se recibieron frames para exportar.")
    if len(req.frames) > 80:
        raise HTTPException(status_code=400, detail="El GIF admite hasta 80 frames.")
    duration_ms = max(40, min(int(req.duration_ms or 90), 500))
    images: list[Image.Image] = []
    try:
        for frame in req.frames:
            raw = frame.split(",", 1)[1] if "," in frame else frame
            payload = base64.b64decode(raw, validate=False)
            if len(payload) > 4_000_000:
                raise HTTPException(status_code=400, detail="Un frame excede el tamano permitido.")
            image = Image.open(io.BytesIO(payload)).convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image)
            images.append(background.convert("P", palette=Image.Palette.ADAPTIVE, colors=256))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo procesar la animacion: {exc}") from exc

    output = io.BytesIO()
    images[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
        optimize=False,
    )
    output.seek(0)
    filename = _clean(req.filename or "detalle-impacto-extras.gif").replace('"', "")
    if not filename.lower().endswith(".gif"):
        filename = f"{filename}.gif"
    return StreamingResponse(
        output,
        media_type="image/gif",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/datos-cache")
async def datos_cache(
    fecha_desde: str = Query(...),
    fecha_hasta: str = Query(...),
    operacion: str = Query(DEFAULT_OPERACION),
    almacen: str = Query(DEFAULT_ALMACEN),
):
    days = _date_range_inclusive(fecha_desde, fecha_hasta)
    expected = [day.isoformat() for day in days]
    operacion = _normalize_operacion(operacion)
    almacen = _normalize_almacen(almacen)
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        daily = await _fetch_rows(
            db,
            """
            SELECT fecha_base, COUNT(*) rows, MAX(loaded_at) last_loaded_at
            FROM pp_caso_modelo_dia
            WHERE fecha_base >= ?
              AND fecha_base <= ?
              AND operacion = ?
              AND (? = 'TODOS' OR almacen = ?)
              AND query_version = ?
            GROUP BY fecha_base
            ORDER BY fecha_base
            """,
            (expected[0], expected[-1], operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION),
        )
        detail_count = await _fetch_one(
            db,
            """
            SELECT COUNT(*) rows,
                   COUNT(DISTINCT fecha_base || ':' || legajo) legajo_dias,
                   MAX(loaded_at) last_loaded_at
            FROM pp_caso_modelo_detalle
            WHERE fecha_base >= ?
              AND fecha_base <= ?
              AND operacion = ?
              AND (? = 'TODOS' OR almacen = ?)
              AND query_version = ?
            """,
            (expected[0], expected[-1], operacion, almacen, almacen, CASO_MODELO_DETALLE_QUERY_VERSION),
        )
        daily_total = await _fetch_one(
            db,
            """
            SELECT COUNT(*) rows,
                   COUNT(DISTINCT operario) legajos,
                   MAX(loaded_at) last_loaded_at
            FROM pp_caso_modelo_dia
            WHERE fecha_base >= ?
              AND fecha_base <= ?
              AND operacion = ?
              AND (? = 'TODOS' OR almacen = ?)
              AND query_version = ?
            """,
            (expected[0], expected[-1], operacion, almacen, almacen, CASO_MODELO_DIA_QUERY_VERSION),
        )
    cached = {row["fecha_base"]: int(row["rows"] or 0) for row in daily}
    missing = [day for day in expected if day not in cached]
    return {
        "fecha_desde": expected[0],
        "fecha_hasta": expected[-1],
        "operacion": operacion,
        "almacen": almacen,
        "db_path": str(PREMIO_DB_PATH),
        "query_versions": {
            "dia": CASO_MODELO_DIA_QUERY_VERSION,
            "detalle": CASO_MODELO_DETALLE_QUERY_VERSION,
        },
        "coverage": {
            "dias": len(expected),
            "dias_cache": len(cached),
            "dias_faltantes": len(missing),
            "faltantes": missing,
            "cache": [{"fecha": row["fecha_base"], "rows": row["rows"], "last_loaded_at": row["last_loaded_at"]} for row in daily],
        },
        "counts": {
            "pp_caso_modelo_dia_rows": int((daily_total or {}).get("rows") or 0),
            "pp_caso_modelo_dia_legajos": int((daily_total or {}).get("legajos") or 0),
            "pp_caso_modelo_dia_last_loaded_at": (daily_total or {}).get("last_loaded_at") or "",
            "pp_caso_modelo_detalle_rows": int((detail_count or {}).get("rows") or 0),
            "pp_caso_modelo_detalle_legajo_dias": int((detail_count or {}).get("legajo_dias") or 0),
            "pp_caso_modelo_detalle_last_loaded_at": (detail_count or {}).get("last_loaded_at") or "",
        },
        "procesos": [
            "Consultar rango valida cobertura diaria y carga desde Oracle solo los dias faltantes en pp_caso_modelo_dia.",
            "Abrir un legajo o ejecutar problematica enriquece pp_caso_modelo_detalle cuando falta detalle horario.",
            "Las versiones de query separan cache diario y cache de detalle para evitar mezclar datos viejos con datos recalculados.",
        ],
    }
