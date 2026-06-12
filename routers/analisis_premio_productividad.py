from __future__ import annotations

import csv
import io
import asyncio
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
from pydantic import BaseModel, Field

from db.paths import ROOT_DIR, resolve_db_path


router = APIRouter(prefix="/api/analisis-premio-productividad", tags=["analisis-premio-productividad"])
logger = logging.getLogger("vigia.analisis_premio_productividad")

PREMIO_DB_PATH = resolve_db_path("PREMIO_PRODUCTIVIDAD_DB_PATH", "premio_productividad.db", ROOT_DIR)
JORNADA_HORAS = 8
JAVA_HELPER_SRC = ROOT_DIR / "scripts" / "OracleProductividadQuery.java"
JAVA_BUILD_DIR = ROOT_DIR / "scripts" / "java_build"
CASO_MODELO_DIA_QUERY_VERSION = "premio_hora_v8"
CASO_MODELO_DETALLE_QUERY_VERSION = "premio_hora_v7"
CASO_MODELO_PREMIO_PRODUCTIVIDAD = {
    "nombre": "Caso modelo 2026-06-09 PICKING nivel 8",
    "fecha_desde": "2026-06-09",
    "fecha_hasta": "2026-06-09",
    "legajos": "198873, 203637, 206714, 207041, 207710, 733818, 734236",
    "operacion": "PICKING",
    "almacen": "",
    "grupo_productivo": "",
    "grupo_funciones_id": 1,
    "nivel": 8,
    "turno": "",
    "observacion": "Caso hardcodeado para evidenciar escala, pago actual y produccion WMS del ciclo 2026-06-09 06:00 a 2026-06-10 06:00.",
    "cargar_mock": True,
}

CONSULTA_ESCALA_PREMIOS = """
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
WHERE ID_DE_GRUPO_DE_FUNCIONES = :grupo_funciones_id
ORDER BY 1, 3, 4
"""

CONSULTA_PAGO_ACTUAL = """
SELECT
    A.FECHA,
    A.LEGAJO,
    D.DESCRIPCION AS OPERACION,
    C.PROD_REAL AS PRODUCTIVIDAD,
    B.A_PAGAR_TOTAL,
    B.ID_PV_UNIDAD_DE_PRODUCCION AS ULMEDIDA
FROM PV_DIA_LABORAL A
JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL
JOIN PV_LIQUIDAC_DIA_DET2 C ON A.ID = C.ID_PV_DIA_LABORAL
    AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES
JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES
JOIN PV_ESCALA_DE_PREMIOS E ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
    AND C.ID_PV_GRUPO_PRODUCTIVO = E.ID_DE_GRUPO_PRODUCTIVO
    AND B.OBJETIVO_NIVEL_ALCANZADO = E.NIVEL
WHERE A.FECHA = :fecha_yyyymmdd
  AND D.DESCRIPCION = :operacion
  AND E.NIVEL = :nivel
  AND A.LEGAJO IN (:legajos)
"""

CONSULTA_PRODUCCION_HORA = """
WITH TODO AS (
SELECT
    TO_CHAR(TO_DATE(:fecha_operativa, 'YYYY-MM-DD'), 'YYYY-MM-DD') AS fecha,
    TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) AS hora,
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
    TRUNC(FCREAREG),
    TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')),
    COPECREA,
    UPPER(CDESCRIP),
    CASE SUB1.DESCDIVI
        WHEN 'SECTOR SECOS' THEN 'SECOS + NOA '
        WHEN 'VARIOS NO ALIMENTOS' THEN 'SECOS + NOA '
        ELSE SUB1.DESCDIVI
    END
ORDER BY TO_NUMBER(TO_CHAR(FCREAREG, 'HH24'))
)
SELECT * FROM TODO
"""

CONSULTA_CASO_MODELO_FINAL = """
WITH ESCALAS AS (
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
        C.PROD_REAL/8,
        B.A_PAGAR_TOTAL,
        B.ID_PV_UNIDAD_DE_PRODUCCION,
        TURNO AS TURNOPROD
    FROM PV_DIA_LABORAL A
    JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL
    JOIN PV_LIQUIDAC_DIA_DET2 C ON A.ID = C.ID_PV_DIA_LABORAL AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES
    JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES
    JOIN PV_ESCALA_DE_PREMIOS E ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES AND C.ID_PV_GRUPO_PRODUCTIVO = E.ID_DE_GRUPO_PRODUCTIVO AND B.OBJETIVO_NIVEL_ALCANZADO = E.NIVEL
    JOIN PARAMS param ON A.FECHA = PARAM.FECHA_PREMIO
    WHERE D.DESCRIPCION = 'PICKING'
      AND B.ID_PV_GRUPO_PRODUCTIVO = 21
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
      AND UPPER(CDESCRIP) = 'PICKING'
    UNION ALL
    SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI
    FROM F132HIST_HIST A
    JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA
    WHERE COPECREA IN (SELECT LEGAJO FROM COMPARACION)
      AND (
          A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24)
          OR COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
      )
      AND UPPER(CDESCRIP) = 'PICKING'
      AND NOT EXISTS (
          SELECT 1
          FROM F132HIST X
          JOIN PARAMS P ON X.FCREAREG >= P.FECHA_DESDE AND X.FCREAREG <= P.FECHA_HASTA
          WHERE X.COPECREA IN (SELECT LEGAJO FROM COMPARACION)
            AND (
                X.FCREAREG <= P.FECHA_BASE + 1 + (6 / 24)
                OR X.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
            )
            AND UPPER(X.CDESCRIP) = 'PICKING'
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
        CASE SUB1.DESCDIVI
            WHEN 'SECTOR SECOS' THEN 'SECOS + NOA '
            WHEN 'VARIOS NO ALIMENTOS' THEN 'SECOS + NOA '
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
      AND UPPER(CDESCRIP) = 'PICKING'
    GROUP BY
        TRUNC(FECHA_DESDE),
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
    LEFT JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = 'SECOS + NOA '
        AND CANTIDAD > DESDE_X_HORA
        AND CANTIDAD <= B.HASTA_X_HORA
),
AGG AS (
    SELECT
        A.*,
        B.TURNOPROD,
        PROD_REAL AS PRODUCTIVIDAD_ANTERIOR,
        A_PAGAR_TOTAL AS PREMIO_ANTERIOR,
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
        SUM(PREMIO_NUEVO) AS PREMIO_X_HORAS,
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
SELECT
    A.*,
    B.PREMIO_ACTUAL,
    PREMIO_ANTERIOR - PREMIO_X_HORAS AS DIFERENCIA_X_HORAS,
    PREMIO_ANTERIOR - PREMIO_ACTUAL AS DIFERENCIA_SIN_EXTRAS
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
        F.DESCRIPCION AS GRUPOPRODUCTIVO,
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
    JOIN PARAMS PARAM ON A.FECHA = PARAM.FECHA_PREMIO
    WHERE D.DESCRIPCION = 'PICKING'
      AND B.ID_PV_GRUPO_PRODUCTIVO = 21
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
      AND UPPER(A.CDESCRIP) = 'PICKING'
    UNION ALL
    SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI
    FROM F132HIST_HIST A
    JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA
    WHERE A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION)
      AND (
          A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24)
          OR A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
      )
      AND UPPER(A.CDESCRIP) = 'PICKING'
      AND NOT EXISTS (
          SELECT 1
          FROM F132HIST X
          JOIN PARAMS P ON X.FCREAREG >= P.FECHA_DESDE AND X.FCREAREG <= P.FECHA_HASTA
          WHERE X.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION)
            AND (
                X.FCREAREG <= P.FECHA_BASE + 1 + (6 / 24)
                OR X.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')
            )
            AND UPPER(X.CDESCRIP) = 'PICKING'
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
        CASE SUB1.DESCDIVI
            WHEN 'SECTOR SECOS' THEN 'SECOS + NOA '
            WHEN 'VARIOS NO ALIMENTOS' THEN 'SECOS + NOA '
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
      AND UPPER(A.CDESCRIP) = 'PICKING'
    GROUP BY
        TRUNC(B.FECHA_DESDE),
        TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')),
        A.COPECREA,
        UPPER(A.CDESCRIP),
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
        ROUND(B.PREMIO_ACTUAL / 8, 2) AS PREMIO_NUEVO
    FROM TODO A
    LEFT JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = 'SECOS + NOA '
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
CREATE TABLE IF NOT EXISTS pp_simulacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    fecha_desde DATE NOT NULL,
    fecha_hasta DATE NOT NULL,
    legajos TEXT,
    operacion TEXT,
    almacen TEXT,
    grupo_funciones_id INTEGER,
    grupo_productivo TEXT,
    nivel INTEGER,
    turno TEXT,
    estado TEXT NOT NULL DEFAULT 'BORRADOR',
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    ultima_consulta_oracle DATETIME,
    origen_datos TEXT,
    observacion TEXT
);
CREATE TABLE IF NOT EXISTS pp_escala_diaria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacion_id INTEGER NOT NULL,
    operacion TEXT,
    almacen TEXT,
    ulmedida TEXT,
    grupo_productivo TEXT,
    nivel INTEGER,
    valor_minimo REAL NOT NULL,
    valor_maximo REAL NOT NULL,
    premio_diario REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pp_escala_horaria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacion_id INTEGER NOT NULL,
    operacion TEXT,
    almacen TEXT,
    ulmedida TEXT,
    grupo_productivo TEXT,
    nivel INTEGER,
    valor_minimo_hora REAL NOT NULL,
    valor_maximo_hora REAL NOT NULL,
    premio_hora REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pp_pago_actual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacion_id INTEGER NOT NULL,
    fecha DATE NOT NULL,
    legajo TEXT NOT NULL,
    nombre TEXT,
    operacion TEXT,
    almacen TEXT,
    turno TEXT,
    premio_actual REAL NOT NULL DEFAULT 0,
    nivel_actual TEXT,
    produccion_total_actual REAL NOT NULL DEFAULT 0,
    horas_trabajadas REAL,
    horas_extra REAL,
    datos_origen TEXT
);
CREATE TABLE IF NOT EXISTS pp_produccion_hora (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacion_id INTEGER NOT NULL,
    fecha DATE NOT NULL,
    legajo TEXT NOT NULL,
    nombre TEXT,
    operacion TEXT,
    almacen TEXT,
    turno TEXT,
    hora INTEGER NOT NULL,
    hora_inicio TEXT,
    hora_fin TEXT,
    produccion REAL NOT NULL DEFAULT 0,
    dentro_turno INTEGER NOT NULL DEFAULT 0,
    tipo_hora TEXT,
    premio_hora_simulado REAL NOT NULL DEFAULT 0,
    nivel_simulado TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pp_resultado_diario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacion_id INTEGER NOT NULL,
    fecha DATE NOT NULL,
    legajo TEXT NOT NULL,
    nombre TEXT,
    operacion TEXT,
    almacen TEXT,
    turno TEXT,
    produccion_total REAL NOT NULL DEFAULT 0,
    produccion_dentro_turno REAL NOT NULL DEFAULT 0,
    produccion_fuera_turno REAL NOT NULL DEFAULT 0,
    premio_actual REAL NOT NULL DEFAULT 0,
    premio_simulado_total REAL NOT NULL DEFAULT 0,
    premio_simulado_dentro_turno REAL NOT NULL DEFAULT 0,
    premio_simulado_fuera_turno REAL NOT NULL DEFAULT 0,
    diferencia_simulado_vs_actual REAL NOT NULL DEFAULT 0,
    diferencia_dentro_turno_vs_actual REAL NOT NULL DEFAULT 0,
    tiene_produccion_fuera_turno INTEGER NOT NULL DEFAULT 0,
    cantidad_horas_con_premio INTEGER NOT NULL DEFAULT 0,
    cantidad_horas_fuera_turno_con_premio INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pp_caso_modelo_final (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacion_id INTEGER NOT NULL,
    fecha DATE,
    operario TEXT,
    operacion TEXT,
    bultos REAL NOT NULL DEFAULT 0,
    almacen TEXT,
    premio_x_horas REAL NOT NULL DEFAULT 0,
    productividad_anterior REAL NOT NULL DEFAULT 0,
    premio_anterior REAL NOT NULL DEFAULT 0,
    bultosturno REAL NOT NULL DEFAULT 0,
    premio_actual REAL NOT NULL DEFAULT 0,
    diferencia_x_horas REAL NOT NULL DEFAULT 0,
    diferencia_sin_extras REAL NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
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
    premio_x_horas_sin_extras REAL NOT NULL DEFAULT 0,
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
CREATE TABLE IF NOT EXISTS pp_validacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacion_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    severidad TEXT NOT NULL DEFAULT 'WARN',
    mensaje TEXT NOT NULL,
    referencia TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pp_pago_sim ON pp_pago_actual(simulacion_id, fecha, legajo);
CREATE INDEX IF NOT EXISTS idx_pp_hora_sim ON pp_produccion_hora(simulacion_id, fecha, legajo);
CREATE INDEX IF NOT EXISTS idx_pp_resultado_sim ON pp_resultado_diario(simulacion_id, fecha, legajo);
CREATE INDEX IF NOT EXISTS idx_pp_caso_final_sim ON pp_caso_modelo_final(simulacion_id, fecha, operario);
CREATE INDEX IF NOT EXISTS idx_pp_caso_dia ON pp_caso_modelo_dia(fecha_base, operacion, query_version);
CREATE INDEX IF NOT EXISTS idx_pp_caso_detalle ON pp_caso_modelo_detalle(fecha_base, legajo, query_version);
"""


class SimulacionRequest(BaseModel):
    nombre: str = "Estudio premio productividad"
    fecha_desde: str
    fecha_hasta: str
    legajos: str = ""
    operacion: str = ""
    almacen: str = ""
    grupo_funciones_id: int = 1
    grupo_productivo: str = ""
    nivel: int | None = None
    turno: str = ""
    observacion: str = ""
    cargar_mock: bool = True


class SimulacionIdRequest(BaseModel):
    simulacion_id: int | None = None


class RangoCasoModeloRequest(BaseModel):
    fecha_desde: str
    fecha_hasta: str
    force: bool = False


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _upper(value: Any) -> str:
    return _clean(value).upper()


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


def _legajos(value: str) -> list[str]:
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def _fecha_oracle_key(value: str) -> str:
    return _to_date(value).strftime("%Y%m%d")


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


def _cycle_bounds(fecha_desde: str) -> tuple[str, str]:
    start = datetime.combine(_to_date(fecha_desde), datetime.min.time()).replace(hour=6)
    end = start + timedelta(days=1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


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
    if "BULTOS_HORA_MIN" in normalized and "BULTOSTURNO" in normalized:
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
        str(binds.get("fecha_operativa") or ""),
        str(binds.get("legajo") or ""),
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
        "pp_simulacion": [
            ("grupo_funciones_id", "INTEGER"),
            ("grupo_productivo", "TEXT"),
            ("nivel", "INTEGER"),
        ],
        "pp_escala_diaria": [
            ("ulmedida", "TEXT"),
            ("grupo_productivo", "TEXT"),
            ("nivel", "INTEGER"),
        ],
        "pp_escala_horaria": [
            ("ulmedida", "TEXT"),
            ("grupo_productivo", "TEXT"),
            ("nivel", "INTEGER"),
        ],
        "pp_caso_modelo_detalle": [
            ("premio_sin_extra", "REAL NOT NULL DEFAULT 0"),
            ("penalizacion_tnc", "TEXT NOT NULL DEFAULT ''"),
            ("penalizacion_error", "TEXT NOT NULL DEFAULT ''"),
        ],
        "pp_caso_modelo_dia": [
            ("premio_x_horas_sin_extras", "REAL NOT NULL DEFAULT 0"),
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


def _hora_bounds(fecha: str, hora: int) -> tuple[str, str]:
    start_date = _to_date(fecha)
    if hora < 6:
        start_date += timedelta(days=1)
    ini = datetime.combine(start_date, datetime.min.time()).replace(hour=hora)
    fin = ini + timedelta(hours=1)
    return ini.strftime("%Y-%m-%d %H:%M"), fin.strftime("%Y-%m-%d %H:%M")


def _match_escala(escalas: list[dict[str, Any]], operacion: str, almacen: str, produccion: float) -> dict[str, Any] | None:
    candidates = [
        row for row in escalas
        if _upper(row.get("operacion")) == _upper(operacion)
        and _upper(row.get("almacen")) == _upper(almacen)
        and float(row["valor_minimo_hora"]) <= produccion <= float(row["valor_maximo_hora"])
    ]
    if not candidates:
        candidates = [
            row for row in escalas
            if _upper(row.get("operacion")) == _upper(operacion)
            and float(row["valor_minimo_hora"]) <= produccion <= float(row["valor_maximo_hora"])
        ]
    return candidates[0] if candidates else None


async def obtenerPagoActual(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Ejecuta Oracle para premio actual, recortado al caso modelo."""
    legajos = _legajos(params.get("legajos") or "")
    if not legajos:
        raise HTTPException(status_code=400, detail="Para consultar Oracle indica al menos un legajo del caso.")
    if not params.get("nivel"):
        raise HTTPException(status_code=400, detail="Para pago actual indica el nivel a revisar.")
    operacion = _upper(params.get("operacion") or "PICKING")
    raw_rows = await asyncio.to_thread(
        _query_oracle,
        CONSULTA_PAGO_ACTUAL,
        {
            "fecha_yyyymmdd": _fecha_oracle_key(params["fecha_desde"]),
            "operacion": operacion,
            "nivel": int(params["nivel"]),
            "legajos": legajos,
        },
    )
    rows = []
    for row in raw_rows:
        rows.append({
            "fecha": _to_date(params["fecha_desde"]).isoformat(),
            "legajo": str(row.get("LEGAJO") or "").strip(),
            "nombre": "",
            "operacion": _upper(row.get("OPERACION") or operacion),
            "almacen": _clean(params.get("almacen") or params.get("grupo_productivo")),
            "turno": _clean(params.get("turno")),
            "premio_actual": _num(row.get("A_PAGAR_TOTAL")),
            "nivel_actual": str(params.get("nivel") or ""),
            "produccion_total_actual": _num(row.get("PRODUCTIVIDAD")),
            "horas_trabajadas": None,
            "horas_extra": None,
            "datos_origen": "oracle_pv_liquidacion",
        })
    return rows


async def obtenerEscalaPremios(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Ejecuta Oracle para escala completa por grupo de funciones."""
    raw_rows = await asyncio.to_thread(
        _query_oracle,
        CONSULTA_ESCALA_PREMIOS,
        {"grupo_funciones_id": int(params.get("grupo_funciones_id") or 1)},
    )
    rows = []
    for row in raw_rows:
        grupo = _clean(row.get("GRUPOPRODUCTIVO"))
        rows.append({
            "operacion": _upper(row.get("OPERACION")),
            "almacen": grupo,
            "ulmedida": _clean(row.get("ULMEDIDA")),
            "grupo_productivo": grupo,
            "nivel": int(_num(row.get("NIVEL"))),
            "valor_minimo": _num(row.get("DESDE_ACTUAL")),
            "valor_maximo": _num(row.get("HASTA_ACTUAL")),
            "premio_diario": _num(row.get("PREMIO_ACTUAL")),
        })
    return rows


async def obtenerProduccionHora(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Ejecuta Oracle para produccion WMS por hora, recortada al dataset del caso."""
    legajos = _legajos(params.get("legajos") or "")
    if not legajos:
        raise HTTPException(status_code=400, detail="Para consultar WMS indica al menos un legajo del caso.")
    fecha_ini, fecha_fin = _cycle_bounds(params["fecha_desde"])
    operacion = _upper(params.get("operacion") or "PICKING")
    raw_rows = await asyncio.to_thread(
        _query_oracle,
        CONSULTA_PRODUCCION_HORA,
        {
            "fecha_operativa": _to_date(params["fecha_desde"]).isoformat(),
            "fecha_ini": fecha_ini,
            "fecha_fin": fecha_fin,
            "legajos": legajos,
            "operacion": operacion,
        },
    )
    rows = []
    for row in raw_rows:
        rows.append({
            "fecha": _to_date(params["fecha_desde"]).isoformat(),
            "legajo": str(row.get("OPERARIO") or "").strip(),
            "nombre": "",
            "operacion": _upper(row.get("OPERACION") or operacion),
            "almacen": _clean(row.get("ALMACEN")),
            "turno": _clean(params.get("turno")),
            "hora": int(_num(row.get("HORA"))),
            "produccion": _num(row.get("CANTIDAD")),
        })
    return rows


async def obtenerCasoModeloFinal(params: dict[str, Any]) -> list[dict[str, Any]]:
    operacion = _upper(params.get("operacion") or "PICKING")
    raw_rows = await asyncio.to_thread(
        _query_oracle,
        CONSULTA_CASO_MODELO_RANGO,
        {
            "fecha_base": _to_date(params["fecha_desde"]).strftime("%Y/%m/%d"),
            "fecha_operativa": _to_date(params["fecha_desde"]).isoformat(),
            "operacion": operacion,
            "grupo_funciones_id": int(params.get("grupo_funciones_id") or 1),
        },
    )
    rows = []
    for row in raw_rows:
        rows.append({
            "fecha": _to_date(params["fecha_desde"]).isoformat(),
            "operario": str(row.get("OPERARIO") or "").strip(),
            "operacion": _upper(row.get("OPERACION") or operacion),
            "bultos": _num(row.get("BULTOS")),
            "almacen": _clean(row.get("ALMACEN")),
            "premio_x_horas": _num(row.get("PREMIO_X_HORAS")),
            "premio_x_horas_sin_extras": _num(row.get("PREMIO_X_HORAS_SIN_EXTRAS")),
            "productividad_anterior": _num(row.get("PRODUCTIVIDAD_ANTERIOR")),
            "premio_anterior": _num(row.get("PREMIO_ANTERIOR")),
            "bultosturno": _num(row.get("BULTOSTURNO")),
            "premio_actual": _num(row.get("PREMIO_ACTUAL")),
            "diferencia_x_horas": _num(row.get("DIFERENCIA_X_HORAS")),
            "diferencia_sin_extras": _num(row.get("DIFERENCIA_SIN_EXTRAS")),
            "diferencia_x_horas_sin_extras": _num(row.get("DIFERENCIA_X_HORAS_SIN_EXTRAS")),
        })
    unique = {}
    for row in rows:
        key = tuple(row.get(field) for field in [
            "fecha", "operario", "operacion", "bultos", "almacen", "premio_x_horas", "premio_x_horas_sin_extras",
            "productividad_anterior", "premio_anterior", "bultosturno", "premio_actual",
            "diferencia_x_horas", "diferencia_sin_extras", "diferencia_x_horas_sin_extras",
        ])
        unique[key] = row
    return list(unique.values())


async def _cache_rows_for_range(db: aiosqlite.Connection, fecha_desde: str, fecha_hasta: str) -> list[dict[str, Any]]:
    return await _fetch_rows(
        db,
        """
        SELECT fecha, operario, 'PICKING' AS operacion, bultos, almacen, premio_x_horas,
               premio_x_horas_sin_extras,
               productividad_anterior, premio_anterior, bultosturno, premio_actual,
               diferencia_x_horas, diferencia_sin_extras, diferencia_x_horas_sin_extras
        FROM pp_caso_modelo_dia
        WHERE fecha_base >= ?
          AND fecha_base <= ?
          AND operacion = 'PICKING'
          AND query_version = ?
        ORDER BY fecha_base, operario
        """,
        (fecha_desde, fecha_hasta, CASO_MODELO_DIA_QUERY_VERSION),
    )


async def _load_day_to_cache(db: aiosqlite.Connection, day: date, force: bool = False) -> dict[str, Any]:
    fecha_base = day.isoformat()
    existing = await _fetch_one(
        db,
        """
        SELECT COUNT(*) qty
        FROM pp_caso_modelo_dia
        WHERE fecha_base = ?
          AND operacion = 'PICKING'
          AND query_version = ?
        """,
        (fecha_base, CASO_MODELO_DIA_QUERY_VERSION),
    )
    if existing and int(existing["qty"] or 0) > 0 and not force:
        return {"fecha": fecha_base, "estado": "cache", "rows": int(existing["qty"])}

    if force:
        await db.execute(
            "DELETE FROM pp_caso_modelo_dia WHERE fecha_base = ? AND operacion = 'PICKING' AND query_version = ?",
            (fecha_base, CASO_MODELO_DIA_QUERY_VERSION),
        )

    rows = await obtenerCasoModeloFinal({
        "fecha_desde": fecha_base,
        "operacion": "PICKING",
        "grupo_funciones_id": 1,
    })
    await db.executemany(
        """
        INSERT INTO pp_caso_modelo_dia
            (fecha_base, operacion, query_version, fecha, operario, bultos, almacen,
             premio_x_horas, productividad_anterior, premio_anterior, bultosturno,
             premio_actual, premio_x_horas_sin_extras, diferencia_x_horas,
             diferencia_sin_extras, diferencia_x_horas_sin_extras, loaded_at)
        VALUES (?, 'PICKING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                fecha_base, CASO_MODELO_DIA_QUERY_VERSION, r["fecha"], r["operario"], r["bultos"], r["almacen"],
                r["premio_x_horas"], r["productividad_anterior"], r["premio_anterior"], r["bultosturno"],
                r["premio_actual"], r["premio_x_horas_sin_extras"], r["diferencia_x_horas"],
                r["diferencia_sin_extras"], r["diferencia_x_horas_sin_extras"], _now(),
            )
            for r in rows
        ],
    )
    return {"fecha": fecha_base, "estado": "oracle", "rows": len(rows)}


async def obtenerDetalleLegajo(params: dict[str, Any]) -> list[dict[str, Any]]:
    raw_rows = await asyncio.to_thread(
        _query_oracle,
        CONSULTA_CASO_MODELO_DETALLE,
        {
            "fecha_base": _to_date(params["fecha_base"]).strftime("%Y/%m/%d"),
            "fecha_operativa": _to_date(params["fecha_base"]).isoformat(),
            "legajo": str(params["legajo"]).strip(),
        },
    )
    rows = []
    for row in raw_rows:
        rows.append({
            "fecha": _to_date(params["fecha_base"]).isoformat(),
            "hora": int(_num(row.get("HORA"))),
            "turno": _clean(row.get("TURNO")),
            "operario": str(row.get("OPERARIO") or "").strip(),
            "nombre": _clean(row.get("NOMBRE")),
            "operacion": _upper(row.get("OPERACION") or "PICKING"),
            "bultos": _num(row.get("BULTOS")),
            "almacen": _clean(row.get("ALMACEN")),
            "bultos_hora_min": _num(row.get("BULTOS_HORA_MIN")),
            "bultos_hora_max": _num(row.get("BULTOS_HORA_MAX")),
            "premio_x_hora": _num(row.get("PREMIO_X_HORA")),
            "prod_modulo": _num(row.get("PROD_MODULO")),
            "pago_modulo": _num(row.get("PAGO_MODULO")),
            "bultos_modulo": _num(row.get("BULTOS_MODULO")),
            "bultosturno": _num(row.get("BULTOSTURNO")),
            "premio_sin_extra": _num(row.get("PREMIO_SIN_EXTRA")),
            "penalizacion_tnc": _clean(row.get("PENALIZACION_TNC")),
            "penalizacion_error": _clean(row.get("PENALIZACION_ERROR")),
        })
    return rows


async def _detalle_rows(db: aiosqlite.Connection, fecha_base: str, legajo: str) -> list[dict[str, Any]]:
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
          AND query_version = ?
        ORDER BY fecha, hora
        """,
        (fecha_base, legajo, CASO_MODELO_DETALLE_QUERY_VERSION),
    )


async def _load_detalle_to_cache(db: aiosqlite.Connection, fecha_base: str, legajo: str, force: bool = False) -> dict[str, Any]:
    rows = await _detalle_rows(db, fecha_base, legajo)
    if rows and not force:
        return {"estado": "cache", "rows": rows}
    await db.execute(
        "DELETE FROM pp_caso_modelo_detalle WHERE fecha_base = ? AND legajo = ? AND query_version = ?",
        (fecha_base, legajo, CASO_MODELO_DETALLE_QUERY_VERSION),
    )
    rows = await obtenerDetalleLegajo({"fecha_base": fecha_base, "legajo": legajo})
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


async def obtenerDatosTurno(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Reservado para enriquecer turnos/legajos desde Oracle si hiciera falta."""
    return []


async def _clear_detail(db: aiosqlite.Connection, simulacion_id: int) -> None:
    for table in ["pp_escala_diaria", "pp_escala_horaria", "pp_pago_actual", "pp_produccion_hora", "pp_resultado_diario", "pp_caso_modelo_final", "pp_caso_modelo_detalle", "pp_validacion"]:
        await db.execute(f"DELETE FROM {table} WHERE simulacion_id = ?", (simulacion_id,))


async def _load_oracle_data(db: aiosqlite.Connection, simulacion_id: int, params: dict[str, Any]) -> None:
    await _clear_detail(db, simulacion_id)
    escalas = await obtenerEscalaPremios(params)
    pagos = await obtenerPagoActual(params)
    horas = await obtenerProduccionHora(params)
    final_rows = await obtenerCasoModeloFinal(params)
    await db.executemany(
        """
        INSERT INTO pp_escala_diaria
            (simulacion_id, operacion, almacen, ulmedida, grupo_productivo, nivel, valor_minimo, valor_maximo, premio_diario)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                simulacion_id, r["operacion"], r["almacen"], r.get("ulmedida"), r.get("grupo_productivo"),
                r.get("nivel"), r["valor_minimo"], r["valor_maximo"], r["premio_diario"],
            )
            for r in escalas
        ],
    )
    await db.executemany(
        """
        INSERT INTO pp_escala_horaria
            (simulacion_id, operacion, almacen, ulmedida, grupo_productivo, nivel, valor_minimo_hora, valor_maximo_hora, premio_hora)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                simulacion_id, r["operacion"], r["almacen"], r.get("ulmedida"), r.get("grupo_productivo"), r.get("nivel"),
                round(r["valor_minimo"] / JORNADA_HORAS, 0),
                round(r["valor_maximo"] / JORNADA_HORAS, 0),
                round(r["premio_diario"] / JORNADA_HORAS, 0),
            )
            for r in escalas
        ],
    )
    await db.executemany(
        """
        INSERT INTO pp_pago_actual
            (simulacion_id, fecha, legajo, nombre, operacion, almacen, turno, premio_actual,
             nivel_actual, produccion_total_actual, horas_trabajadas, horas_extra, datos_origen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                simulacion_id, r["fecha"], r["legajo"], r["nombre"], r["operacion"], r["almacen"], r["turno"],
                r["premio_actual"], r["nivel_actual"], r["produccion_total_actual"], r["horas_trabajadas"],
                r["horas_extra"], r["datos_origen"],
            )
            for r in pagos
        ],
    )
    escala_hora = [
        {
            "operacion": r["operacion"], "almacen": r["almacen"],
            "valor_minimo_hora": round(r["valor_minimo"] / JORNADA_HORAS, 0),
            "valor_maximo_hora": round(r["valor_maximo"] / JORNADA_HORAS, 0),
            "premio_hora": round(r["premio_diario"] / JORNADA_HORAS, 0),
            "nivel": r.get("nivel"),
        }
        for r in escalas
    ]
    hora_rows = []
    for row in horas:
        hora = int(row["hora"])
        dentro = _within_shift(hora, row.get("turno"))
        tipo = _tipo_hora(hora, row.get("turno"))
        escala = _match_escala(escala_hora, row.get("operacion"), row.get("almacen"), float(row["produccion"]))
        premio = float(escala["premio_hora"]) if escala else 0
        nivel = f"N{escala.get('nivel')} {escala['valor_minimo_hora']:.2f}-{escala['valor_maximo_hora']:.2f}" if escala else "SIN_ESCALA"
        ini, fin = _hora_bounds(row["fecha"], hora)
        hora_rows.append((
            simulacion_id, row["fecha"], row["legajo"], row["nombre"], row["operacion"], row["almacen"], row["turno"],
            hora, ini, fin, row["produccion"], 1 if dentro else 0, tipo, premio, nivel,
        ))
    await db.executemany(
        """
        INSERT INTO pp_produccion_hora
            (simulacion_id, fecha, legajo, nombre, operacion, almacen, turno, hora, hora_inicio, hora_fin,
             produccion, dentro_turno, tipo_hora, premio_hora_simulado, nivel_simulado)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        hora_rows,
    )
    await db.executemany(
        """
        INSERT INTO pp_caso_modelo_final
            (simulacion_id, fecha, operario, operacion, bultos, almacen, premio_x_horas,
             productividad_anterior, premio_anterior, bultosturno, premio_actual,
             diferencia_x_horas, diferencia_sin_extras)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                simulacion_id, r["fecha"], r["operario"], r["operacion"], r["bultos"], r["almacen"],
                r["premio_x_horas"], r["productividad_anterior"], r["premio_anterior"],
                r["bultosturno"], r["premio_actual"], r["diferencia_x_horas"], r["diferencia_sin_extras"],
            )
            for r in final_rows
        ],
    )
    await db.execute(
        """
        UPDATE pp_simulacion
        SET estado = 'DATOS_CARGADOS', fecha_actualizacion = ?, ultima_consulta_oracle = ?, origen_datos = 'oracle_productiva_cache'
        WHERE id = ?
        """,
        (_now(), _now(), simulacion_id),
    )


async def _mark_simulation_error(db: aiosqlite.Connection, simulacion_id: int, exc: Exception) -> None:
    message = str(exc)[:900]
    await db.execute(
        """
        UPDATE pp_simulacion
        SET estado = 'ERROR', fecha_actualizacion = ?, observacion = ?
        WHERE id = ?
        """,
        (_now(), f"Error consultando Oracle: {message}", simulacion_id),
    )
    await _insert_validation(db, simulacion_id, "ORACLE_ERROR", f"No se pudo consultar Oracle: {message}", severidad="ERROR")


async def _insert_validation(db: aiosqlite.Connection, simulacion_id: int, tipo: str, mensaje: str, referencia: str = "", severidad: str = "WARN") -> None:
    await db.execute(
        "INSERT INTO pp_validacion (simulacion_id, tipo, severidad, mensaje, referencia) VALUES (?, ?, ?, ?, ?)",
        (simulacion_id, tipo, severidad, mensaje, referencia),
    )


async def _recalculate(db: aiosqlite.Connection, simulacion_id: int) -> None:
    await db.execute("DELETE FROM pp_resultado_diario WHERE simulacion_id = ?", (simulacion_id,))
    await db.execute("DELETE FROM pp_validacion WHERE simulacion_id = ?", (simulacion_id,))
    pagos = await _fetch_rows(db, "SELECT * FROM pp_pago_actual WHERE simulacion_id = ?", (simulacion_id,))
    horas = await _fetch_rows(db, "SELECT * FROM pp_produccion_hora WHERE simulacion_id = ?", (simulacion_id,))
    pagos_by_key = {(r["fecha"], str(r["legajo"])): r for r in pagos}
    horas_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in horas:
        horas_by_key[(row["fecha"], str(row["legajo"]))].append(row)
    for key, pago in pagos_by_key.items():
        day_hours = horas_by_key.get(key, [])
        if not day_hours:
            await _insert_validation(db, simulacion_id, "PAGO_SIN_PRODUCCION", "Hay pago actual sin produccion horaria.", f"{key[0]} {key[1]}")
        prod_total = sum(float(r["produccion"] or 0) for r in day_hours)
        prod_in = sum(float(r["produccion"] or 0) for r in day_hours if r["dentro_turno"])
        premio_total = sum(float(r["premio_hora_simulado"] or 0) for r in day_hours)
        premio_in = sum(float(r["premio_hora_simulado"] or 0) for r in day_hours if r["dentro_turno"])
        premio_out = premio_total - premio_in
        out_rows = [r for r in day_hours if not r["dentro_turno"] and float(r["produccion"] or 0) > 0]
        if out_rows:
            await _insert_validation(db, simulacion_id, "PRODUCCION_FUERA_TURNO", "Se detectan casos donde parte de la produccion que contribuye al resultado diario fue realizada fuera del turno asignado.", f"{key[0]} {key[1]}")
        if any((r.get("tipo_hora") or "") == "SIN_TURNO" for r in day_hours):
            await _insert_validation(db, simulacion_id, "PRODUCCION_SIN_TURNO", "Hay produccion sin turno asignado.", f"{key[0]} {key[1]}")
        if any((r.get("nivel_simulado") or "") == "SIN_ESCALA" for r in day_hours):
            await _insert_validation(db, simulacion_id, "ESCALA_FALTANTE", "Hay horas sin nivel de premio asignado.", f"{key[0]} {key[1]}")
        if any(float(r.get("produccion") or 0) < 0 or float(r.get("premio_hora_simulado") or 0) < 0 for r in day_hours):
            await _insert_validation(db, simulacion_id, "VALOR_NEGATIVO", "Hay valores negativos inesperados.", f"{key[0]} {key[1]}")
        await db.execute(
            """
            INSERT INTO pp_resultado_diario
                (simulacion_id, fecha, legajo, nombre, operacion, almacen, turno, produccion_total,
                 produccion_dentro_turno, produccion_fuera_turno, premio_actual, premio_simulado_total,
                 premio_simulado_dentro_turno, premio_simulado_fuera_turno, diferencia_simulado_vs_actual,
                 diferencia_dentro_turno_vs_actual, tiene_produccion_fuera_turno, cantidad_horas_con_premio,
                 cantidad_horas_fuera_turno_con_premio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                simulacion_id, pago["fecha"], pago["legajo"], pago["nombre"], pago["operacion"], pago["almacen"], pago["turno"],
                prod_total, prod_in, prod_total - prod_in, pago["premio_actual"], premio_total, premio_in, premio_out,
                premio_total - float(pago["premio_actual"] or 0), premio_in - float(pago["premio_actual"] or 0),
                1 if out_rows else 0,
                sum(1 for r in day_hours if float(r["premio_hora_simulado"] or 0) > 0),
                sum(1 for r in day_hours if not r["dentro_turno"] and float(r["premio_hora_simulado"] or 0) > 0),
            ),
        )
    for key in set(horas_by_key) - set(pagos_by_key):
        await _insert_validation(db, simulacion_id, "PRODUCCION_SIN_PAGO", "Hay produccion horaria sin pago actual.", f"{key[0]} {key[1]}")
    duplicates = await _fetch_rows(
        db,
        """
        SELECT fecha, legajo, hora, COUNT(*) qty
        FROM pp_produccion_hora
        WHERE simulacion_id = ?
        GROUP BY fecha, legajo, hora
        HAVING COUNT(*) > 1
        """,
        (simulacion_id,),
    )
    for row in duplicates:
        await _insert_validation(db, simulacion_id, "DUPLICADO", "Hay registros duplicados por fecha, legajo y hora.", f"{row['fecha']} {row['legajo']} hora {row['hora']}")
    multi_turno = await _fetch_rows(
        db,
        """
        SELECT fecha, legajo, COUNT(DISTINCT turno) qty
        FROM pp_pago_actual
        WHERE simulacion_id = ?
        GROUP BY fecha, legajo
        HAVING COUNT(DISTINCT turno) > 1
        """,
        (simulacion_id,),
    )
    for row in multi_turno:
        await _insert_validation(db, simulacion_id, "MULTI_TURNO", "Hay legajos con mas de un turno en la misma fecha.", f"{row['fecha']} {row['legajo']}")
    await db.execute(
        "UPDATE pp_simulacion SET estado = 'SIMULADA', fecha_actualizacion = ? WHERE id = ?",
        (_now(), simulacion_id),
    )


async def _active_id(db: aiosqlite.Connection) -> int | None:
    row = await _fetch_one(
        db,
        """
        SELECT s.id
        FROM pp_simulacion s
        ORDER BY
            CASE
                WHEN EXISTS (SELECT 1 FROM pp_escala_diaria e WHERE e.simulacion_id = s.id)
                 AND EXISTS (SELECT 1 FROM pp_pago_actual p WHERE p.simulacion_id = s.id)
                THEN 0 ELSE 1
            END,
            s.fecha_actualizacion DESC,
            s.id DESC
        LIMIT 1
        """,
    )
    return int(row["id"]) if row else None


async def _resolve_id(db: aiosqlite.Connection, simulacion_id: int | None = None) -> int:
    resolved = simulacion_id or await _active_id(db)
    if not resolved:
        raise HTTPException(status_code=404, detail="No hay simulacion activa.")
    return int(resolved)


def _sum(rows: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(row.get(key) or 0) for row in rows), 2)


def _group(rows: list[dict[str, Any]], key: str, fields: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "Sin dato")].append(row)
    return [
        {"grupo": group, "casos": len(items), **{field: _sum(items, field) for field in fields}}
        for group, items in sorted(grouped.items(), key=lambda item: _sum(item[1], fields[0]), reverse=True)
    ]


def _interpretacion(k: dict[str, Any]) -> list[str]:
    texts = []
    if k["premio_simulado_fuera_turno"] > 0:
        texts.append("Se detecta premio simulado generado por produccion fuera del turno asignado. Conviene analizar si corresponde mantener doble incentivo: pago de hora extra mas premio de productividad.")
    if k["premio_simulado_total"] < k["premio_actual_pagado"]:
        texts.append("El modelo horario simulado reduce el pago total frente al esquema vigente para el rango analizado.")
    elif k["premio_simulado_total"] > k["premio_actual_pagado"]:
        texts.append("El modelo horario simulado aumenta el pago total frente al esquema vigente para el rango analizado. Revisar casos donde el modelo actual podria estar castigando productividad horaria alta.")
    else:
        texts.append("El modelo horario simulado queda alineado con el pago actual para el rango analizado.")
    return texts


async def _table_counts(db: aiosqlite.Connection, simulacion_id: int) -> dict[str, int]:
    counts = {}
    for table in ["pp_escala_diaria", "pp_escala_horaria", "pp_pago_actual", "pp_produccion_hora", "pp_resultado_diario", "pp_caso_modelo_final", "pp_caso_modelo_detalle", "pp_validacion"]:
        row = await _fetch_one(db, f"SELECT COUNT(*) qty FROM {table} WHERE simulacion_id = ?", (simulacion_id,))
        counts[table] = int(row["qty"] if row else 0)
    return counts


def _has_case_model_data(counts: dict[str, int]) -> bool:
    return (
        counts.get("pp_escala_diaria", 0) > 0
        and counts.get("pp_pago_actual", 0) > 0
        and counts.get("pp_produccion_hora", 0) > 0
        and counts.get("pp_caso_modelo_final", 0) > 0
    )


@router.get("/simulaciones")
async def simulaciones():
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        return {"items": await _fetch_rows(db, "SELECT * FROM pp_simulacion ORDER BY fecha_actualizacion DESC, id DESC")}


@router.get("/consultas-modelo")
async def consultas_modelo():
    return {
        "escala_premios": CONSULTA_ESCALA_PREMIOS,
        "pago_actual": CONSULTA_PAGO_ACTUAL,
        "produccion_hora": CONSULTA_PRODUCCION_HORA,
        "parametros_caso_20260609": {
            "fecha_desde": "2026-06-09",
            "fecha_hasta": "2026-06-09",
            "fecha_ini": "2026-06-09 06:00:00",
            "fecha_fin": "2026-06-10 06:00:00",
            "legajos": ["198873", "203637", "206714", "207041", "207710", "733818", "734236"],
            "operacion": "PICKING",
            "grupo_funciones_id": 1,
            "nivel": 8,
        },
        "nota": "La produccion se imputa a fecha_desde del ciclo operativo 06:00 a 06:00, aunque haya tareas despues de medianoche.",
    }


@router.post("/simulaciones")
async def crear_simulacion(req: SimulacionRequest):
    await init_premio_productividad_db()
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            INSERT INTO pp_simulacion
                (nombre, fecha_desde, fecha_hasta, legajos, operacion, almacen, grupo_funciones_id,
                 grupo_productivo, nivel, turno, estado, origen_datos, observacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BORRADOR', 'cache_sqlite', ?)
            """,
            (
                req.nombre, req.fecha_desde, req.fecha_hasta, req.legajos, req.operacion, req.almacen,
                req.grupo_funciones_id, req.grupo_productivo, req.nivel, req.turno, req.observacion,
            ),
        )
        sim_id = int(cur.lastrowid)
        if req.cargar_mock:
            try:
                await _load_oracle_data(db, sim_id, req.model_dump())
                await _recalculate(db, sim_id)
            except Exception as exc:
                await _mark_simulation_error(db, sim_id, exc)
                await db.commit()
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(status_code=500, detail=f"No se pudo consultar Oracle: {exc}") from exc
        await db.commit()
    return {"ok": True, "id": sim_id}


@router.post("/caso-modelo")
async def cargar_caso_modelo(force: bool = Query(False)):
    await init_premio_productividad_db()
    params = SimulacionRequest(**CASO_MODELO_PREMIO_PRODUCTIVIDAD).model_dump()
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim = await _fetch_one(
            db,
            """
            SELECT *
            FROM pp_simulacion
            WHERE nombre = ?
            ORDER BY fecha_actualizacion DESC, id DESC
            LIMIT 1
            """,
            (params["nombre"],),
        )
        if sim and not force:
            counts = await _table_counts(db, int(sim["id"]))
            if sim["estado"] != "ERROR" and _has_case_model_data(counts):
                return {"ok": True, "id": int(sim["id"]), "simulacion": sim, "counts": counts, "loaded": False}

        cur = await db.execute(
            """
            INSERT INTO pp_simulacion
                (nombre, fecha_desde, fecha_hasta, legajos, operacion, almacen, grupo_funciones_id,
                 grupo_productivo, nivel, turno, estado, origen_datos, observacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BORRADOR', 'cache_sqlite', ?)
            """,
            (
                params["nombre"], params["fecha_desde"], params["fecha_hasta"], params["legajos"], params["operacion"],
                params["almacen"], params["grupo_funciones_id"], params["grupo_productivo"], params["nivel"],
                params["turno"], params["observacion"],
            ),
        )
        sim_id = int(cur.lastrowid)
        try:
            await _load_oracle_data(db, sim_id, params)
            await _recalculate(db, sim_id)
        except Exception as exc:
            await _mark_simulation_error(db, sim_id, exc)
            await db.commit()
            sim_error = await _fetch_one(db, "SELECT * FROM pp_simulacion WHERE id = ?", (sim_id,))
            counts = await _table_counts(db, sim_id)
            return {
                "ok": False,
                "id": sim_id,
                "simulacion": sim_error,
                "counts": counts,
                "loaded": False,
                "error": f"No se pudo consultar Oracle: {str(exc)[:900]}",
            }
        await db.commit()
        sim_loaded = await _fetch_one(db, "SELECT * FROM pp_simulacion WHERE id = ?", (sim_id,))
        counts = await _table_counts(db, sim_id)
    return {"ok": True, "id": sim_id, "simulacion": sim_loaded, "counts": counts, "loaded": True}


@router.get("/simulacion-activa")
async def simulacion_activa():
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _active_id(db)
        sim = await _fetch_one(db, "SELECT * FROM pp_simulacion WHERE id = ?", (sim_id,)) if sim_id else None
    return {"simulacion": sim}


@router.post("/consultar-oracle")
async def consultar_oracle(req: SimulacionIdRequest):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, req.simulacion_id)
        sim = await _fetch_one(db, "SELECT * FROM pp_simulacion WHERE id = ?", (sim_id,))
        try:
            await _load_oracle_data(db, sim_id, sim or {})
            await _recalculate(db, sim_id)
        except Exception as exc:
            await _mark_simulation_error(db, sim_id, exc)
            await db.commit()
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=f"No se pudo consultar Oracle: {exc}") from exc
        await db.commit()
    return {"ok": True, "id": sim_id}


@router.post("/recalcular")
async def recalcular(req: SimulacionIdRequest):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, req.simulacion_id)
        await _recalculate(db, sim_id)
        await db.commit()
    return {"ok": True, "id": sim_id}


@router.delete("/simulaciones/{simulacion_id}")
async def borrar_simulacion(simulacion_id: int):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        for table in ["pp_escala_diaria", "pp_escala_horaria", "pp_pago_actual", "pp_produccion_hora", "pp_resultado_diario", "pp_caso_modelo_final", "pp_caso_modelo_detalle", "pp_validacion", "pp_simulacion"]:
            await db.execute(f"DELETE FROM {table} WHERE {'id' if table == 'pp_simulacion' else 'simulacion_id'} = ?", (simulacion_id,))
        await db.commit()
    return {"ok": True}


@router.get("/resumen")
async def resumen(simulacion_id: int | None = Query(None)):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        sim = await _fetch_one(db, "SELECT * FROM pp_simulacion WHERE id = ?", (sim_id,))
        rows = await _fetch_rows(db, "SELECT * FROM pp_resultado_diario WHERE simulacion_id = ?", (sim_id,))
        validaciones = await _fetch_rows(db, "SELECT tipo, severidad, mensaje, referencia FROM pp_validacion WHERE simulacion_id = ? ORDER BY id DESC LIMIT 50", (sim_id,))
    kpis = {
        "premio_actual_pagado": _sum(rows, "premio_actual"),
        "premio_simulado_total": _sum(rows, "premio_simulado_total"),
        "premio_simulado_dentro_turno": _sum(rows, "premio_simulado_dentro_turno"),
        "premio_simulado_fuera_turno": _sum(rows, "premio_simulado_fuera_turno"),
        "diferencia_simulado_vs_actual": _sum(rows, "diferencia_simulado_vs_actual"),
        "diferencia_dentro_turno_vs_actual": _sum(rows, "diferencia_dentro_turno_vs_actual"),
        "legajo_dia_analizados": len(rows),
        "casos_con_produccion_fuera_turno": sum(1 for row in rows if row.get("tiene_produccion_fuera_turno")),
        "pct_premio_fuera_turno": round(_sum(rows, "premio_simulado_fuera_turno") / _sum(rows, "premio_simulado_total") * 100, 2) if _sum(rows, "premio_simulado_total") else 0,
        "produccion_total": _sum(rows, "produccion_total"),
        "produccion_dentro_turno": _sum(rows, "produccion_dentro_turno"),
        "produccion_fuera_turno": _sum(rows, "produccion_fuera_turno"),
    }
    return {
        "simulacion": sim,
        "kpis": kpis,
        "interpretacion": _interpretacion(kpis),
        "validaciones": validaciones,
        "graficos": {
            "comparativo_premio": [
                {"grupo": "Actual", "valor": kpis["premio_actual_pagado"]},
                {"grupo": "Simulado total", "valor": kpis["premio_simulado_total"]},
                {"grupo": "Dentro turno", "valor": kpis["premio_simulado_dentro_turno"]},
            ],
            "dentro_fuera": [
                {"grupo": "Dentro turno", "valor": kpis["premio_simulado_dentro_turno"]},
                {"grupo": "Fuera turno", "valor": kpis["premio_simulado_fuera_turno"]},
            ],
            "distribucion_diferencia": [
                {"grupo": "Cobra mas", "valor": sum(1 for r in rows if float(r["diferencia_simulado_vs_actual"] or 0) > 0)},
                {"grupo": "Cobra igual", "valor": sum(1 for r in rows if float(r["diferencia_simulado_vs_actual"] or 0) == 0)},
                {"grupo": "Cobra menos", "valor": sum(1 for r in rows if float(r["diferencia_simulado_vs_actual"] or 0) < 0)},
            ],
        },
    }


@router.get("/caso-modelo-final")
async def caso_modelo_final(simulacion_id: int | None = Query(None)):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        sim = await _fetch_one(db, "SELECT * FROM pp_simulacion WHERE id = ?", (sim_id,))
        rows = await _fetch_rows(
            db,
            """
            SELECT fecha, operario, operacion, bultos, almacen, premio_x_horas,
                   productividad_anterior, premio_anterior, bultosturno, premio_actual,
                   diferencia_x_horas, diferencia_sin_extras
            FROM pp_caso_modelo_final
            WHERE simulacion_id = ?
            ORDER BY operario
            """,
            (sim_id,),
        )
    kpis = {
        "premio_anterior": _sum(rows, "premio_anterior"),
        "premio_x_horas": _sum(rows, "premio_x_horas"),
        "premio_actual": _sum(rows, "premio_actual"),
        "diferencia_x_horas": _sum(rows, "diferencia_x_horas"),
        "diferencia_sin_extras": _sum(rows, "diferencia_sin_extras"),
        "operarios": len(rows),
        "bultos": _sum(rows, "bultos"),
        "bultosturno": _sum(rows, "bultosturno"),
    }
    return {
        "simulacion": sim,
        "kpis": kpis,
        "rows": rows,
        "graficos": {
            "comparativo": [
                {"grupo": "Pagado actual", "valor": kpis["premio_anterior"]},
                {"grupo": "Por hora", "valor": kpis["premio_x_horas"]},
                {"grupo": "Solo turno", "valor": kpis["premio_actual"]},
            ],
            "ahorros": [
                {"grupo": "Diferencia por horas", "valor": kpis["diferencia_x_horas"]},
                {"grupo": "Diferencia sin extras", "valor": kpis["diferencia_sin_extras"]},
            ],
        },
    }


def _caso_modelo_payload(rows: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    extra_rows = [
        row for row in rows
        if max(0, float(row.get("bultos") or 0) - float(row.get("bultosturno") or 0)) > 0
    ]
    kpis = {
        "premio_anterior": _sum(rows, "premio_anterior"),
        "premio_x_horas": _sum(rows, "premio_x_horas"),
        "premio_x_horas_sin_extras": _sum(rows, "premio_x_horas_sin_extras"),
        "premio_actual": _sum(rows, "premio_actual"),
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
    return {
        "meta": meta or {},
        "kpis": kpis,
        "rows": rows,
        "graficos": {
            "comparativo": [
                {"grupo": "Pagado actual", "valor": kpis["premio_anterior"]},
                {"grupo": "Sin extras", "valor": kpis["premio_actual"]},
                {"grupo": "Por horas", "valor": kpis["premio_x_horas"]},
                {"grupo": "Por horas sin extras", "valor": kpis["premio_x_horas_sin_extras"]},
            ],
            "ahorros": [
                {"grupo": "Diferencia sin extras", "valor": kpis["diferencia_sin_extras"]},
                {"grupo": "Diferencia por horas", "valor": kpis["diferencia_x_horas"]},
                {"grupo": "Diferencia por horas sin extras", "valor": kpis["diferencia_x_horas_sin_extras"]},
            ],
        },
    }


@router.post("/consultar-rango")
async def consultar_rango(req: RangoCasoModeloRequest):
    await init_premio_productividad_db()
    days = _date_range_inclusive(req.fecha_desde, req.fecha_hasta)
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        estados = []
        for day in days:
            estados.append(await _load_day_to_cache(db, day, force=req.force))
            await db.commit()
        rows = await _cache_rows_for_range(db, days[0].isoformat(), days[-1].isoformat())
    meta = {
        "fecha_desde": days[0].isoformat(),
        "fecha_hasta": days[-1].isoformat(),
        "dias": len(days),
        "dias_oracle": sum(1 for row in estados if row["estado"] == "oracle"),
        "dias_cache": sum(1 for row in estados if row["estado"] == "cache"),
        "detalle_dias": estados,
        "query_version": CASO_MODELO_DIA_QUERY_VERSION,
        "origen": "cache_sqlite",
    }
    return _caso_modelo_payload(rows, meta)


@router.get("/rango-cache")
async def rango_cache(fecha_desde: str = Query(...), fecha_hasta: str = Query(...)):
    days = _date_range_inclusive(fecha_desde, fecha_hasta)
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _cache_rows_for_range(db, days[0].isoformat(), days[-1].isoformat())
    return _caso_modelo_payload(rows, {
        "fecha_desde": days[0].isoformat(),
        "fecha_hasta": days[-1].isoformat(),
        "dias": len(days),
        "query_version": CASO_MODELO_DIA_QUERY_VERSION,
        "origen": "cache_sqlite",
    })


@router.get("/cache-cobertura")
async def cache_cobertura(fecha_desde: str = Query(...), fecha_hasta: str = Query(...)):
    days = _date_range_inclusive(fecha_desde, fecha_hasta)
    expected = [day.isoformat() for day in days]
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cached_rows = await _fetch_rows(
            db,
            """
            SELECT fecha_base, COUNT(*) rows
            FROM pp_caso_modelo_dia
            WHERE fecha_base >= ?
              AND fecha_base <= ?
              AND operacion = 'PICKING'
              AND query_version = ?
            GROUP BY fecha_base
            ORDER BY fecha_base
            """,
            (expected[0], expected[-1], CASO_MODELO_DIA_QUERY_VERSION),
        )
    cached = {row["fecha_base"]: int(row["rows"] or 0) for row in cached_rows}
    missing = [day for day in expected if day not in cached]
    return {
        "fecha_desde": expected[0],
        "fecha_hasta": expected[-1],
        "dias": len(expected),
        "dias_cache": len(cached),
        "dias_faltantes": len(missing),
        "faltantes": missing,
        "cache": [{"fecha": day, "rows": cached[day]} for day in expected if day in cached],
        "query_version": CASO_MODELO_DIA_QUERY_VERSION,
    }


@router.get("/detalle-legajo")
async def detalle_legajo(fecha: str = Query(...), legajo: str = Query(...), force: bool = False):
    fecha_base = _to_date(fecha).isoformat()
    legajo = _clean(legajo)
    if not legajo:
        raise HTTPException(status_code=400, detail="Indica un legajo.")
    await init_premio_productividad_db()
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        loaded = await _load_detalle_to_cache(db, fecha_base, legajo, force=force)
        await db.commit()
    rows = loaded["rows"]
    return {
        "meta": {
            "fecha": fecha_base,
            "legajo": legajo,
            "origen": loaded["estado"],
            "query_version": CASO_MODELO_DETALLE_QUERY_VERSION,
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


@router.get("/modelo-actual")
async def modelo_actual(simulacion_id: int | None = Query(None)):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        pagos = await _fetch_rows(db, "SELECT * FROM pp_pago_actual WHERE simulacion_id = ?", (sim_id,))
        resultados = await _fetch_rows(db, "SELECT * FROM pp_resultado_diario WHERE simulacion_id = ?", (sim_id,))
    premiados = [row for row in pagos if float(row.get("premio_actual") or 0) > 0]
    return {
        "kpis": {
            "total_pagado": _sum(pagos, "premio_actual"),
            "cantidad_premiados": len(premiados),
            "premio_promedio": round(_sum(pagos, "premio_actual") / len(premiados), 2) if premiados else 0,
            "casos_fuera_turno": sum(1 for row in resultados if row.get("tiene_produccion_fuera_turno")),
        },
        "por_operacion": _group(pagos, "operacion", ["premio_actual", "produccion_total_actual"]),
        "por_almacen": _group(pagos, "almacen", ["premio_actual", "produccion_total_actual"]),
        "por_turno": _group(pagos, "turno", ["premio_actual", "produccion_total_actual"]),
        "por_nivel": _group(pagos, "nivel_actual", ["premio_actual", "produccion_total_actual"]),
        "ranking_premio_actual": sorted(pagos, key=lambda row: float(row["premio_actual"] or 0), reverse=True)[:50],
        "ranking_fuera_turno": sorted(resultados, key=lambda row: float(row["produccion_fuera_turno"] or 0), reverse=True)[:50],
        "detalle": resultados,
    }


@router.get("/escala")
async def escala(simulacion_id: int | None = Query(None)):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        rows = await _fetch_rows(
            db,
            """
            SELECT d.operacion AS OPERACION,
                   d.ulmedida AS ULMEDIDA,
                   COALESCE(d.grupo_productivo, d.almacen) AS GRUPOPRODUCTIVO,
                   d.nivel AS NIVEL,
                   d.valor_minimo AS DESDE_ACTUAL,
                   d.valor_maximo AS HASTA_ACTUAL,
                   d.premio_diario AS PREMIO_ACTUAL,
                   h.valor_minimo_hora AS DESDE_X_HORA,
                   h.valor_maximo_hora AS HASTA_X_HORA,
                   h.premio_hora AS PREMIO_X_HORA
            FROM pp_escala_diaria d
            JOIN pp_escala_horaria h
              ON h.simulacion_id = d.simulacion_id
             AND h.operacion = d.operacion
             AND h.almacen = d.almacen
             AND h.nivel = d.nivel
            WHERE d.simulacion_id = ?
            ORDER BY d.operacion, GRUPOPRODUCTIVO, d.nivel
            """,
            (sim_id,),
        )
    return {
        "rows": rows,
        "regla": "Resultado de la escala actual de premios y su fragmentacion horaria: DESDE_X_HORA, HASTA_X_HORA y PREMIO_X_HORA se calculan con ROUND(valor/8, 0).",
        "columnas_origen": ["OPERACION", "ULMEDIDA", "GRUPOPRODUCTIVO", "NIVEL", "DESDE_ACTUAL", "HASTA_ACTUAL", "PREMIO_ACTUAL"],
        "columnas_simuladas": ["DESDE_X_HORA", "HASTA_X_HORA", "PREMIO_X_HORA"],
    }


@router.get("/simulacion-hora")
async def simulacion_hora(simulacion_id: int | None = Query(None)):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        rows = await _fetch_rows(db, "SELECT * FROM pp_resultado_diario WHERE simulacion_id = ?", (sim_id,))
    fields = ["premio_actual", "premio_simulado_total", "premio_simulado_dentro_turno", "premio_simulado_fuera_turno", "diferencia_simulado_vs_actual", "diferencia_dentro_turno_vs_actual"]
    return {
        "general": {field: _sum(rows, field) for field in fields},
        "por_operacion": _group(rows, "operacion", fields),
        "por_almacen": _group(rows, "almacen", fields),
        "por_turno": _group(rows, "turno", fields),
        "por_legajo": _group(rows, "legajo", fields),
    }


@router.get("/comparacion-diaria")
async def comparacion_diaria(
    simulacion_id: int | None = Query(None),
    fecha: str = "",
    legajo: str = "",
    turno: str = "",
    operacion: str = "",
    almacen: str = "",
    solo_fuera_turno: bool = False,
    solo_positivas: bool = False,
    solo_negativas: bool = False,
):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        rows = await _fetch_rows(db, "SELECT * FROM pp_resultado_diario WHERE simulacion_id = ? ORDER BY fecha DESC, legajo", (sim_id,))
    def ok(row: dict[str, Any]) -> bool:
        return (
            (not fecha or row["fecha"] == fecha)
            and (not legajo or legajo in str(row["legajo"]))
            and (not turno or _upper(row["turno"]) == _upper(turno))
            and (not operacion or _upper(row["operacion"]) == _upper(operacion))
            and (not almacen or _upper(row["almacen"]) == _upper(almacen))
            and (not solo_fuera_turno or bool(row["tiene_produccion_fuera_turno"]))
            and (not solo_positivas or float(row["diferencia_simulado_vs_actual"] or 0) > 0)
            and (not solo_negativas or float(row["diferencia_simulado_vs_actual"] or 0) < 0)
        )
    return {"rows": [row for row in rows if ok(row)]}


@router.get("/detalle-hora")
async def detalle_hora(simulacion_id: int | None = Query(None), legajo: str = "", fecha: str = ""):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        rows = await _fetch_rows(db, "SELECT * FROM pp_produccion_hora WHERE simulacion_id = ? ORDER BY fecha DESC, legajo, hora_inicio", (sim_id,))
    return {"rows": [row for row in rows if (not legajo or legajo in str(row["legajo"])) and (not fecha or row["fecha"] == fecha)]}


@router.get("/impacto-fuera-turno")
async def impacto_fuera_turno(simulacion_id: int | None = Query(None)):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        rows = await _fetch_rows(db, "SELECT * FROM pp_resultado_diario WHERE simulacion_id = ?", (sim_id,))
    fields = ["premio_simulado_fuera_turno", "produccion_fuera_turno", "cantidad_horas_fuera_turno_con_premio"]
    return {
        "por_legajo": _group(rows, "legajo", fields),
        "por_fecha": _group(rows, "fecha", fields),
        "por_operacion": _group(rows, "operacion", fields),
        "por_almacen": _group(rows, "almacen", fields),
        "ranking": sorted(rows, key=lambda row: float(row["premio_simulado_fuera_turno"] or 0), reverse=True)[:50],
    }


@router.get("/datos-cache")
async def datos_cache(simulacion_id: int | None = Query(None)):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        sim = await _fetch_one(db, "SELECT * FROM pp_simulacion WHERE id = ?", (sim_id,))
        counts = await _table_counts(db, sim_id)
    return {"simulacion": sim, "counts": counts, "db_path": str(PREMIO_DB_PATH), "cache_estado": "OK" if sim else "SIN_DATOS"}


def _csv_response(filename: str, rows: list[dict[str, Any]]) -> StreamingResponse:
    output = io.StringIO()
    if rows:
        fieldnames: list[str] = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write("sin_datos\n")
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export")
async def export(tipo: str = Query("resumen"), simulacion_id: int | None = Query(None)):
    async with aiosqlite.connect(PREMIO_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sim_id = await _resolve_id(db, simulacion_id)
        if tipo == "modelo-actual":
            rows = await _fetch_rows(db, "SELECT * FROM pp_pago_actual WHERE simulacion_id = ?", (sim_id,))
        elif tipo == "comparacion-diaria":
            rows = await _fetch_rows(db, "SELECT * FROM pp_resultado_diario WHERE simulacion_id = ?", (sim_id,))
        elif tipo == "detalle-hora":
            rows = await _fetch_rows(db, "SELECT * FROM pp_produccion_hora WHERE simulacion_id = ?", (sim_id,))
        elif tipo == "impacto-fuera-turno":
            rows = await _fetch_rows(db, "SELECT * FROM pp_resultado_diario WHERE simulacion_id = ? AND premio_simulado_fuera_turno > 0", (sim_id,))
        else:
            data = await resumen(sim_id)
            rows = [{"indicador": key, "valor": value} for key, value in data["kpis"].items()]
    return _csv_response(f"premio_productividad_{tipo}.csv", rows)
