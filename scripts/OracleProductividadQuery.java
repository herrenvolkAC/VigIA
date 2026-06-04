import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Timestamp;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

public class OracleProductividadQuery {
    private static final DateTimeFormatter TS_FMT =
        DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss").withZone(ZoneId.systemDefault());

    private static String esc(String value) {
        if (value == null) return "";
        return value
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\r", "\\r")
            .replace("\n", "\\n");
    }

    private static String str(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private static String num(Object value) {
        if (value == null) return "0";
        if (value instanceof Number) return value.toString();
        try {
            return Double.toString(Double.parseDouble(String.valueOf(value)));
        } catch (Exception e) {
            return "0";
        }
    }

    private static boolean hasColumn(ResultSet rs, String column) {
        try {
            rs.findColumn(column);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private static void appendGenericJsonRow(ResultSet rs, StringBuilder out) throws Exception {
        var meta = rs.getMetaData();
        int columns = meta.getColumnCount();
        out.append("{");
        for (int i = 1; i <= columns; i++) {
            if (i > 1) out.append(",");
            String name = meta.getColumnLabel(i);
            Object value = rs.getObject(i);
            out.append("\"").append(esc(name)).append("\":");
            if (value == null) {
                out.append("null");
            } else if (value instanceof Number) {
                out.append(num(value));
            } else if (value instanceof Timestamp) {
                out.append("\"").append(esc(TS_FMT.format(((Timestamp) value).toInstant()))).append("\"");
            } else {
                out.append("\"").append(esc(str(value))).append("\"");
            }
        }
        out.append("}");
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 5) {
            System.err.println("Uso: OracleProductividadQuery <jdbcUrl> <user> <password> <fechaDesde> <fechaHasta> [queryKey]");
            System.exit(2);
        }

        String jdbcUrl = args[0];
        String user = args[1];
        String password = args[2];
        String fechaDesde = args[3];
        String fechaHasta = args[4];
        String queryKey = args.length >= 6 ? args[5] : "productividad";
        String legajo = args.length >= 7 ? args[6] : "";

        String sql;
        if ("picking_analysis".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CZONAORI AS ZONA_ORIGEN, " +
                "    A.CUBIORIG AS UBIC_ORIGEN, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.QCANTIDA AS CANTIDAD, " +
                "    A.QPESOREG AS PESO, " +
                "    A.CREFEREN AS REFERENCIA " +
                "FROM F132HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN ( " +
                "    SELECT DISTINCT CZONALMA, DESCDIVI " +
                "    FROM VW_UBICACIONES_DIVISION " +
                ") SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND UPPER(A.CDESCRIP) = 'PICKING' " +
                "ORDER BY A.COPECREA, A.FCREAREG";
        } else if ("daily_picking_real".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH prm AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to
                  FROM dual
                ),
                pck AS (
                  SELECT
                    h.COPECREA,
                    h.QCANTIDA,
                    CASE
                      WHEN UPPER(TRIM(h.CZONAORI)) = 'T06' THEN 4
                      WHEN h.CZONAORI IS NOT NULL
                       AND INSTR(UPPER(TRIM(h.CZONAORI)), 'T') > 0 THEN 2
                      WHEN UPPER(TRIM(h.CZONAORI)) IN ('N01','N02','N04','N05','N07','N09','N10','N15') THEN 6
                      ELSE 1
                    END AS division
                  FROM f132hist h
                  WHERE h.FCREAREG >= (SELECT p_from FROM prm)
                    AND h.FCREAREG <  (SELECT p_to FROM prm)
                    AND h.CDESCRIP = 'Picking'
                )
                SELECT
                  CASE division
                    WHEN 1 THEN 'SECOS'
                    WHEN 2 THEN 'REFRIGERADOS'
                    WHEN 4 THEN 'REFRIGERADOS'
                    WHEN 6 THEN 'NOA'
                  END AS ALMACEN,
                  COUNT(DISTINCT COPECREA) AS LEGAJOS,
                  SUM(QCANTIDA) AS BULTOS,
                  ROUND(SUM(QCANTIDA) / COUNT(DISTINCT COPECREA), 2) AS PRODUCCION
                FROM pck
                GROUP BY CASE division
                  WHEN 1 THEN 'SECOS'
                  WHEN 2 THEN 'REFRIGERADOS'
                  WHEN 4 THEN 'REFRIGERADOS'
                  WHEN 6 THEN 'NOA'
                END
                """;
        } else if ("daily_despacho_real".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH params AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to
                  FROM dual
                ),
                base AS (
                  SELECT
                    t.hojaruta,
                    t.cargador AS legajo_cargador,
                    CASE
                      WHEN t.cdivisio IN (1,6) THEN 1
                      WHEN t.cdivisio IN (2,4) THEN 2
                      ELSE NULL
                    END AS division
                  FROM f922traf t
                  WHERE t.inicarga >= (SELECT p_from FROM params)
                    AND t.inicarga <  (SELECT p_to FROM params)
                    AND t.calmacen IN ('093','93')
                )
                SELECT
                  CASE division
                    WHEN 1 THEN 'SECOS'
                    WHEN 2 THEN 'REFRIGERADOS'
                  END AS ALMACEN,
                  COUNT(DISTINCT legajo_cargador) AS LEGAJOS,
                  COUNT(DISTINCT hojaruta) AS VIAJES,
                  ROUND(COUNT(DISTINCT hojaruta) / COUNT(DISTINCT legajo_cargador), 2) AS PRODUCCION
                FROM base
                WHERE division IN (1, 2)
                GROUP BY CASE division
                  WHEN 1 THEN 'SECOS'
                  WHEN 2 THEN 'REFRIGERADOS'
                END
                """;
        } else if ("daily_picking_plan".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH params AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to
                  FROM dual
                ),
                base AS (
                  SELECT
                    v.CODIGO,
                    v.FECHAYHORADEINICIO,
                    (v.FECHAYHORADEINICIO - INTERVAL '2' HOUR) AS FECHA_ARMADO_PLAN,
                    TRUNC((v.FECHAYHORADEINICIO - INTERVAL '2' HOUR) - INTERVAL '6' HOUR) AS dia_operativo,
                    CASE
                      WHEN v.CODIGODETIPODEDARSENA IN (1, 2, 6) THEN v.CODIGODETIPODEDARSENA
                      ELSE NULL
                    END AS division
                  FROM TR_VIAJE v, params p
                  WHERE v.FECHAYHORADEINICIO >= p.p_from
                    AND v.FECHAYHORADEINICIO <  p.p_to
                ),
                viaje_pallet AS (
                  SELECT
                    m.CODIGO AS CODIGODEVIAJE,
                    m.division,
                    c.NUMERODEPALLET AS PALLET_ID,
                    NVL(
                      (SELECT SUM(d.cantidad)
                       FROM TR_DETALLE_DE_PALLET_NEW d
                       WHERE d.pallet_id = p.NUMERO),
                      0
                    ) AS bultos_pallet
                  FROM base m
                  JOIN TR_CARGAS c ON m.CODIGO = c.CODIGODEVIAJE
                  JOIN TR_PALLET p ON c.NUMERODEPALLET = p.NUMERO
                  WHERE UPPER(p.TIPO) IN ('PALLET DE PICKING','PALLET DE PICKING (CONSOLIDADO)')
                )
                SELECT
                  CASE division
                    WHEN 1 THEN 'SECOS'
                    WHEN 2 THEN 'REFRIGERADOS'
                    WHEN 6 THEN 'NOA'
                  END AS ALMACEN,
                  SUM(bultos_pallet) AS BULTOS_PLANIFICADOS,
                  COUNT(DISTINCT CODIGODEVIAJE) AS VIAJES_PLANIFICADOS,
                  COUNT(DISTINCT PALLET_ID) AS PALLETS_PICKING_PLANIFICADOS
                FROM viaje_pallet
                WHERE division IN (1, 2, 6)
                GROUP BY CASE division
                  WHEN 1 THEN 'SECOS'
                  WHEN 2 THEN 'REFRIGERADOS'
                  WHEN 6 THEN 'NOA'
                END
                """;
        } else if ("daily_despacho_plan".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH params AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to
                  FROM dual
                ),
                base AS (
                  SELECT
                    v.CODIGO,
                    CASE
                      WHEN v.CODIGODETIPODEDARSENA = 1 THEN 1
                      WHEN v.CODIGODETIPODEDARSENA = 2 THEN 2
                      ELSE NULL
                    END AS division
                  FROM TR_VIAJE v
                  WHERE v.FECHAYHORADEINICIO >= (SELECT p_from FROM params)
                    AND v.FECHAYHORADEINICIO <  (SELECT p_to FROM params)
                )
                SELECT
                  CASE division
                    WHEN 1 THEN 'SECOS'
                    WHEN 2 THEN 'REFRIGERADOS'
                  END AS ALMACEN,
                  COUNT(*) AS VIAJES_PLANIFICADOS
                FROM base
                WHERE division IN (1, 2)
                GROUP BY CASE division
                  WHEN 1 THEN 'SECOS'
                  WHEN 2 THEN 'REFRIGERADOS'
                END
                """;
        } else if ("daily_spc_plan".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH params AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to
                  FROM dual
                ),
                base AS (
                  SELECT
                    v.CODIGO,
                    v.FECHAYHORADEINICIO,
                    v.CODIGODETIPODEDARSENA,
                    (v.FECHAYHORADEINICIO - INTERVAL '2' HOUR) AS FECHA_ARMADO_PLAN,
                    CASE
                      WHEN v.CODIGODETIPODEDARSENA = 1 THEN 1
                      WHEN v.CODIGODETIPODEDARSENA = 2 THEN 2
                      ELSE NULL
                    END AS division
                  FROM TR_VIAJE v
                  WHERE v.FECHAYHORADEINICIO >= (SELECT p_from FROM params)
                    AND v.FECHAYHORADEINICIO <  (SELECT p_to FROM params)
                ),
                viaje_pallet AS (
                  SELECT
                    m.division,
                    m.CODIGO AS CODIGODEVIAJE,
                    c.NUMERODEPALLET AS PALLET_ID,
                    p.TIPO
                  FROM base m
                  JOIN TR_CARGAS c
                    ON m.CODIGO = c.CODIGODEVIAJE
                  JOIN TR_PALLET p
                    ON c.NUMERODEPALLET = p.NUMERO
                ),
                no_picking AS (
                  SELECT *
                  FROM viaje_pallet
                  WHERE UPPER(TIPO) NOT IN ('PALLET DE PICKING','PALLET DE PICKING (CONSOLIDADO)')
                )
                SELECT
                  CASE division
                    WHEN 1 THEN 'SECOS'
                    WHEN 2 THEN 'REFRIGERADOS'
                  END AS ALMACEN,
                  COUNT(DISTINCT PALLET_ID) AS PALLETS_TOTALES_PLANIFICADOS,
                  COUNT(DISTINCT CODIGODEVIAJE) AS VIAJES_PLANIFICADOS
                FROM no_picking
                WHERE division IN (1, 2)
                GROUP BY CASE division
                  WHEN 1 THEN 'SECOS'
                  WHEN 2 THEN 'REFRIGERADOS'
                END
                """;
        } else if ("daily_clark_real".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH prm AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to,
                    15 AS tol_min
                  FROM dual
                ),
                mdiv AS (
                  SELECT
                    s.CREFEREN,
                    d.CDIVISIO
                  FROM f602asec s
                  JOIN F601SECT d
                    ON d.CNSECTOR = s.CNSECTOR
                ),
                leg AS (
                  SELECT DISTINCT h.COPECREA
                  FROM f132hist h
                  WHERE h.FCREAREG >= (SELECT p_from FROM prm)
                    AND h.FCREAREG <  (SELECT p_to FROM prm)
                    AND h.CDESCRIP IN (
                      'GUARADO PALETS ENTRADA',
                      'EXTRACCION DE REAPROS',
                      'EXTRACCION TRASPASOS',
                      'SURTIDO P.COMPLETOS'
                    )
                ),
                bas AS (
                  SELECT
                    h.COPECREA,
                    h.FCREAREG,
                    h.CDESCRIP,
                    h.QCANTIDA,
                    h.QPESOREG,
                    h.CZONAORI,
                    h.CUBIORIG,
                    h.CNUPALET,
                    h.CREFEREN,
                    pv.TURNO AS tur_pv
                  FROM f132hist h
                  JOIN leg l
                    ON l.COPECREA = h.COPECREA
                  LEFT JOIN PV_DIA_LABORAL pv
                    ON TO_CHAR(pv.LEGAJO) = TO_CHAR(h.COPECREA)
                   AND pv.FECHA = TO_NUMBER(TO_CHAR(h.FCREAREG,'YYYYMMDD'))
                  WHERE h.FCREAREG >= (SELECT p_from FROM prm)
                    AND h.FCREAREG <  (SELECT p_to FROM prm)
                ),
                enr AS (
                  SELECT
                    b.COPECREA,
                    b.FCREAREG,
                    b.CDESCRIP,
                    b.QCANTIDA,
                    b.QPESOREG,
                    b.CZONAORI,
                    b.CUBIORIG,
                    b.CNUPALET,
                    b.CREFEREN,
                    b.tur_pv,
                    CASE
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '060000'
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '140000' THEN 'TM'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '140000'
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '220000' THEN 'TT'
                      ELSE 'TN'
                    END AS tur_real,
                    CASE
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= TO_CHAR(TO_DATE('06:00:00','HH24:MI:SS') - NUMTODSINTERVAL((SELECT tol_min FROM prm),'MINUTE'),'HH24MISS')
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '060000'
                       AND b.tur_pv = 1 THEN 'TM'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= TO_CHAR(TO_DATE('14:00:00','HH24:MI:SS') - NUMTODSINTERVAL((SELECT tol_min FROM prm),'MINUTE'),'HH24MISS')
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '140000'
                       AND b.tur_pv = 2 THEN 'TT'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= TO_CHAR(TO_DATE('22:00:00','HH24:MI:SS') - NUMTODSINTERVAL((SELECT tol_min FROM prm),'MINUTE'),'HH24MISS')
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '220000'
                       AND b.tur_pv = 3 THEN 'TN'
                      ELSE
                        CASE
                          WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '060000'
                           AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '140000' THEN 'TM'
                          WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '140000'
                           AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '220000' THEN 'TT'
                          ELSE 'TN'
                        END
                    END AS turno,
                    m.CDIVISIO AS division
                  FROM bas b
                  LEFT JOIN mdiv m
                    ON m.CREFEREN = b.CREFEREN
                ),
                enr2 AS (
                  SELECT
                    e.*,
                    CASE
                      WHEN e.turno = 'TM'
                       AND TO_CHAR(e.FCREAREG,'HH24MISS') < '060000'
                      THEN TRUNC(e.FCREAREG)
                      ELSE TRUNC(e.FCREAREG - INTERVAL '6' HOUR)
                    END AS dia_op
                  FROM enr e
                ),
                ven AS (
                  SELECT
                    e.COPECREA,
                    e.FCREAREG,
                    e.CDESCRIP,
                    e.QCANTIDA,
                    e.QPESOREG,
                    e.CZONAORI,
                    e.CUBIORIG,
                    e.CNUPALET,
                    e.CREFEREN,
                    e.turno,
                    e.dia_op,
                    e.division
                  FROM enr2 e
                  WHERE e.FCREAREG >= (SELECT p_from FROM prm)
                    AND e.FCREAREG <  (SELECT p_to FROM prm)
                ),
                mapv AS (
                  SELECT
                    v.*,
                    CASE
                      WHEN TO_CHAR(v.dia_op, 'DY', 'NLS_DATE_LANGUAGE=ENGLISH') IN ('FRI','SAT','SUN')
                      THEN TRUNC(NEXT_DAY(v.dia_op, 'LUNES'))
                      ELSE v.dia_op + 1
                    END AS dia_daily
                  FROM ven v
                ),
                seq AS (
                  SELECT
                    m.*,
                    LAG(m.FCREAREG) OVER (
                      PARTITION BY m.COPECREA, m.dia_op, m.turno
                      ORDER BY m.FCREAREG, m.CDESCRIP, m.CNUPALET, m.CREFEREN
                    ) AS f_prev_turno
                  FROM mapv m
                ),
                dur AS (
                  SELECT
                    s.*,
                    CASE
                      WHEN s.f_prev_turno IS NULL THEN 0
                      ELSE (s.FCREAREG - s.f_prev_turno) * 86400
                    END AS dur_s_turno
                  FROM seq s
                ),
                clk AS (
                  SELECT
                    d.COPECREA,
                    d.FCREAREG,
                    d.CDESCRIP,
                    d.CNUPALET,
                    d.turno,
                    d.dia_op,
                    d.dia_daily,
                    d.division,
                    d.dur_s_turno
                  FROM dur d
                  WHERE d.CDESCRIP IN (
                    'GUARADO PALETS ENTRADA',
                    'EXTRACCION DE REAPROS',
                    'EXTRACCION TRASPASOS',
                    'SURTIDO P.COMPLETOS'
                  )
                ),
                agt AS (
                  SELECT
                    m.dia_op,
                    m.dia_daily,
                    m.turno,
                    m.COPECREA,
                    m.division,
                    COUNT(m.CNUPALET) AS pallets_totales,
                    COUNT(DISTINCT m.CNUPALET) AS pallets_distintos,
                    SUM(m.dur_s_turno) / 3600 AS hs_clark_total
                  FROM clk m
                  GROUP BY
                    m.dia_op,
                    m.dia_daily,
                    m.turno,
                    m.COPECREA,
                    m.division
                )
                SELECT
                  CASE division
                    WHEN 1 THEN 'SECOS'
                    WHEN 2 THEN 'REFRIGERADOS'
                    WHEN 6 THEN 'NOA'
                  END AS ALMACEN,
                  COUNT(DISTINCT COPECREA) AS LEGAJOS,
                  SUM(pallets_totales) AS PALLETS,
                  SUM(pallets_distintos) AS PALLETS_DISTINTOS,
                  ROUND(SUM(pallets_totales) / COUNT(DISTINCT COPECREA), 2) AS PRODUCCION
                FROM agt
                WHERE division IN (1, 2, 6)
                GROUP BY CASE division
                  WHEN 1 THEN 'SECOS'
                  WHEN 2 THEN 'REFRIGERADOS'
                  WHEN 6 THEN 'NOA'
                END
                """;
        } else if ("gestion_productividad_picking".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT * FROM ( " +
                "SELECT " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    UPPER(A.CDESCRIP) AS OPERACION, " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CZONAORI AS ZONA_ORIGEN, " +
                "    A.CUBIORIG AS UBIC_ORIGEN, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.CNPEDIDO AS PEDIDO, " +
                "    A.QCANTIDA AS CANTIDAD, " +
                "    A.QPESOREG AS PESO, " +
                "    'F132HIST' AS SOURCE_TABLE " +
                "FROM F132HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN (SELECT DISTINCT CZONALMA, DESCDIVI FROM VW_UBICACIONES_DIVISION) SUB1 " +
                "  ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND UPPER(A.CDESCRIP) IN ('PICKING', 'ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                "UNION ALL " +
                "SELECT " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    UPPER(A.CDESCRIP) AS OPERACION, " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CZONAORI AS ZONA_ORIGEN, " +
                "    A.CUBIORIG AS UBIC_ORIGEN, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.CNPEDIDO AS PEDIDO, " +
                "    A.QCANTIDA AS CANTIDAD, " +
                "    A.QPESOREG AS PESO, " +
                "    'F132HIST_HIST' AS SOURCE_TABLE " +
                "FROM F132HIST_HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN (SELECT DISTINCT CZONALMA, DESCDIVI FROM VW_UBICACIONES_DIVISION) SUB1 " +
                "  ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND UPPER(A.CDESCRIP) IN ('PICKING', 'ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                ") ORDER BY COPECREA, FH_MOVIMIENTO";
        } else if ("historia_productividad_legajo".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.FECHA, " +
                "    C.DESCRIPCION AS FUNCION, " +
                "    B.PROD_REAL, " +
                "    B.PROD_EQUIVAL_POR_SECTOR " +
                "FROM PV_DIA_LABORAL A " +
                "JOIN PV_LIQUIDAC_DIA_DET2 B ON A.ID = B.ID_PV_DIA_LABORAL " +
                "JOIN PV_GRUPO_DE_FUNCIONES_CAB C ON C.ID = B.ID_PV_GRUPO_DE_FUNCIONES " +
                "WHERE A.FECHA >= ? " +
                "  AND A.FECHA <= ? " +
                "  AND A.LEGAJO = ? " +
                "  AND (B.PROD_REAL > 0 OR B.PROD_EQUIVAL_POR_SECTOR > 0) " +
                "ORDER BY A.FECHA, C.DESCRIPCION";
        } else if ("historia_productividad_bulk".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.FECHA, " +
                "    A.LEGAJO, " +
                "    SUM(B.PROD_REAL) AS PRODUCCION, " +
                "    SUM(B.TIEMPO_DURANTE_PH_EN_SEGUNDOS) AS TIEMPONETO, " +
                "    SUM(B.TIEMPO_TOTAL_EN_SEGUNDOS) AS TIEMPOTOTAL, " +
                "    C.DESCRIPCION AS FUNCION, " +
                "    C.ID_DE_UNIDAD_DE_PRODUCCION AS TIPO " +
                "FROM PV_DIA_LABORAL A " +
                "JOIN PV_LIQUIDAC_DIA_DET2 B ON A.ID = B.ID_PV_DIA_LABORAL " +
                "JOIN PV_GRUPO_DE_FUNCIONES_CAB C ON B.ID_PV_GRUPO_DE_FUNCIONES = C.ID " +
                "WHERE A.FECHA >= ? " +
                "  AND A.FECHA <= ? " +
                "GROUP BY A.FECHA, A.LEGAJO, C.DESCRIPCION, C.ID_DE_UNIDAD_DE_PRODUCCION " +
                "ORDER BY A.FECHA, A.LEGAJO, C.DESCRIPCION";
        } else if ("historia_tnc_legajo".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.FECHA, " +
                "    B.DESCRIP_DE_FUNCION, " +
                "    B.CANTIDAD_DE_CORTES_HECHOS, " +
                "    B.TIEMPO_EXCEDIDO_EN_SEGUNDOS " +
                "FROM PV_DIA_LABORAL A " +
                "JOIN PV_LIQUIDAC_DIA_DET3 B ON A.ID = B.ID_PV_DIA_LABORAL " +
                "WHERE A.LEGAJO = ? " +
                "  AND A.FECHA >= ? " +
                "  AND A.FECHA <= ? " +
                "  AND B.TIEMPO_EXCEDIDO_EN_SEGUNDOS > 0 " +
                "ORDER BY A.FECHA, B.DESCRIP_DE_FUNCION";
        } else if ("historia_actividad_operaciones".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    TO_CHAR(FCREAREG, 'YYYY-MM-DD') AS FECHA, " +
                "    CDESCRIP AS OPERACION " +
                "FROM ( " +
                "    SELECT DISTINCT TRUNC(FCREAREG) AS FCREAREG, CDESCRIP " +
                "    FROM F132HIST " +
                "    WHERE COPECREA = ? " +
                "      AND FCREAREG >= TO_DATE(?, 'YYYY-MM-DD') " +
                "      AND FCREAREG < TO_DATE(?, 'YYYY-MM-DD') + 1 " +
                "      AND CDESCRIP NOT IN ('ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                "    UNION " +
                "    SELECT DISTINCT TRUNC(FCREAREG) AS FCREAREG, CDESCRIP " +
                "    FROM F132HIST_HIST " +
                "    WHERE COPECREA = ? " +
                "      AND FCREAREG >= TO_DATE(?, 'YYYY-MM-DD') " +
                "      AND FCREAREG < TO_DATE(?, 'YYYY-MM-DD') + 1 " +
                "      AND CDESCRIP NOT IN ('ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                ") " +
                "ORDER BY FECHA, OPERACION";
        } else if ("historia_actividad_operaciones_bulk".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    COPECREA AS LEGAJO, " +
                "    TO_CHAR(FCREAREG, 'YYYY-MM-DD') AS FECHA, " +
                "    CDESCRIP AS OPERACION " +
                "FROM ( " +
                "    SELECT DISTINCT COPECREA, TRUNC(FCREAREG) AS FCREAREG, CDESCRIP " +
                "    FROM F132HIST " +
                "    WHERE FCREAREG >= TO_DATE(?, 'YYYY-MM-DD') " +
                "      AND FCREAREG < TO_DATE(?, 'YYYY-MM-DD') + 1 " +
                "      AND CDESCRIP NOT IN ('ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                "      AND COPECREA IS NOT NULL " +
                "    UNION " +
                "    SELECT DISTINCT COPECREA, TRUNC(FCREAREG) AS FCREAREG, CDESCRIP " +
                "    FROM F132HIST_HIST " +
                "    WHERE FCREAREG >= TO_DATE(?, 'YYYY-MM-DD') " +
                "      AND FCREAREG < TO_DATE(?, 'YYYY-MM-DD') + 1 " +
                "      AND CDESCRIP NOT IN ('ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                "      AND COPECREA IS NOT NULL " +
                ") " +
                "ORDER BY FECHA, LEGAJO, OPERACION";
        } else if ("online".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    UPPER(A.CDESCRIP) AS OPERACION, " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CZONAORI AS ZONA_ORIGEN, " +
                "    A.CUBIORIG AS UBIC_ORIGEN, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.CNPEDIDO AS PEDIDO, " +
                "    A.QCANTIDA AS CANTIDAD, " +
                "    A.QPESOREG AS PESO " +
                "FROM F132HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN ( " +
                "    SELECT DISTINCT CZONALMA, DESCDIVI " +
                "    FROM VW_UBICACIONES_DIVISION " +
                ") SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "ORDER BY A.COPECREA, A.FCREAREG";
        } else if ("tiempos_muertos".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.CNPEDIDO AS PEDIDO, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    UPPER(A.CDESCRIP) AS OPERACION, " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN " +
                "FROM F132HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN ( " +
                "    SELECT DISTINCT CZONALMA, DESCDIVI " +
                "    FROM VW_UBICACIONES_DIVISION " +
                ") SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "ORDER BY A.COPECREA, A.FCREAREG";
        } else if ("tnc".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.LEGAJO, " +
                "    A.LOTEINFORMACION AS FECHA_INICIO, " +
                "    A.CODIGO AS CODIGO_TNC, " +
                "    B.DESCRIPCION AS DESCRIPCION_TNC, " +
                "    TRUNC(A.TIEMPOMAXIMO / 60) AS MINUTOS_TOPE, " +
                "    CASE " +
                "        WHEN A.ESTADO != 0 THEN A.TIEMPOREAL " +
                "        ELSE ((SYSDATE - A.LOTEINFORMACION) * 86400) " +
                "    END AS TIEMPO_ACUMULADO " +
                "FROM F957ATNC A " +
                "JOIN F956MTNC B " +
                "  ON A.EMPRESA = B.EMPRESA " +
                " AND A.ALMACEN = B.ALMACEN " +
                " AND A.CODIGO = B.CODIGO " +
                "WHERE A.LOTEINFORMACION >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.LOTEINFORMACION <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND UPPER(TRIM(B.DESCRIPCION)) <> 'FIN DEL TURNO' " +
                "ORDER BY A.LEGAJO, A.LOTEINFORMACION";
        } else if ("tnc_master".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    B.CODIGO AS CODIGO_TNC, " +
                "    A.CODIGO AS CODIGO_PRODUCTIVIDAD, " +
                "    B.DESCRIPCION AS DESCRIPCION_TNC, " +
                "    TRUNC(B.DURACION / 60) AS DURACION_MINUTOS_WF, " +
                "    TRUNC(A.TIEMPO_MAXIMO / 60) AS DURACION_MINUTOS_PRODUCTIVIDAD, " +
                "    A.TIENE_TIEMPO_MAXIMO, " +
                "    A.TIENE_TOLERANCIA_X_EXCESO, " +
                "    TRUNC(A.TOLERANCIA_X_EXCESO / 60) AS TOLERANCIA_X_EXCESO, " +
                "    A.CANTIDAD_DE_OCURRENCIAS, " +
                "    B.REQUIEREAUTORIZACION, " +
                "    B.TIPOTNC " +
                "FROM F956MTNC B " +
                "LEFT JOIN PV_FUNCION A " +
                "  ON REGEXP_LIKE(A.CODIGO, '^RF-TNC-[0-9]+$') " +
                " AND TO_NUMBER(REPLACE(A.CODIGO, 'RF-TNC-', '')) = B.CODIGO " +
                "ORDER BY B.CODIGO";
        } else if ("tnc_monitor".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH BASE AS ( " +
                "    SELECT " +
                "        A.EMPRESA, " +
                "        A.ALMACEN, " +
                "        A.LEGAJO, " +
                "        A.CODIGO AS CODIGO_TNC, " +
                "        A.LOTEINFORMACION, " +
                "        A.ULTIMAMODIFICACION, " +
                "        TO_CHAR(A.LOTEINFORMACION, 'YYYY-MM-DD') AS DIA_TNC, " +
                "        B.DESCRIPCION AS TNC, " +
                "        A.ESTADO, " +
                "        TRUNC( " +
                "            CASE " +
                "                WHEN A.ESTADO <> 0 THEN A.TIEMPOREAL / 60 " +
                "                ELSE (SYSDATE - A.LOTEINFORMACION) * 1440 " +
                "            END " +
                "        ) AS MINUTOS_CONSUMIDOS, " +
                "        TRUNC(A.TIEMPOMAXIMO / 60) AS MINUTOS_TOPE " +
                "    FROM F957ATNC A " +
                "    JOIN F956MTNC B " +
                "      ON A.EMPRESA = B.EMPRESA " +
                "     AND A.ALMACEN = B.ALMACEN " +
                "     AND A.CODIGO = B.CODIGO " +
                "    WHERE A.LOTEINFORMACION >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "      AND A.LOTEINFORMACION < TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "      AND A.CODIGO <> 62 " +
                "      AND UPPER(TRIM(B.DESCRIPCION)) <> 'FIN DEL TURNO' " +
                ") " +
                "SELECT " +
                "    A.EMPRESA, " +
                "    A.ALMACEN, " +
                "    A.LEGAJO, " +
                "    C.NOMBRE AS OPERARIO, " +
                "    C.AREA_PERS_TXT AS AREA, " +
                "    C.PUESTO AS PUESTO, " +
                "    C.FOTO AS FOTO, " +
                "    A.CODIGO_TNC, " +
                "    A.DIA_TNC, " +
                "    TO_CHAR(LOTEINFORMACION, 'YYYY-MM-DD HH24:MI:SS') AS LOTEINFORMACION_TS, " +
                "    TO_CHAR(ULTIMAMODIFICACION, 'YYYY-MM-DD HH24:MI:SS') AS ULTIMAMODIFICACION_TS, " +
                "    TO_CHAR(LOTEINFORMACION, 'HH24:MI:SS') AS INICIO, " +
                "    CASE " +
                "        WHEN ESTADO = 0 THEN NULL " +
                "        WHEN ULTIMAMODIFICACION = LOTEINFORMACION THEN NULL " +
                "        ELSE TO_CHAR(ULTIMAMODIFICACION, 'HH24:MI:SS') " +
                "    END AS FIN, " +
                "    TNC, " +
                "    CASE " +
                "        WHEN ESTADO = 0 THEN 'Activo' " +
                "        ELSE 'Finalizado' " +
                "    END AS ESTADO, " +
                "    MINUTOS_CONSUMIDOS AS MINUTOS, " +
                "    MINUTOS_TOPE AS TOPE, " +
                "    MINUTOS_CONSUMIDOS - MINUTOS_TOPE AS DIFERENCIA, " +
                "    CASE " +
                "        WHEN MINUTOS_CONSUMIDOS <= MINUTOS_TOPE OR MINUTOS_TOPE = 0 THEN 'Dentro de tope' " +
                "        ELSE 'Excedido' " +
                "    END AS ESTADO_TIEMPO " +
                "FROM BASE A " +
                "LEFT JOIN ( " +
                "    SELECT " +
                "        CASE " +
                "            WHEN REGEXP_LIKE(TRIM(LEGAJO), '^[0-9]+$') THEN TO_NUMBER(TRIM(LEGAJO)) " +
                "        END AS LEGAJO_NUM, " +
                "        NOMBRE, " +
                "        AREA_PERS_TXT, " +
                "        PUESTO, " +
                "        FOTO " +
                "    FROM WF_ACTIVE_EMPLOYEE " +
                ") C ON A.LEGAJO = C.LEGAJO_NUM " +
                "ORDER BY LOTEINFORMACION DESC";
        } else if ("plantel".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "A.FCREAREG AS FHMovimiento, " +
                "A.COPECREA AS Operario, " +
                "A.QCANTIDA AS Cantidad, " +
                "A.CZONAORI AS ZonaOrigen, " +
                "A.CNUPALET AS NroPallet, " +
                "A.QPESOREG AS PesoRegistrado, " +
                "SUB1.DESCDIVI AS Almacen " +
                "FROM F132HIST A " +
                "JOIN ( " +
                "  SELECT DISTINCT CZONALMA, DESCDIVI " +
                "  FROM VW_UBICACIONES_DIVISION " +
                "  WHERE DESCDIVI IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS') " +
                ") SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "AND A.CDESCRIP = 'Picking' " +
                "ORDER BY A.FCREAREG";
        } else if ("picking_ubicaciones_hist".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH UBICS AS ( " +
                "  SELECT CUBIORIG " +
                "  FROM F132HIST_HIST A " +
                "  WHERE UPPER(CDESCRIP) = 'PICKING' " +
                "    AND CUBIORIG IS NOT NULL " +
                ") " +
                "SELECT DISTINCT CUBIORIG AS UBICACION_CODIGO " +
                "FROM UBICS " +
                "ORDER BY CUBIORIG";
        } else {
            sql =
                "SELECT " +
                "FCREAREG AS FHMovimiento, " +
                "CTIPTRAB AS TipoTrabajo, " +
                "CNUPALET AS NroPallet, " +
                "QCANTIDA AS Cantidad, " +
                "CREFEREN AS Referencia, " +
                "CZONAORI AS ZonaOrigen, " +
                "CUBIORIG AS UbicOrige, " +
                "COPECREA AS Operario, " +
                "QPESOREG AS PesoRegistrado " +
                "FROM F132HIST " +
                "WHERE FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "AND FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "AND CDESCRIP = 'Picking' " +
                "ORDER BY FCREAREG";
        }

        Class.forName("oracle.jdbc.OracleDriver");

        try (
            Connection conn = DriverManager.getConnection(jdbcUrl, user, password);
            PreparedStatement ps = conn.prepareStatement(sql)
        ) {
            if (!"picking_ubicaciones_hist".equalsIgnoreCase(queryKey) && !"tnc_master".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaDesde);
                ps.setString(2, fechaHasta);
                if ("gestion_productividad_picking".equalsIgnoreCase(queryKey)) {
                    ps.setString(3, fechaDesde);
                    ps.setString(4, fechaHasta);
                } else if ("historia_productividad_legajo".equalsIgnoreCase(queryKey)) {
                    ps.setString(3, legajo);
                } else if ("historia_tnc_legajo".equalsIgnoreCase(queryKey)) {
                    ps.setString(1, legajo);
                    ps.setString(2, fechaDesde);
                    ps.setString(3, fechaHasta);
                } else if ("historia_actividad_operaciones".equalsIgnoreCase(queryKey)) {
                    ps.setString(1, legajo);
                    ps.setString(2, fechaDesde);
                    ps.setString(3, fechaHasta);
                    ps.setString(4, legajo);
                    ps.setString(5, fechaDesde);
                    ps.setString(6, fechaHasta);
                } else if ("historia_actividad_operaciones_bulk".equalsIgnoreCase(queryKey)) {
                    ps.setString(3, fechaDesde);
                    ps.setString(4, fechaHasta);
                }
            }

            try (ResultSet rs = ps.executeQuery()) {
                StringBuilder out = new StringBuilder();
                out.append("[");
                boolean first = true;
                while (rs.next()) {
                    if (!first) out.append(",");
                    first = false;

                    if ("online".equalsIgnoreCase(queryKey) || "tiempos_muertos".equalsIgnoreCase(queryKey) || "tnc".equalsIgnoreCase(queryKey) || "tnc_master".equalsIgnoreCase(queryKey) || "tnc_monitor".equalsIgnoreCase(queryKey) || "picking_analysis".equalsIgnoreCase(queryKey) || "daily_picking_real".equalsIgnoreCase(queryKey) || "daily_despacho_real".equalsIgnoreCase(queryKey) || "daily_picking_plan".equalsIgnoreCase(queryKey) || "daily_despacho_plan".equalsIgnoreCase(queryKey) || "daily_spc_plan".equalsIgnoreCase(queryKey) || "daily_clark_real".equalsIgnoreCase(queryKey) || "picking_ubicaciones_hist".equalsIgnoreCase(queryKey) || "gestion_productividad_picking".equalsIgnoreCase(queryKey) || "historia_productividad_legajo".equalsIgnoreCase(queryKey) || "historia_productividad_bulk".equalsIgnoreCase(queryKey) || "historia_tnc_legajo".equalsIgnoreCase(queryKey) || "historia_actividad_operaciones".equalsIgnoreCase(queryKey) || "historia_actividad_operaciones_bulk".equalsIgnoreCase(queryKey)) {
                        appendGenericJsonRow(rs, out);
                        continue;
                    }

                    Timestamp ts = rs.getTimestamp("FHMOVIMIENTO");
                    String fh = ts == null ? "" : TS_FMT.format(ts.toInstant());

                    out.append("{")
                        .append("\"FHMOVIMIENTO\":\"").append(esc(fh)).append("\",")
                        .append("\"TIPOTRABAJO\":\"").append(esc(hasColumn(rs, "TIPOTRABAJO") ? str(rs.getObject("TIPOTRABAJO")) : "")).append("\",")
                        .append("\"NROPALLET\":\"").append(esc(hasColumn(rs, "NROPALLET") ? str(rs.getObject("NROPALLET")) : "")).append("\",")
                        .append("\"CANTIDAD\":").append(num(rs.getObject("CANTIDAD"))).append(",")
                        .append("\"REFERENCIA\":\"").append(esc(hasColumn(rs, "REFERENCIA") ? str(rs.getObject("REFERENCIA")) : "")).append("\",")
                        .append("\"ZONAORIGEN\":\"").append(esc(hasColumn(rs, "ZONAORIGEN") ? str(rs.getObject("ZONAORIGEN")) : "")).append("\",")
                        .append("\"UBICORIGE\":\"").append(esc(hasColumn(rs, "UBICORIGE") ? str(rs.getObject("UBICORIGE")) : "")).append("\",")
                        .append("\"OPERARIO\":\"").append(esc(str(rs.getObject("OPERARIO")))).append("\",")
                        .append("\"PESOREGISTRADO\":").append(num(rs.getObject("PESOREGISTRADO")));

                    try {
                        if (hasColumn(rs, "ALMACEN")) {
                        out.append(",\"ALMACEN\":\"").append(esc(str(rs.getObject("ALMACEN")))).append("\"");
                        }
                    } catch (Exception ignored) {}

                    out.append("}");
                }
                out.append("]");
                System.out.print(out);
            }
        }
    }
}
